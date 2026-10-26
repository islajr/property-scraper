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
from datetime import datetime, timezone, date, timedelta
from typing import Dict, List, Optional, Set, Tuple

import psycopg2
import psycopg2.extras

from scraper.models import NormalisedListing
import config
from scraper.pricing import QUOTE_FIELDS, PERIOD_FIELDS, quote_dict, classify_change, comparable

log = logging.getLogger(__name__)

ActiveListings = Dict[Tuple[str, str], Optional[int]]   # {(source, ext_id): price_kobo}


class DatabaseWriter:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.conn = psycopg2.connect(database_url)
        self.conn.autocommit = False
    
    def _connect(self):
        conn = psycopg2.connect(self.database_url)
        conn.autocommit = False
        return conn

    def _ensure_connection(self):
        """ Reconnect if the connection has gone stale """
        try:
            # closed == 0 means open; a simple query confirms if server is reachable
            if self.conn.closed != 0:
                raise psycopg2.OperationalError("connection closed")
            with self.conn.cursor() as curr:
                curr.execute("SELECT 1")
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            log.warning("[db_writer] Connection lost — reconnecting...")
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = self._connect()

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
        
        # Ensure connection and reconnect if needed
        self._ensure_connection()
        
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return {(row[0], row[1]): row[2] for row in cur.fetchall()}

    # ═══════════════════════════════════════════════════════════════════════════
    # Main upsert — new listings inserted, existing updated
    # ═══════════════════════════════════════════════════════════════════════════

    def upsert(self, listings, active_listings, scraped_sources=None):
        try:
            return self._upsert(listings, active_listings, scraped_sources)
        except Exception:
            self.conn.rollback()
            raise

    def _upsert(self,
               listings: List[NormalisedListing],
               active_listings: ActiveListings,
               scraped_sources: Optional[Set[str]] = None) -> Dict:
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
        
        # Ensure connection and reconnect if needed
        self._ensure_connection()
        
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
            "rental_periods": {status: sum(1 for item in deduped
                if item.price_type in ('FOR_RENT','FOR_SHORT_LET') and item.price_period_status == status)
                for status in ('KNOWN','UNKNOWN','CONFLICT','UNSUPPORTED')},
        }
        now            = datetime.now(timezone.utc)
        seen_this_run: Set[Tuple[str, str]] = set()

        # ── Process each listing ──────────────────────────────────────────────
        for batch in _chunks(deduped, config.UPSERT_BATCH_SIZE):
            
            batch_history_events: List[Dict] = []
            
            self._ensure_connection()
            
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
                        event = self._update_existing(cur, listing, now)
                        stats["updated"] += 1
                        stats["per_source"][source]["updated"] += 1

                        if isinstance(event, dict):
                            batch_history_events.append(event)
                            if event['event_type'] == 'PRICE_CHANGE':
                                stats['price_changes'] += 1
                                stats['per_source'][source]['price_changes'] += 1
                    else:
                        # ── New listing ────────────────────────────────────────
                        listing_id = self._insert_new(cur, listing, now)
                        stats["new"] += 1
                        stats["per_source"][source]["new"] += 1

                        if listing_id is not None:
                            batch_history_events.append({
                                "listing_id": listing_id,
                                "event_type": "LISTED",
                                "old_value":  None,
                                "new_value":  listing.price_kobo,
                                "new_pricing": quote_dict(listing),
                            })
                            # Register immediately so a second encounter of this
                            # key later in the run routes to _update_existing.
                            active_listings[key] = listing.price_kobo
                        else:
                            # A removed/concurrently discovered listing already exists.
                            event = self._update_existing(cur, listing, now)
                            if isinstance(event, dict):
                                batch_history_events.append(event)
                            stats['new'] -= 1
                            stats['per_source'][source]['new'] -= 1
                            stats['updated'] += 1
                            stats['per_source'][source]['updated'] += 1
                            if isinstance(event, dict) and event['event_type'] == 'PRICE_CHANGE':
                                stats['price_changes'] += 1
                                stats['per_source'][source]['price_changes'] += 1

            # ── Write history events ───────────────────────────────────────────────
            # History events written inside the samae transaction as the batch
            self._insert_history_events(batch_history_events)
            self.conn.commit()

        # ── Handle listings not seen this run ─────────────────────────────────
        # Increment missed_run_count only. REMOVED status is set exclusively
        # by the health checker after an individual URL verification confirms
        # the listing is actually gone. Marking REMOVED here based on feed
        # absence alone causes false positives because listings age off the
        # "recent" feed while still being live on the portal.
        missing = set(active_listings.keys()) - seen_this_run
        if scraped_sources is not None:
            missing = {k for k in missing if k[0] in scraped_sources}
        if missing:
            with self.conn.cursor() as cur:
                pairs = list(missing)
                # Chunk to avoid Postgres stack depth limit exceeded error with massive IN clauses
                for chunk in _chunks(pairs, config.UPSERT_BATCH_SIZE):
                    placeholders = ",".join(["(%s, %s)"] * len(chunk))
                    flat_args    = [v for pair in chunk for v in pair]
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

        return stats

    # ═══════════════════════════════════════════════════════════════════════════
    # History events
    # ═══════════════════════════════════════════════════════════════════════════

    def _insert_history_events(self, events: List[Dict]) -> None:
        if not events:
            return
        sql = """
            INSERT INTO raw_data.listing_history
                (listing_id, event_type, old_value, new_value, event_date, notes, old_pricing, new_pricing, price_comparable)
            SELECT
                sl.id,
                %(event_type)s,
                %(old_value)s,
                %(new_value)s,
                CURRENT_DATE,
                %(notes)s, %(old_pricing)s, %(new_pricing)s, %(price_comparable)s
            FROM raw_data.scraped_listings sl
            WHERE sl.source = %(source)s AND sl.external_id = %(ext_id)s
        """
        direct_sql = """
            INSERT INTO raw_data.listing_history
                (listing_id, event_type, old_value, new_value, event_date, notes, old_pricing, new_pricing, price_comparable)
            VALUES (%(listing_id)s, %(event_type)s, %(old_value)s, %(new_value)s, CURRENT_DATE, %(notes)s, %(old_pricing)s, %(new_pricing)s, %(price_comparable)s)
        """
        with self.conn.cursor() as cur:
            for event in events:
                event = dict(event)
                event.setdefault("notes", None)
                for field in ('old_pricing', 'new_pricing'):
                    value = event.get(field)
                    event[field] = psycopg2.extras.Json(value) if value is not None else None
                event.setdefault('price_comparable', False)
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

    def fetch_last_successful_run(self, source: str) -> Optional[datetime]:
        """Fetch the timestamp of the last successful run for a given source."""
        sql = """
            SELECT run_at
            FROM raw_data.scrape_runs
            WHERE source = %s AND status = 'SUCCESS'
            ORDER BY run_at DESC
            LIMIT 1
        """
        self._ensure_connection()
        with self.conn.cursor() as cur:
            cur.execute(sql, (source,))
            row = cur.fetchone()
            return row[0] if row else None


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

    def fetch_listings_for_health_check(self, force_all: bool = False) -> List[Dict]:
        """
        Returns ACTIVE listings that are due for an individual URL health check.

        If force_all is True, returns all ACTIVE listings bypassing cooldown and limits.
        Otherwise, uses Adaptive Cooldown based on listing age:
          - < 14 days old: Checked every 2 days (1.9 with buffer)
          - 14-60 days old: Checked every 7 days (6.8 with buffer)
          - > 60 days old: Checked every 14 days (13.8 with buffer)

        Applies HEALTH_CHECK_LIMIT to guarantee a fixed maximum runtime.
        """
        if force_all:
            sql = """
                SELECT id, source, external_id, url, first_seen_at, price_kobo
                FROM raw_data.scraped_listings
                WHERE listing_status = 'ACTIVE'
                ORDER BY missed_run_count DESC,
                         last_health_check_at ASC NULLS FIRST
            """
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                return cur.fetchall()
        else:
            sql = """
                SELECT id, source, external_id, url, first_seen_at, price_kobo
                FROM raw_data.scraped_listings
                WHERE listing_status = 'ACTIVE'
                  AND missed_run_count > 0
                  AND (
                      next_health_check_at IS NULL
                      OR next_health_check_at < NOW()
                  )
                ORDER BY 
                    CASE 
                        WHEN next_health_check_at IS NULL THEN 1.0
                        ELSE EXTRACT(EPOCH FROM (NOW() - last_health_check_at)) / 
                             EXTRACT(EPOCH FROM (
                                 CASE
                                     WHEN first_seen_at >= NOW() - INTERVAL '14 days' THEN INTERVAL '1.9 days'
                                     WHEN first_seen_at >= NOW() - INTERVAL '60 days' THEN INTERVAL '6.8 days'
                                     ELSE INTERVAL '13.8 days'
                                 END
                             ))
                    END DESC,
                    last_health_check_at ASC NULLS FIRST
                LIMIT %s
            """
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (config.HEALTH_CHECK_LIMIT,))
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
            cur.execute(
                "SELECT price_kobo FROM raw_data.scraped_listings WHERE id = %s",
                (listing_id,)
            )
            row = cur.fetchone()
            final_price = row[0] if row else None
            cur.execute("""
                UPDATE raw_data.scraped_listings
                SET listing_status       = 'REMOVED',
                    suspected_sold       = %s,
                    last_health_check_at = %s,
                    next_health_check_at = NULL
                WHERE id = %s
            """, (is_suspected_sold, now, listing_id))


        self._insert_history_events([{
            "listing_id": listing_id,
            "event_type": "REMOVED",
            "old_value":  final_price,
            "new_value":  None,
            "notes":      "confirmed removed by health checker",
        }])
        self.conn.commit()
        log.debug("[db_writer] listing %d marked REMOVED (suspected_sold=%s)",
                  listing_id, is_suspected_sold)

    def confirm_listing_active(self, listing_id: int, first_seen_at: datetime,
                               observed_price_kobo: Optional[int] = None,
                               observed_quote: Optional[NormalisedListing] = None) -> bool:
        now = datetime.now(timezone.utc)
        age_days = (now - (first_seen_at or now)).days
        interval = timedelta(days=1.9 if age_days < 14 else 6.8 if age_days < 60 else 13.8)
        try:
            with self.conn.cursor() as cur:
                old = self._load_pricing(cur, listing_id=listing_id)
                event = None
                if old is not None:
                    if observed_quote is not None:
                        new = quote_dict(observed_quote)
                    elif observed_price_kobo is not None:
                        # Legacy callers provide no unit evidence; do not attach the old unit.
                        new = {**quote_dict(old), 'price_kobo': observed_price_kobo,
                               'price_period': None, 'price_period_count': None,
                               'price_period_status': 'UNKNOWN', 'price_currency': None,
                               'price_basis': 'UNKNOWN', 'price_period_source': 'LEGACY_UNKNOWN',
                               'raw_price_text': None, 'price_period_evidence': None}
                    else:
                        new = None
                    if new is not None:
                        event = self._persist_pricing(cur, old, new, now)
                cur.execute("""UPDATE raw_data.scraped_listings
                    SET missed_run_count=0, last_health_check_at=%s, next_health_check_at=%s
                    WHERE id=%s""", (now, now + interval, listing_id))
            if event: self._insert_history_events([event])
            self.conn.commit()
            return bool(event and event['event_type'] == 'PRICE_CHANGE')
        except Exception:
            self.conn.rollback()
            raise

    def _load_pricing(self, cur, source=None, external_id=None, listing_id=None):
        if listing_id is not None:
            cur.execute('SELECT row_to_json(sl) FROM raw_data.scraped_listings sl WHERE id=%s FOR UPDATE', (listing_id,))
        else:
            cur.execute('SELECT row_to_json(sl) FROM raw_data.scraped_listings sl WHERE source=%s AND external_id=%s FOR UPDATE', (source, external_id))
        row = cur.fetchone()
        return row[0] if row and isinstance(row[0], dict) else None

    def _persist_pricing(self, cur, old, new, now):
        before = quote_dict(old)
        if new.get('price_kobo') is None:
            # Keep a valid stored quote intact, but retain the rejected observation for review.
            return dict(listing_id=old['id'], event_type='PRICING_OBSERVATION_REJECTED',
                        old_value=before['price_kobo'], new_value=None,
                        old_pricing=before, new_pricing=new,
                        notes='Quote could not be parsed as a positive NGN amount; previous quote retained')
        event_type = classify_change(before, new)
        fields = (*QUOTE_FIELDS, 'price_parse_failed', 'pricing_observed_at')
        values = {**new, 'price_parse_failed': False, 'pricing_observed_at': now, 'id': old['id']}
        cur.execute('UPDATE raw_data.scraped_listings SET ' +
                    ', '.join(f'{k}=%({k})s' for k in fields) + ' WHERE id=%(id)s', values)
        if event_type:
            return dict(listing_id=old['id'], event_type=event_type,
                        old_value=before['price_kobo'], new_value=new['price_kobo'],
                        old_pricing=before, new_pricing=new,
                        price_comparable=comparable(before,new))
        return None

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
                first_seen_at, last_seen_at,
                price_period, price_period_count, price_period_status, price_period_source, raw_price_text, price_period_evidence, price_currency, price_basis, pricing_observed_at
            ) VALUES (
                %(external_id)s, %(source)s, %(url)s, %(title)s, %(description)s,
                %(price_kobo)s, %(price_parse_failed)s, %(price_type)s,
                %(property_type)s, %(bedrooms)s, %(bathrooms)s,
                %(floor_area_sqm)s, %(floor_area_source)s,
                %(raw_address)s, %(neighbourhood)s, %(neighbourhood_normalised)s,
                %(city)s, %(lat)s, %(lng)s, %(geocoded)s,
                %(agent_name)s, %(diaspora_targeted)s,
                'ACTIVE', FALSE, 0,
                %(now)s, %(now)s,
                %(price_period)s, %(price_period_count)s, %(price_period_status)s, %(price_period_source)s, %(raw_price_text)s, %(price_period_evidence)s, %(price_currency)s, %(price_basis)s, %(now)s
            )
            ON CONFLICT (source, external_id) DO NOTHING
            RETURNING id
        """, {**listing.__dict__, "now": now})
        row = cur.fetchone()
        return row[0] if row else None

    def _update_existing(self, cur, listing: NormalisedListing, now: datetime):
        old = self._load_pricing(cur, listing.source, listing.external_id)
        if old is None: return None
        event = self._persist_pricing(cur, old, quote_dict(listing), now)
        cur.execute("""UPDATE raw_data.scraped_listings SET
            last_seen_at=%(now)s, url=%(url)s, title=%(title)s,
            lat=COALESCE(%(lat)s,lat), lng=COALESCE(%(lng)s,lng),
            geocoded=(geocoded OR %(geocoded)s), missed_run_count=0, listing_status='ACTIVE'
            WHERE source=%(source)s AND external_id=%(external_id)s""",
            {**listing.__dict__, 'now':now})
        if old.get('listing_status') == 'REMOVED':
            self._insert_history_events([dict(listing_id=old['id'],event_type='RELISTED',
                old_value=old['price_kobo'],new_value=listing.price_kobo,
                old_pricing=quote_dict(old),new_pricing=quote_dict(listing))])
        return event

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
                  AND price_comparable = TRUE
                  AND new_value < old_value
                LIMIT 1
            """, (listing_id,))
            return cur.fetchone() is not None


# ── Utility ───────────────────────────────────────────────────────────────────

def _chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]