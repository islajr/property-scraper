"""
orchestrator.py — PS-0 PropertyScraper pipeline entry point.

Wires: parsers -> normaliser -> geocoder -> db_writer -> notifier. 

Run via:
    python -m scraper.orchestrator
    
Each listing portal is wrapped in an independent try/except.
A single portal failure cannot crash the entire pipeline, not suppress results from others.
Run status is also logged to raw_data.scrape_runs and summarized on telegram bot 

"""

from __future__ import annotations

import logging
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
from scraper.parsers.jiji import JijiParser


# —————— Logging setup —————————
logging.basicConfig(
    level = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scraper.log"),
    ],
)
log = logging.getLogger(__name__)


def run():
    log.info("=" * 60)
    log.info("PropertyScraper starting - %s", datetime.now(timezone.utc).isoformat())
    log.info("=" * 60)
    
    run_start = time.time()
    db = None
    
    try:
        # ——————— Initialize infrastructure ———————————————————————————————————————————
        db       = DatabaseWriter(config.DATABASE_URL)
        geocoder = Geocoder(db)
        
        # Fetch active listings before scraping for history comparison and deduplication
        log.info("Fetching active listing snapshots from DB...")
        active_listings = db.fetch_active_listings() # fetch {(source, ext_id): current_price_koo}
        log.info("Active listings: %d", len(active_listings))
        
        # Run each portal parser
        all_raw_listings = []
        run_stats = {}  # source: {count, status}
        
        parsers = [
            PropertyProParser(config),
            PrivatePropertyParser(config),
            NigeriaPropertyCentreParser(config),
            JijiParser(config)
        ]
    
        for parser in parsers:
            source = parser.source
            log.info("——— Scraping %s ———", source)
            
            try:
                raw_listing = parser.scrape()
                all_raw_listings.extend(raw_listing)
                run_stats[source] = {"new": 0, "updated": 0, "status": "SUCCESS", "count": len(raw_listing)}
                log.info("[%s] Collected %d listings", source, len(raw_listing))
            
            except Exception as exc:
                log.error("[%s] FAILED: %s ", source, exc, exc_info=True)
                run_stats[source] = {
                    "new": 0, "updated": 0, "status": 'FAILED', 
                    'error': str(exc)[:500], "count": 0}

        log.info("Total raw listings collected: %s", len(all_raw_listings))
        
        # ——— Normalization ————————————————————————————————————————————————————————
        log.info("Normalising listings...")
        normalised = []
        for raw_listing in all_raw_listings:
            try:
                normalised.append(normaliser.normalise(raw_listing))
            except Exception as exc:
                log.warning("Normalisation error for %s/%s: %s", raw_listing.source, raw_listing.external_id, exc)
        
        # ——— Geocoding ————————————————————————————————
        log.info("Geocoding listings via Nominate/OSM...")
        normalised = geocoder.enrich(normalised)
        # Log progress? Report completion?
        
        # ——— Database upsert ——————————————————————————
        log.info("Writing to database...")
        stats = db.upsert(normalised, active_listings)
        
        for source in run_stats:
            if run_stats[source]["status"] == "SUCCESS":
                count = run_stats[source]["count"]
                # Proportional share — exact per-portal breakdown would require
                # per-portal source tracking through the pipeline (future improvement)
                total = len(normalised) or 1
                fraction = count / total
                run_stats[source]["new"]     = int(stats["new"]     * fraction)
                run_stats[source]["updated"] = int(stats["updated"] * fraction)
                run_stats[source]["suspected_sold"] = int(stats["suspected_sold"] * fraction)
                run_stats[source]["price_changes"]  = int(stats["price_changes"]  * fraction)
        
        # ——— Run log —————————————————————————————————————————
        duration = time.time() - run_start
        db.write_run_log(run_stats, duration)
        
        # ——— Aggregate stats for notification display ——————————————————
        geocoded_count = sum(1 for l in normalised if l.geocoded)
        prices_parsed = sum(1 for l in normalised if not l.price_parse_failed)
        
        aggregate = {
            "new":              stats["new"],
            "updated":          stats["updated"],
            "price_changes":    stats["price_changes"],
            "suspected_sold":   stats["suspected_sold"],
            "geocoded":         geocoded_count,
            "geocode_total":    len(normalised),
            "prices_parsed":    prices_parsed,
            "prices_total":     len(normalised),
        }
        
        # ——— Serve telegram notification ———————————————————
        notifier.send_summary(aggregate, run_stats, duration)
        log.info("Run complete in %.1fs —— new: %d, updated: %d, suspected_sold: %d", 
                 duration, stats["new"], stats["updated"], stats["suspected_sold"])
        
        
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

if __name__ == "__main__":
    run()