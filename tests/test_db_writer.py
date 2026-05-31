"""
test_db_writer.py — Tests for scraper/db_writer.py business logic.

Strategy: mock the psycopg2 connection entirely. We test the Python-level
logic — what decisions the writer makes — not the SQL it generates.
For SQL correctness, use the schema integration test (test_pipeline.py).

Run all:               pytest tests/test_db_writer.py -v
Run one class:         pytest tests/test_db_writer.py::TestUpsertRouting -v
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

from tests.conftest import make_normalised
import config


# ── Shared helper ─────────────────────────────────────────────────────────────

def _make_writer():
    """DatabaseWriter with a fully mocked psycopg2 connection."""
    from scraper.db_writer import DatabaseWriter
    with patch("scraper.db_writer.psycopg2.connect") as mock_connect:
        mock_conn   = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
        mock_conn.closed = 0          # ← _ensure_connection() checks this;
                                      #   0 means open, so no reconnect fires
        mock_connect.return_value = mock_conn
        writer = DatabaseWriter("postgresql://fake/db")
        writer.conn = mock_conn       # ← attribute is conn, not _conn
    return writer


# =============================================================================
# Upsert routing: new vs existing
# =============================================================================

class TestUpsertRouting:

    def test_new_listing_calls_insert_not_update(self):
        writer  = _make_writer()
        listing = make_normalised()
        active  = {}   # empty — listing is brand new

        writer._insert_new         = MagicMock(return_value=None)
        writer._update_existing    = MagicMock()
        writer._insert_history_events = MagicMock()

        stats = writer.upsert([listing], active)

        writer._insert_new.assert_called_once()
        writer._update_existing.assert_not_called()
        assert stats["new"] == 1
        assert stats["updated"] == 0

    def test_existing_listing_calls_update_not_insert(self):
        writer  = _make_writer()
        listing = make_normalised()
        active  = {("propertypro", "TEST001"): 4_500_000_000}

        writer._insert_new         = MagicMock()
        writer._update_existing    = MagicMock()
        writer._insert_history_events = MagicMock()

        stats = writer.upsert([listing], active)

        writer._update_existing.assert_called_once()
        writer._insert_new.assert_not_called()
        assert stats["updated"] == 1
        assert stats["new"] == 0

    def test_multiple_listings_routed_correctly(self):
        writer  = _make_writer()
        new_one = make_normalised(external_id="NEW001")
        existing = make_normalised(external_id="EX001")
        active  = {("propertypro", "EX001"): 4_500_000_000}

        inserts = []
        updates = []
        writer._insert_new         = MagicMock(side_effect=lambda cur, l, now: inserts.append(l))
        writer._update_existing    = MagicMock(side_effect=lambda cur, l, now: updates.append(l))
        writer._insert_history_events = MagicMock()

        stats = writer.upsert([new_one, existing], active)

        assert len(inserts) == 1
        assert len(updates) == 1
        assert stats["new"] == 1
        assert stats["updated"] == 1

    def test_empty_listing_list_returns_zero_stats(self):
        writer = _make_writer()
        writer._insert_new         = MagicMock()
        writer._update_existing    = MagicMock()
        writer._insert_history_events = MagicMock()

        stats = writer.upsert([], {})

        assert stats["new"] == 0
        assert stats["updated"] == 0
        assert stats["price_changes"] == 0


# =============================================================================
# Missing listings (missed_run_count updates)
# =============================================================================

class TestUpsertMissingListings:

    def test_missing_listings_are_batched_correctly(self):
        writer = _make_writer()
        
        mock_cursor = MagicMock()
        writer.conn.cursor.return_value.__enter__ = lambda s: mock_cursor

        # Mock active listings to have 2.5 times the UPSERT_BATCH_SIZE
        batch_size = config.UPSERT_BATCH_SIZE
        num_missing = int(batch_size * 2.5)
        
        active = {
            ("source", f"ext{i}"): 1000 for i in range(num_missing)
        }
        
        writer._insert_new = MagicMock()
        writer._update_existing = MagicMock()
        writer._insert_history_events = MagicMock()
        
        stats = writer.upsert([], active)
        
        # We expect cur.execute to be called 3 times with UPDATE raw_data.scraped_listings.
        update_calls = [
            c for c in mock_cursor.execute.call_args_list 
            if "UPDATE raw_data.scraped_listings" in c[0][0]
        ]
        assert len(update_calls) == 3
        
        # Verify the batch sizes of the calls
        assert len(update_calls[0][0][1]) == batch_size * 2
        assert len(update_calls[1][0][1]) == batch_size * 2
        assert len(update_calls[2][0][1]) == (num_missing - batch_size * 2) * 2


# =============================================================================
# Price change detection
# =============================================================================

class TestPriceChangeDetection:

    def test_price_drop_emits_price_change_event(self):
        writer  = _make_writer()
        listing = make_normalised(price_kobo=4_000_000_000)   # dropped from 4.5B
        active  = {("propertypro", "TEST001"): 4_500_000_000}

        captured_events = []
        writer._insert_new         = MagicMock()
        writer._update_existing    = MagicMock()
        writer._insert_history_events = lambda evts: captured_events.extend(evts)

        stats = writer.upsert([listing], active)

        price_changes = [e for e in captured_events if e.get("event_type") == "PRICE_CHANGE"]
        assert len(price_changes) == 1
        assert price_changes[0]["old_value"] == 4_500_000_000
        assert price_changes[0]["new_value"] == 4_000_000_000
        assert stats["price_changes"] == 1

    def test_price_increase_also_emits_price_change_event(self):
        writer  = _make_writer()
        listing = make_normalised(price_kobo=5_000_000_000)   # increased from 4.5B
        active  = {("propertypro", "TEST001"): 4_500_000_000}

        captured_events = []
        writer._insert_new         = MagicMock()
        writer._update_existing    = MagicMock()
        writer._insert_history_events = lambda evts: captured_events.extend(evts)

        stats = writer.upsert([listing], active)

        price_changes = [e for e in captured_events if e.get("event_type") == "PRICE_CHANGE"]
        assert len(price_changes) == 1
        assert stats["price_changes"] == 1

    def test_same_price_no_price_change_event(self):
        writer  = _make_writer()
        listing = make_normalised(price_kobo=4_500_000_000)
        active  = {("propertypro", "TEST001"): 4_500_000_000}

        captured_events = []
        writer._insert_new         = MagicMock()
        writer._update_existing    = MagicMock()
        writer._insert_history_events = lambda evts: captured_events.extend(evts)

        stats = writer.upsert([listing], active)

        price_changes = [e for e in captured_events if e.get("event_type") == "PRICE_CHANGE"]
        assert len(price_changes) == 0
        assert stats["price_changes"] == 0

    def test_null_price_no_price_change_event(self):
        """Listings with unparseable price should not emit a PRICE_CHANGE event."""
        writer  = _make_writer()
        listing = make_normalised(price_kobo=None, price_parse_failed=True)
        active  = {("propertypro", "TEST001"): 4_500_000_000}

        captured_events = []
        writer._insert_new         = MagicMock()
        writer._update_existing    = MagicMock()
        writer._insert_history_events = lambda evts: captured_events.extend(evts)

        writer.upsert([listing], active)

        price_changes = [e for e in captured_events if e.get("event_type") == "PRICE_CHANGE"]
        assert len(price_changes) == 0


# =============================================================================
# Suspected sold evaluation
# =============================================================================

class TestSuspectedSold:
    """
    _evaluate_suspected_sold(listing_id, first_seen, now) → bool

    Rules:
      - Must be active >= SUSPECTED_SOLD_MIN_DAYS (30) days
      - Must have at least one downward PRICE_CHANGE in history
    """

    def _writer_with_price_history(self, has_reduction: bool):
        """Build a writer whose DB cursor reports presence/absence of a price reduction."""
        from scraper.db_writer import DatabaseWriter
        with patch("scraper.db_writer.psycopg2.connect") as mock_connect:
            mock_conn   = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (1,) if has_reduction else None
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
            mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
            mock_conn.closed = 0      # ← same fix as _make_writer
            mock_connect.return_value = mock_conn
            writer = DatabaseWriter("postgresql://fake/db")
            writer.conn = mock_conn   # ← conn, not _conn
        return writer

    def test_returns_true_when_old_enough_and_price_reduced(self):
        writer     = self._writer_with_price_history(has_reduction=True)
        now        = datetime.now(timezone.utc)
        first_seen = now - timedelta(days=45)
        assert writer._evaluate_suspected_sold(listing_id=1, first_seen=first_seen, now=now) is True

    def test_returns_false_when_too_recent(self):
        writer     = self._writer_with_price_history(has_reduction=True)
        now        = datetime.now(timezone.utc)
        first_seen = now - timedelta(days=10)   # only 10 days — below threshold
        assert writer._evaluate_suspected_sold(listing_id=1, first_seen=first_seen, now=now) is False

    def test_returns_false_when_no_price_reduction(self):
        writer     = self._writer_with_price_history(has_reduction=False)
        now        = datetime.now(timezone.utc)
        first_seen = now - timedelta(days=60)   # old enough, but no price drop
        assert writer._evaluate_suspected_sold(listing_id=1, first_seen=first_seen, now=now) is False

    def test_exactly_at_threshold_qualifies(self):
        writer     = self._writer_with_price_history(has_reduction=True)
        now        = datetime.now(timezone.utc)
        first_seen = now - timedelta(days=config.SUSPECTED_SOLD_MIN_DAYS)
        assert writer._evaluate_suspected_sold(listing_id=1, first_seen=first_seen, now=now) is True


# =============================================================================
# Missed run / removal threshold
# =============================================================================

class TestMissedRunConfig:
    """
    These tests guard the config constants that control removal behaviour.
    If someone accidentally changes MISSED_RUN_REMOVAL_THRESHOLD, a test fails
    immediately rather than silently starting to remove listings too early/late.
    """

    def test_removal_threshold_is_3(self):
        assert config.MISSED_RUN_REMOVAL_THRESHOLD == 3

    def test_suspected_sold_min_days_is_30(self):
        assert config.SUSPECTED_SOLD_MIN_DAYS == 30

    def test_pagination_stop_after_known_is_10(self):
        assert config.PAGINATION_STOP_AFTER_KNOWN == 10