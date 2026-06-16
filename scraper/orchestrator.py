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
import sys
import time
from datetime import datetime, timezone

import psycopg2

import config
from scraper import normaliser
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
        logging.FileHandler("scraper.log"),
    ],
)
log = logging.getLogger(__name__)


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
            log.info("── Scraping: %s ──", source)
            try:
                raw = parser.scrape()
                all_raw.extend(raw)
                run_stats[source] = {
                    "status":    "SUCCESS",
                    "raw_count": len(raw),
                    # new/updated/price_changes filled in after db.upsert()
                    "new":           0,
                    "updated":       0,
                    "price_changes": 0,
                    "suspected_sold": 0,
                }
                log.info("[%s] Collected %d listings", source, len(raw))
            except Exception as exc:
                log.error("[%s] FAILED: %s", source, exc, exc_info=True)
                run_stats[source] = {
                    "status":    "FAILED",
                    "raw_count": 0,
                    "new":       0, "updated": 0,
                    "error":     str(exc)[:500],
                }

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
        db_stats = db.upsert(normalised, active_listings)

        # db_stats["per_source"] carries exact new/updated/price_changes counts
        # per portal as measured at write time. Merge them into run_stats so
        # both the Telegram notification and the run log reflect real numbers,
        # not fractional approximations.
        for source in run_stats:
            if run_stats[source]["status"] == "SUCCESS":
                per = db_stats["per_source"].get(source, {})
                run_stats[source]["new"]            = per.get("new",           0)
                run_stats[source]["updated"]        = per.get("updated",       0)
                run_stats[source]["price_changes"]  = per.get("price_changes", 0)
                # suspected_sold is not per-source in current db_stats; zero is correct
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

    db = None
    try:
        db = DatabaseWriter(config.DATABASE_URL)

        from scraper.health_checker import HealthChecker
        checker = HealthChecker(db)
        stats   = checker.run(force_all=force_all)

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