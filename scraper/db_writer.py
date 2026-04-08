"""
db_writer.py — All database write and read operations for PS-0 PropertyScraper.

Writes EXCLUSIVELY to the raw_data schema on Supabase.
Never touches synthetic_properties, macro, geospatial, or any other schema.

Core operations:
  fetch_active_listings()           → {(source, ext_id): current_price_kobo}
  upsert()                          → insert new / update existing listings + emit history events
  write_run_log()                   → one row per portal per run in raw_data.scrape_runs
  fetch_geocode_cache()             → load persistent geocode pairs into geocoder memory
  save_geocode_cache()              → persist a new geocode result
  count_total_listings()            → current total row count for Telegram summary
  fetch_listings_for_health_check() → candidates for URL verification
  confirm_listing_removed()         → called by health_checker on confirmed removal
  confirm_listing_active()          → called by health_checker on confirmed active

Monetary values: ALWAYS kobo (BIGINT). Never float. Never naira at the DB layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Set, Tuple

import psycopg2
import psycopg2.extras

from scraper.models import NormalisedListing
import config

log = logging.getLogger(__name__)

ActiveListings = Dict[Tuple[str, str], Optional[int]]   # {(source, ext_id): price_kobo}


class DatabaseWriter:
    def __init__(self, database_url: str):
        self.conn = psycopg2.connect(database_url)
        self.conn.autocommit = False

    def close(self):
        self.conn.close()

    # ═══════════════════════════════════════════════════════════════════════════
    # Active listings — fetched at run start for deduplication + history compare
    # ═══════════════════════════════════════════════════════════════════════════

    def fetch_active_listings(self) -> ActiveListings:
        """
        Returns a dict of all currently ACTIVE listings in the DB.
        {(source, external_id): price_kobo}
        Used by orchestrator to:
          (a) detect price changes against current run observations
          (b) detect removals (listings present in DB but absent this run)
        """
        sql = """
            SELECT source, external_id, price_kobo
            FROM raw_data.scraped_listings
            WHERE listing_status = 'ACTIVE'
        """
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return {(row[0], row[1]): row[2] for row in cur.fetchall()}

    # ═══════════════════════════════════════════════════════════════════════════
    # Main upsert — new listings inserted, existing updated
    # ═══════════════════════════════════════════════════════════════════════════

    def upsert(self,
               listings: List[NormalisedListing],
               active_listings: ActiveListings) -> Dict:
        """
        Upsert all listings from this run and emit history events.

        Deduplicates within the run before any DB work so that a listing
        appearing twice across search pages (e.g. page 1 and page 3 of the
        same portal) is counted and written exactly once. Last occurrence wins
        for field values; this is inconsequential since the fields are identical.

        Returns a stats dict:
          {
            new:                int,
            updated:            int,
            price_changes:      int,
            suspected_sold:     int,
            duplicates_dropped: int,
            per_source: {
              source: {new: int, updated: int, price_changes: int}
            }
          }
        """
        # ── Deduplicate within this run ───────────────────────────────────────
        # Build an ordered dict keyed on (source, external_id). If the same key
        # appears twice (same listing on page 1 and page 3 of the same portal),
        # the second occurrence overwrites the first. Both have identical data;
        # we just need to write it once and count it once.
        seen_keys: dict = {}
        for listing in listings:
            seen_keys[(listing.source, listing.external_id)] = listing

        duplicates_dropped = len(listings) - len(seen_keys)
        if duplicates_dropped:
            log.info(
                "[db_writer] Dropped %d within-run duplicate(s) before write "
                "(raw: %d → deduplicated: %d)",
                duplicates_dropped, len(listings), len(seen_keys),
            )

        deduped = list(seen_keys.values())

        stats: Dict = {
            "new":                0,
            "updated":            0,
            "price_changes":      0,
            "suspected_sold":     0,
            "duplicates_dropped": duplicates_dropped,
            "per_source":         {},
        }
        now            = datetime.now(timezone.utc)
        seen_this_run: Set[Tuple[str, str]] = set()
        history_events: List[Dict] = []

        # ── Process each listing ──────────────────────────────────────────────
        for batch in _chunks(deduped, config.UPSERT_BATCH_SIZE):
            with self.conn.cursor() as cur:
                for listing in batch:
                    key    = (listing.source, listing.external_id)
                    source = listing.source
                    seen_this_run.add(key)

                    if source not in stats["per_source"]:
                        stats["per_source"][source] = {
                            "new": 0, "updated": 0, "price_changes": 0,
                        }

                    if key in active_listings:
                        # ── Existing listing ──────────────────────────────────
                        self._update_existing(cur, listing, now)
                        stats["updated"] += 1
                        stats["per_source"][source]["updated"] += 1

                        old_price = active_listings[key]
                        if (listing.price_kobo is not None
                                and old_price is not None
                                and listing.price_kobo != old_price):
                            history_events.append({
                                "source":     listing.source,
                                "ext_id":     listing.external_id,
                                "event_type": "PRICE_CHANGE",
                                "old_value":  old_price,
                                "new_value":  listing.price_kobo,
                            })
                            stats["price_changes"] += 1
                            stats["per_source"][source]["price_changes"] += 1
                    else:
                        # ── New listing ────────────────────────────────────────
                        listing_id = self._insert_new(cur, listing, now)
                        stats["new"] += 1
                        stats["per_source"][source]["new"] += 1

                        if listing_id is not None:
                            history_events.append({
                                "listing_id": listing_id,
                                "event_type": "LISTED",
                                "old_value":  None,
                                "new_value":  listing.price_kobo,
                            })
                            # Register immediately so a second encounter of this
                            # key later in the run routes to _update_existing.
                            active_listings[key] = listing.price_kobo
                        else:
                            log.warning(
                                "[db_writer] _insert_new returned None for (%s, %s) "
                                "— skipping LISTED history event",
                                listing.source, listing.external_id,
                            )

            self.conn.commit()

        # ── Handle listings not seen this run ─────────────────────────────────
        # Increment missed_run_count only. REMOVED status is set exclusively
        # by the health checker after an individual URL verification confirms
        # the listing is actually gone. Marking REMOVED here based on feed
        # absence alone causes false positives because listings age off the
        # "recent" feed while still being live on the portal.
        missing = set(active_listings.keys()) - seen_this_run
        if missing:
            with self.conn.cursor() as cur:
                pairs        = list(missing)
                placeholders = ",".join(["(%s, %s)"] * len(pairs))
                flat_args    = [v for pair in pairs for v in pair]
                cur.execute(
                    f"UPDATE raw_data.scraped_listings "
                    f"SET missed_run_count = missed_run_count + 1 "
                    f"WHERE (source, external_id) IN ({placeholders}) "
                    f"AND listing_status = 'ACTIVE'",
                    flat_args,
                )
            self.conn.commit()
            log.debug("[db_writer] Incremented missed_run_count for %d listings "
                      "not seen this run", len(missing))

        # ── Write history events ───────────────────────────────────────────────
        self._insert_history_events(history_events)
        self.conn.commit()

        return stats

    # ═══════════════════════════════════════════════════════════════════════════
    # History events
    # ═══════════════════════════════════════════════════════════════════════════

    def _insert_history_events(self, events: List[Dict]) -> None:
        if not events:
            return
        sql = """
            INSERT INTO raw_data.listing_history
                (listing_id, event_type, old_value, new_value, event_date, notes)
            SELECT
                sl.id,
                %(event_type)s,
                %(old_value)s,
                %(new_value)s,
                CURRENT_DATE,
                %(notes)s
            FROM raw_data.scraped_listings sl
            WHERE sl.source = %(source)s AND sl.external_id = %(ext_id)s
        """
        direct_sql = """
            INSERT INTO raw_data.listing_history
                (listing_id, event_type, old_value, new_value, event_date, notes)
            VALUES (%(listing_id)s, %(event_type)s, %(old_value)s, %(new_value)s, CURRENT_DATE, %(notes)s)
        """
        with self.conn.cursor() as cur:
            for event in events:
                event.setdefault("notes", None)
                if "listing_id" in event:
                    cur.execute(direct_sql, event)
                else:
                    cur.execute(sql, event)

    # ═══════════════════════════════════════════════════════════════════════════
    # Run log
    # ═══════════════════════════════════════════════════════════════════════════

    def write_run_log(self, run_stats: Dict, duration_seconds: float) -> None:
        """Write one row per portal to raw_data.scrape_runs."""
        sql = """
            INSERT INTO raw_data.scrape_runs
                (source, new_listings, updated_listings, suspected_sold,
                 price_changes, status, error_message, duration_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        with self.conn.cursor() as cur:
            for source, info in run_stats.items():
                cur.execute(sql, (
                    source,
                    info.get("new",            0),
                    info.get("updated",        0),
                    info.get("suspected_sold", 0),
                    info.get("price_changes",  0),
                    info.get("status",         "FAILED"),
                    info.get("error"),
                    duration_seconds,
                ))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # Total listing count — for Telegram summary footer
    # ═══════════════════════════════════════════════════════════════════════════

    def count_total_listings(self) -> int:
        """Return current total row count across all statuses in scraped_listings."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM raw_data.scraped_listings")
            row = cur.fetchone()
            return row[0] if row else 0

    # ═══════════════════════════════════════════════════════════════════════════
    # Geocode cache
    # ═══════════════════════════════════════════════════════════════════════════

    def fetch_geocode_cache(self) -> Dict[Tuple[str, str], Tuple[float, float]]:
        """Load the persistent geocode cache into a dict for in-memory use."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT neighbourhood, city, lat, lng FROM raw_data.geocode_cache")
            return {
                (row[0].lower(), row[1].lower()): (row[2], row[3])
                for row in cur.fetchall()
            }

    def save_geocode_cache(self, neighbourhood: str, city: str,
                           lat: float, lng: float) -> None:
        """Persist a new geocode result. ON CONFLICT DO NOTHING (idempotent)."""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO raw_data.geocode_cache (neighbourhood, city, lat, lng)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (neighbourhood, city) DO NOTHING
            """, (neighbourhood, city, lat, lng))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # Health check support
    # ═══════════════════════════════════════════════════════════════════════════

    def fetch_listings_for_health_check(self) -> List[Dict]:
        """
        Returns ACTIVE listings that are due for an individual URL health check.

        Ordered by missed_run_count DESC so listings most likely to be gone
        are verified first. Ties broken by last_health_check_at ASC NULLS FIRST
        so the oldest checks are refreshed soonest.
        """
        interval = f"{config.HEALTH_CHECK_INTERVAL_DAYS} days"
        sql = """
            SELECT id, source, external_id, url, first_seen_at, price_kobo
            FROM raw_data.scraped_listings
            WHERE listing_status = 'ACTIVE'
              AND (
                  last_health_check_at IS NULL
                  OR last_health_check_at < NOW() - INTERVAL %s
              )
            ORDER BY missed_run_count DESC,
                     last_health_check_at ASC NULLS FIRST
        """
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (interval,))
            return cur.fetchall()

    def confirm_listing_removed(self, listing_id: int,
                                 first_seen_at: datetime) -> None:
        """
        Called by health_checker when an individual URL check confirms removal.

        Sets listing_status = 'REMOVED', evaluates and writes suspected_sold,
        updates last_health_check_at, and emits a REMOVED history event.

        This is the ONLY place that may set listing_status = 'REMOVED'.
        """
        now = datetime.now(timezone.utc)
        is_suspected_sold = self._evaluate_suspected_sold(listing_id, first_seen_at, now)

        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE raw_data.scraped_listings
                SET listing_status       = 'REMOVED',
                    suspected_sold       = %s,
                    last_health_check_at = %s
                WHERE id = %s
            """, (is_suspected_sold, now, listing_id))

        self._insert_history_events([{
            "listing_id": listing_id,
            "event_type": "REMOVED",
            "old_value":  None,
            "new_value":  None,
            "notes":      "confirmed removed by health checker",
        }])
        self.conn.commit()
        log.debug("[db_writer] listing %d marked REMOVED (suspected_sold=%s)",
                  listing_id, is_suspected_sold)

    def confirm_listing_active(self, listing_id: int) -> None:
        """
        Called by health_checker when an individual URL check confirms the
        listing is still live. Resets missed_run_count and stamps timestamp.
        """
        now = datetime.now(timezone.utc)
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE raw_data.scraped_listings
                SET missed_run_count     = 0,
                    last_health_check_at = %s
                WHERE id = %s
            """, (now, listing_id))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # Private helpers
    # ═══════════════════════════════════════════════════════════════════════════

    def _insert_new(self, cur, listing: NormalisedListing, now: datetime) -> int:
        """Insert a brand-new listing row. Returns the new row id."""
        cur.execute("""
            INSERT INTO raw_data.scraped_listings (
                external_id, source, url, title, description,
                price_kobo, price_parse_failed, price_type,
                property_type, bedrooms, bathrooms,
                floor_area_sqm, floor_area_source,
                raw_address, neighbourhood, neighbourhood_normalised,
                city, lat, lng, geocoded,
                agent_name, diaspora_targeted,
                listing_status, suspected_sold, missed_run_count,
                first_seen_at, last_seen_at
            ) VALUES (
                %(external_id)s, %(source)s, %(url)s, %(title)s, %(description)s,
                %(price_kobo)s, %(price_parse_failed)s, %(price_type)s,
                %(property_type)s, %(bedrooms)s, %(bathrooms)s,
                %(floor_area_sqm)s, %(floor_area_source)s,
                %(raw_address)s, %(neighbourhood)s, %(neighbourhood_normalised)s,
                %(city)s, %(lat)s, %(lng)s, %(geocoded)s,
                %(agent_name)s, %(diaspora_targeted)s,
                'ACTIVE', FALSE, 0,
                %(now)s, %(now)s
            )
            ON CONFLICT (source, external_id) DO UPDATE
                SET last_seen_at = EXCLUDED.last_seen_at
            RETURNING id
        """, {**listing.__dict__, "now": now})
        row = cur.fetchone()
        return row[0] if row else None

    def _update_existing(self, cur, listing: NormalisedListing, now: datetime) -> None:
        """Update last_seen_at and mutable fields for a known listing."""
        cur.execute("""
            UPDATE raw_data.scraped_listings SET
                last_seen_at             = %(now)s,
                price_kobo               = %(price_kobo)s,
                price_parse_failed       = %(price_parse_failed)s,
                url                      = %(url)s,
                title                    = %(title)s,
                lat                      = COALESCE(%(lat)s, lat),
                lng                      = COALESCE(%(lng)s, lng),
                geocoded                 = COALESCE(%(geocoded)s, geocoded),
                missed_run_count         = 0,
                listing_status           = 'ACTIVE'
            WHERE source = %(source)s AND external_id = %(external_id)s
        """, {**listing.__dict__, "now": now})

    def _evaluate_suspected_sold(self, listing_id: int,
                                  first_seen: datetime,
                                  now: datetime) -> bool:
        """
        Returns True if the listing meets the suspected-sold criteria:
          1. Was active for >= SUSPECTED_SOLD_MIN_DAYS days.
          2. Had at least one PRICE_CHANGE event where new < old.
        """
        if first_seen and (now - first_seen).days < config.SUSPECTED_SOLD_MIN_DAYS:
            return False

        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM raw_data.listing_history
                WHERE listing_id = %s
                  AND event_type = 'PRICE_CHANGE'
                  AND new_value < old_value
                LIMIT 1
            """, (listing_id,))
            return cur.fetchone() is not None


# ── Utility ───────────────────────────────────────────────────────────────────

def _chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]