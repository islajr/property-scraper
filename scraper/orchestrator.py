"""
orchestrator.py — PS-0 PropertyScraper pipeline entry point.

Two modes:

  Discovery (default):
    Wires parsers → normaliser → geocoder → db_writer → notifier.
    Run via: python -m scraper.orchestrator
             ./run.sh

  Health check:
    Verifies individual listing URLs and confirms removals.
    Run via: python -m scraper.orchestrator --health-check
             ./run.sh --health-check

Each portal in discovery mode is wrapped in an independent try/except.
A single portal failure cannot crash the pipeline or suppress results from others.
Run status is logged to raw_data.scrape_runs and summarised in Telegram.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import socket
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import psycopg2

import config
from scraper import normaliser
from scraper import checkpoint
from scraper.db_writer import DatabaseWriter
from scraper.geocoder import Geocoder
from scraper import notifier
from scraper.parsers.propertypro import PropertyProParser
from scraper.parsers.privateproperty import PrivatePropertyParser
from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
# from scraper.parsers.jiji import JijiParser

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("scraper.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def check_database_dns(db_url: str) -> bool:
    """Check if the database hostname can be resolved (pre-flight network check)."""
    try:
        parsed = urlparse(db_url)
        hostname = parsed.hostname
        if not hostname:
            return True
        socket.gethostbyname(hostname)
        return True
    except socket.gaierror:
        return False



# ═════════════════════════════════════════════════════════════════════════════
# Discovery mode (default weekly run)
# ═════════════════════════════════════════════════════════════════════════════

def run():
    log.info("═" * 60)
    log.info("PropertyScraper DISCOVERY starting — %s",
             datetime.now(timezone.utc).isoformat())
    log.info("═" * 60)

    run_start = time.time()
    db = None

    # Check for --fresh flag
    fresh_run = "--fresh" in sys.argv

    # Try loading checkpoint
    chk = None
    if not fresh_run:
        chk = checkpoint.load_checkpoint("discovery")

    try:
        # ── Initialise infrastructure ─────────────────────────────────────────
        db       = DatabaseWriter(config.DATABASE_URL)
        geocoder = Geocoder(db)

        log.info("Fetching active listings snapshot from DB...")
        active_listings = db.fetch_active_listings()
        log.info("Active listings in DB: %d", len(active_listings))

        # ── Run each portal parser ────────────────────────────────────────────
        all_raw    = []
        run_stats  = {}   # {source: {status, raw_count, error}}
        completed_portals = set()

        if chk:
            all_raw = chk.get("collected_raw_listings", [])
            run_stats = chk.get("run_stats", {})
            completed_portals = set(chk.get("completed_portals", []))
            log.info("Resuming run with %d raw listings already in memory", len(all_raw))

        # Check for --portals flag (comma-separated list, e.g. --portals=privateproperty,nigeriapropertycentre)
        allowed_portals = None
        for arg in sys.argv:
            if arg.startswith("--portals="):
                allowed_portals = set(arg.split("=")[1].split(","))

        parsers = [
            PropertyProParser(active_listings),
            PrivatePropertyParser(active_listings),
            NigeriaPropertyCentreParser(active_listings),
            # JijiParser(active_listings),
        ]

        if allowed_portals:
            parsers = [p for p in parsers if p.source in allowed_portals]
            log.info("Filtering discovery run to portals: %s", ", ".join(allowed_portals))

        for parser in parsers:
            source = parser.source
            
            # Skip if already completed
            if source in completed_portals:
                log.info("── Skipping completed portal: %s ──", source)
                continue

            log.info("── Scraping: %s ──", source)
            
            # Prepare feed completions tracker for checkpoint callbacks
            completed_feeds = []
            if chk and chk.get("partial_portal") == source:
                completed_feeds = chk.get("completed_feeds", [])

            # Define page callback
            def make_page_complete_callback(source_name, feeds_list):
                def callback(feed_url, page_num, page_results):
                    # Append new items to in-memory list
                    all_raw.extend(page_results)
                    
                    # Update local statistics
                    if source_name not in run_stats:
                        run_stats[source_name] = {
                            "status": "IN_PROGRESS",
                            "raw_count": 0,
                            "new": 0, "updated": 0, "price_changes": 0, "suspected_sold": 0
                        }
                    run_stats[source_name]["raw_count"] = len([r for r in all_raw if r.source == source_name])
                    
                    # Save checkpoint
                    checkpoint.save_checkpoint({
                        "mode": "discovery",
                        "completed_portals": list(completed_portals),
                        "partial_portal": source_name,
                        "completed_feeds": list(feeds_list),
                        "partial_feed": feed_url,
                        "partial_feed_page": page_num,
                        "collected_raw_listings": all_raw,
                        "run_stats": run_stats
                    })
                return callback

            try:
                # Run scrape with checkpoint and callback
                parser.scrape(
                    checkpoint_state=chk,
                    on_page_complete=make_page_complete_callback(source, completed_feeds)
                )
                
                # When done, update run_stats for success
                run_stats[source] = {
                    "status":    "SUCCESS",
                    "raw_count": len([r for r in all_raw if r.source == source]),
                    "new":           0,
                    "updated":       0,
                    "price_changes": 0,
                    "suspected_sold": 0,
                }
                completed_portals.add(source)
                
                # Save checkpoint showing portal completed
                checkpoint.save_checkpoint({
                    "mode": "discovery",
                    "completed_portals": list(completed_portals),
                    "partial_portal": None,
                    "completed_feeds": [],
                    "partial_feed": None,
                    "partial_feed_page": 1,
                    "collected_raw_listings": all_raw,
                    "run_stats": run_stats
                })
                
                log.info("[%s] Scrape complete. Collected total %d listings", source, run_stats[source]["raw_count"])
                
            except Exception as exc:
                log.error("[%s] FAILED: %s", source, exc, exc_info=True)
                run_stats[source] = {
                    "status":    "FAILED",
                    "raw_count": len([r for r in all_raw if r.source == source]),
                    "new":       0, "updated": 0,
                    "error":     str(exc)[:500],
                }
                # Even if failed, save checkpoint showing this portal failed so we can skip/move on if restarted
                completed_portals.add(source)
                checkpoint.save_checkpoint({
                    "mode": "discovery",
                    "completed_portals": list(completed_portals),
                    "partial_portal": None,
                    "completed_feeds": [],
                    "partial_feed": None,
                    "partial_feed_page": 1,
                    "collected_raw_listings": all_raw,
                    "run_stats": run_stats
                })

        raw_total = len(all_raw)
        log.info("Total raw listings collected from portals: %d", raw_total)

        # ── Normalise ─────────────────────────────────────────────────────────
        log.info("Normalising listings...")
        normalised = []
        for raw in all_raw:
            try:
                normalised.append(normaliser.normalise(raw))
            except Exception as exc:
                log.warning("Normalisation error for %s/%s: %s",
                            raw.source, raw.external_id, exc)

        # ── Geocode ───────────────────────────────────────────────────────────
        log.info("Geocoding listings (Nominatim/OSM)...")
        normalised = geocoder.enrich(normalised)

        # ── Database upsert ───────────────────────────────────────────────────
        log.info("Writing to database...")
        scraped_sources = {source for source, info in run_stats.items() if info["status"] == "SUCCESS" and info["raw_count"] > 0}
        db_stats = db.upsert(normalised, active_listings, scraped_sources=scraped_sources)

        # db_stats["per_source"] carries exact new/updated/price_changes counts
        for source in run_stats:
            if run_stats[source]["status"] == "SUCCESS":
                per = db_stats["per_source"].get(source, {})
                run_stats[source]["new"]            = per.get("new",           0)
                run_stats[source]["updated"]        = per.get("updated",       0)
                run_stats[source]["price_changes"]  = per.get("price_changes", 0)
                run_stats[source]["suspected_sold"] = 0

        log.info(
            "DB write complete — raw from portals: %d, within-run duplicates dropped: %d, "
            "written (deduplicated): %d — new: %d, updated: %d",
            raw_total,
            db_stats["duplicates_dropped"],
            raw_total - db_stats["duplicates_dropped"],
            db_stats["new"],
            db_stats["updated"],
        )

        # ── Run log ───────────────────────────────────────────────────────────
        duration = time.time() - run_start
        db.write_run_log(run_stats, duration)

        # ── Aggregate stats for notification ──────────────────────────────────
        geocoded_count = sum(1 for l in normalised if l.geocoded)
        prices_parsed  = sum(1 for l in normalised if not l.price_parse_failed)
        total_listings = db.count_total_listings()

        aggregate = {
            "new":                db_stats["new"],
            "updated":            db_stats["updated"],
            "price_changes":      db_stats["price_changes"],
            "suspected_sold":     db_stats["suspected_sold"],
            "duplicates_dropped": db_stats["duplicates_dropped"],
            "raw_total":          raw_total,
            "geocoded":           geocoded_count,
            "geocode_total":      len(normalised),
            "prices_parsed":      prices_parsed,
            "prices_total":       len(normalised),
        }

        # ── Telegram notification ─────────────────────────────────────────────
        notifier.send_summary(aggregate, run_stats, duration,
                              total_listings=total_listings)

        # Clear checkpoint on successful completion of the entire run
        checkpoint.clear_checkpoint()

        log.info(
            "Run complete in %.1fs — new: %d, updated: %d, "
            "duplicates_dropped: %d, suspected_sold: %d",
            duration,
            db_stats["new"],
            db_stats["updated"],
            db_stats["duplicates_dropped"],
            db_stats["suspected_sold"],
        )

    except Exception as exc:
        log.critical("Orchestrator crashed: %s", exc, exc_info=True)
        try:
            notifier.send_error(str(exc))
        except Exception:
            pass
        raise
    finally:
        if db:
            db.close()


# ═════════════════════════════════════════════════════════════════════════════
# Health check mode
# ═════════════════════════════════════════════════════════════════════════════

def run_health_checks(force_all: bool = False):
    """
    Fetches every ACTIVE listing URL individually and confirms whether it is
    still live. Only this mode may mark listings as REMOVED.
    """
    log.info("═" * 60)
    log.info("PropertyScraper HEALTH CHECK starting — %s",
             datetime.now(timezone.utc).isoformat())
    log.info("═" * 60)

    # 1. Pre-flight check: is the database host resolvable? (i.e. is internet connected?)
    if not check_database_dns(config.DATABASE_URL):
        log.warning("[orchestrator] Pre-flight network check failed: database hostname is unreachable (DNS resolution failed). Assuming offline/no network. Exiting cleanly.")
        return

    # Check for --fresh flag
    fresh_run = "--fresh" in sys.argv

    # Try loading checkpoint
    chk = None
    if not fresh_run:
        chk = checkpoint.load_checkpoint("health_check")

    db = None
    try:
        db = DatabaseWriter(config.DATABASE_URL)

        # 2. Timing Guard check (skip if success run happened < 22 hours ago, unless force_all is True or resuming from chk)
        if not force_all and not chk:
            last_run = db.fetch_last_successful_run("health_check")
            if last_run:
                now = datetime.now(timezone.utc)
                elapsed = now - last_run
                hours_elapsed = elapsed.total_seconds() / 3600.0
                if hours_elapsed < config.HEALTH_CHECK_RUN_INTERVAL_HOURS:
                    log.info("[orchestrator] Health check skipped: last successful run was %.1f hours ago (minimum interval: %dh).",
                             hours_elapsed, config.HEALTH_CHECK_RUN_INTERVAL_HOURS)
                    return

        from scraper.health_checker import HealthChecker
        checker = HealthChecker(db)
        
        # Define callback for saving checkpoint progress
        def on_batch_complete(candidates, last_processed_idx, stats):
            checkpoint.save_checkpoint({
                "mode": "health_check",
                "candidates": candidates,
                "last_processed_idx": last_processed_idx,
                "stats": stats
            })

        run_start = time.time()
        stats   = checker.run(
            force_all=force_all,
            checkpoint_state=chk,
            on_batch_complete=on_batch_complete
        )
        duration = time.time() - run_start

        # 3. Log the successful run
        db.write_run_log({
            "health_check": {
                "new": 0,
                "updated": stats.get("confirmed_active", 0),
                "suspected_sold": stats.get("confirmed_removed", 0),
                "price_changes": stats.get("price_changes", 0),
                "status": "SUCCESS",
                "error": None
            }
        }, duration)

        # Clear checkpoint on successful completion
        checkpoint.clear_checkpoint()

        try:
            notifier.send_health_check_summary(stats)
        except AttributeError:
            log.info(
                "[health_checker] notifier.send_health_check_summary not implemented. "
                "Stats: checked=%d removed=%d active=%d errors=%d",
                stats.get("checked", 0),
                stats.get("confirmed_removed", 0),
                stats.get("confirmed_active", 0),
                stats.get("price_changes", 0),
                stats.get("errors", 0),
            )

        # Trigger telemetry dashboard compilation & deploy
        try:
            log.info("[orchestrator] Re-rendering telemetry dashboard...")
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            render_script = os.path.join(root_dir, "scripts", "render_dashboard.py")
            if os.path.exists(render_script):
                subprocess.run([sys.executable, render_script, "--force"], check=False)
        except Exception as t_err:
            log.warning("[orchestrator] Could not trigger dashboard update: %s", t_err)

    except Exception as exc:
        log.critical("Health check crashed: %s", exc, exc_info=True)
        try:
            notifier.send_error(str(exc))
        except Exception:
            pass
        raise
    finally:
        if db:
            db.close()



# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "--health-check" in sys.argv:
        force_all = "--all" in sys.argv or "--force" in sys.argv
        run_health_checks(force_all=force_all)
    else:
        run()