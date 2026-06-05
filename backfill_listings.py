#!/usr/bin/env python3
"""
backfill_listings.py — Retroactively normalise and geocode listings in the database.

Usage:
    # Dry run (default):
    python3 backfill_listings.py
    
    # Actually apply changes:
    python3 backfill_listings.py --commit
"""

import sys
import argparse
import logging
from typing import List, Dict, Tuple, Optional

# Set up logging before imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("backfill")

# Ensure parent directory is in import path
sys.path.append("/home/isla-jr/Documents/se-workspace/property-scraper")

import config
from scraper.db_writer import DatabaseWriter
from scraper.geocoder import Geocoder
from scraper.normaliser import normalise_neighbourhood


def main():
    parser = argparse.ArgumentParser(description="Backfill script for property scraper database")
    parser.add_argument(
        "--commit", 
        action="store_true", 
        help="Actually apply updates and commit to database (default is dry-run)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Batch size for database transaction commits (default 200)"
    )
    args = parser.parse_args()

    commit = args.commit
    batch_size = args.batch_size

    log.info("=" * 60)
    log.info("DATABASE BACKFILL starting (Mode: %s)", "COMMIT" if commit else "DRY-RUN (No writes)")
    log.info("=" * 60)

    try:
        db = DatabaseWriter(config.DATABASE_URL)
        geocoder = Geocoder(db)
    except Exception as exc:
        log.error("Failed to connect to database or initialize geocoder: %s", exc)
        sys.exit(1)

    # 1. Fetch all candidate listings
    log.info("Fetching unnormalised listings from database...")
    try:
        with db.conn.cursor() as cur:
            cur.execute("""
                SELECT id, raw_address, city, geocoded, lat, lng 
                FROM raw_data.scraped_listings 
                WHERE neighbourhood_normalised = FALSE
            """)
            rows = cur.fetchall()
    except Exception as exc:
        log.error("Failed to fetch listings: %s", exc)
        sys.exit(1)

    total_candidates = len(rows)
    log.info("Found %d unnormalised listings.", total_candidates)

    if total_candidates == 0:
        log.info("No listings require backfilling. Exiting.")
        sys.exit(0)

    # 2. Process listings
    processed_count = 0
    normalised_count = 0
    geocoded_count = 0
    new_geocodes_called = 0
    
    proposed_updates: List[Tuple[int, str, Optional[float], Optional[float]]] = []

    # Get the geocoder memory cache size before run
    initial_cache_size = len(geocoder.memory_cache)

    log.info("Processing listings and extracting neighbourhoods...")
    for idx, (listing_id, raw_address, city, old_geocoded, old_lat, old_lng) in enumerate(rows, 1):
        if not raw_address:
            continue
            
        nb, was_norm = normalise_neighbourhood(raw_address)
        processed_count += 1
        
        if was_norm:
            normalised_count += 1
            
            # Re-geocode the normalised neighbourhood
            # geocoder._geocode checks self.memory_cache (preloaded from DB)
            # and falls back to Nominatim on cache miss.
            try:
                lat, lng = geocoder._geocode(nb, city)
            except Exception as exc:
                log.warning("Geocoding failed for (%s, %s): %s", nb, city, exc)
                lat, lng = None, None
                
            if lat is not None:
                geocoded_count += 1
                
            proposed_updates.append((listing_id, nb, lat, lng))
            
            if idx % 100 == 0:
                log.info("  Processed %d/%d listings...", idx, total_candidates)

    # Calculate Nominatim API calls made
    final_cache_size = len(geocoder.memory_cache)
    api_calls_made = final_cache_size - initial_cache_size

    log.info("-" * 60)
    log.info("Processing complete. Statistics:")
    log.info("  Total candidates:         %d", total_candidates)
    log.info("  Processed:                %d", processed_count)
    log.info("  Successfully Normalised:  %d (%.2f%%)", normalised_count, normalised_count/processed_count*100 if processed_count else 0)
    log.info("  Successfully Geocoded:    %d (%.2f%%)", geocoded_count, geocoded_count/normalised_count*100 if normalised_count else 0)
    log.info("  New Nominatim API Calls:  %d", api_calls_made)
    log.info("-" * 60)

    # 3. Write updates to DB (if commit mode enabled)
    if commit and proposed_updates:
        log.info("Writing updates to the database in batches of %d...", batch_size)
        try:
            batch: List[Tuple[int, str, Optional[float], Optional[float]]] = []
            for i, update in enumerate(proposed_updates, 1):
                batch.append(update)
                if len(batch) >= batch_size or i == len(proposed_updates):
                    # Write batch
                    with db.conn.cursor() as cur:
                        for listing_id, nb, lat, lng in batch:
                            cur.execute("""
                                UPDATE raw_data.scraped_listings
                                SET neighbourhood = %s,
                                    neighbourhood_normalised = TRUE,
                                    lat = %s,
                                    lng = %s,
                                    geocoded = %s
                                WHERE id = %s
                            """, (nb, lat, lng, lat is not None, listing_id))
                    db.conn.commit()
                    log.info("  Committed %d/%d updates...", i, len(proposed_updates))
                    batch = []
            log.info("Database backfill successfully completed and committed!")
        except Exception as exc:
            db.conn.rollback()
            log.error("Database transaction failed. Rolled back changes: %s", exc)
            sys.exit(1)
    else:
        if proposed_updates:
            log.info("DRY-RUN mode. No changes were written. Run with --commit to apply these changes.")
        else:
            log.info("No candidates qualified for updates.")

    db.close()


if __name__ == "__main__":
    main()
