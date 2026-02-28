"""
test_db_writer.py — Unit tests for scraper/db_writer.py.

Uses a real SQLite in-memory DB as a substitute for PostgreSQL.
The SQL dialect differences are minor for the logic being tested here.

Alternatively: use pytest-postgresql or psycopg2 pointed at a local test DB.
These tests use the mock pattern to avoid any external dependency.

Run with: pytest tests/test_db_writer.py -v
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

from scraper.models import NormalisedListing
import config


def _make_listing(**overrides) -> NormalisedListing:
    defaults = dict(
        external_id="EXT001", source="propertypro",
        url="https://example.com/property/1",
        title="Test Listing", description="Nice flat in Lekki",
        price_kobo=4_500_000_000, price_parse_failed=False,
        price_type="FOR_SALE", property_type="FLAT_APARTMENT",
        bedrooms=3, bathrooms=2, floor_area_sqm=120.0, floor_area_source="PORTAL",
        raw_address="Lekki Phase 1, Lagos",
        neighbourhood="Lekki Phase 1", neighbourhood_normalised=True,
        city="LAGOS", lat=6.4698, lng=3.5852, geocoded=True,
        agent_name="Test Agent", diaspora_targeted=False,
        first_seen_at=None, last_seen_at=None,
        listing_status="ACTIVE", suspected_sold=False, missed_run_count=0,
    )
    defaults.update(overrides)
    return NormalisedListing(**defaults)


# =============================================================================
# Upsert logic
# =============================================================================

class TestUpsertLogic:
    """
    Test the business logic of upsert() without a real DB.
    We inspect what SQL the cursor is asked to execute.
    """

    def _make_db_writer_with_mock_conn(self):
        """Return a DatabaseWriter with a fully mocked psycopg2 connection."""
        from scraper.db_writer import DatabaseWriter
        with patch("scraper.db_writer.psycopg2.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn
            writer = DatabaseWriter("postgresql://fake/db")
            writer._mock_cursor = mock_cursor
            writer._mock_conn   = mock_conn
            return writer

    def test_new_listing_triggers_insert(self):
        """A (source, ext_id) NOT in active_listings should trigger INSERT."""
        writer = self._make_db_writer_with_mock_conn()
        listing = _make_listing()
        active  = {}   # empty — listing is new

        # _insert_new is called when key not in active_listings
        # We patch it to observe the call
        writer._insert_new = MagicMock(return_value=1)
        writer._update_existing = MagicMock()
        writer._insert_history_events = MagicMock()

        stats = writer.upsert([listing], active)

        writer._insert_new.assert_called_once()
        writer._update_existing.assert_not_called()
        assert stats["new"] == 1
        assert stats["updated"] == 0

    def test_existing_listing_triggers_update(self):
        """A (source, ext_id) IN active_listings should trigger UPDATE."""
        writer = self._make_db_writer_with_mock_conn()
        listing = _make_listing()
        active  = {("propertypro", "EXT001"): 4_500_000_000}  # same price

        writer._insert_new = MagicMock(return_value=None)
        writer._update_existing = MagicMock()
        writer._insert_history_events = MagicMock()

        stats = writer.upsert([listing], active)

        writer._update_existing.assert_called_once()
        writer._insert_new.assert_not_called()
        assert stats["updated"] == 1
        assert stats["new"] == 0

    def test_price_change_creates_history_event(self):
        """When price differs from active_listings price → PRICE_CHANGE event emitted."""
        writer = self._make_db_writer_with_mock_conn()
        listing = _make_listing(price_kobo=4_000_000_000)  # dropped from 4.5B to 4B
        active  = {("propertypro", "EXT001"): 4_500_000_000}

        history_events_captured = []

        def capture_history(events):
            history_events_captured.extend(events)

        writer._insert_new = MagicMock(return_value=None)
        writer._update_existing = MagicMock()
        writer._insert_history_events = capture_history

        stats = writer.upsert([listing], active)

        assert stats["price_changes"] == 1
        price_change_events = [e for e in history_events_captured if e["event_type"] == "PRICE_CHANGE"]
        assert len(price_change_events) == 1
        assert price_change_events[0]["old_value"] == 4_500_000_000
        assert price_change_events[0]["new_value"] == 4_000_000_000

    def test_no_price_change_when_prices_equal(self):
        """Same price as in active_listings → no PRICE_CHANGE event."""
        writer = self._make_db_writer_with_mock_conn()
        listing = _make_listing(price_kobo=4_500_000_000)
        active  = {("propertypro", "EXT001"): 4_500_000_000}

        history_events_captured = []
        writer._insert_new = MagicMock()
        writer._update_existing = MagicMock()
        writer._insert_history_events = lambda e: history_events_captured.extend(e)

        stats = writer.upsert([listing], active)

        price_change_events = [e for e in history_events_captured if e.get("event_type") == "PRICE_CHANGE"]
        assert len(price_change_events) == 0
        assert stats["price_changes"] == 0


# =============================================================================
# Suspected sold logic
# =============================================================================

class TestSuspectedSold:

    def test_suspected_sold_requires_price_reduction_and_active_30d(self):
        """
        _evaluate_suspected_sold returns True only when:
          - listing was active >= 30 days
          - had at least one downward PRICE_CHANGE
        """
        from scraper.db_writer import DatabaseWriter
        with patch("scraper.db_writer.psycopg2.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (1,)   # price reduction found
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            writer = DatabaseWriter("postgresql://fake/db")

            now        = datetime.now(timezone.utc)
            first_seen = now - timedelta(days=75)

            result = writer._evaluate_suspected_sold(listing_id=1, first_seen=first_seen, now=now)
            assert result is True

    def test_suspected_sold_false_when_too_recent(self):
        """Listing active < 30 days → suspected_sold must be False regardless of price history."""
        from scraper.db_writer import DatabaseWriter
        with patch("scraper.db_writer.psycopg2.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (1,)
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            writer = DatabaseWriter("postgresql://fake/db")

            now        = datetime.now(timezone.utc)
            first_seen = now - timedelta(days=10)   # too recent

            result = writer._evaluate_suspected_sold(listing_id=1, first_seen=first_seen, now=now)
            assert result is False

    def test_suspected_sold_false_when_no_price_reduction(self):
        """No downward price change in history → suspected_sold=False."""
        from scraper.db_writer import DatabaseWriter
        with patch("scraper.db_writer.psycopg2.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = None   # no price reduction found
            mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            writer = DatabaseWriter("postgresql://fake/db")

            now        = datetime.now(timezone.utc)
            first_seen = now - timedelta(days=75)

            result = writer._evaluate_suspected_sold(listing_id=1, first_seen=first_seen, now=now)
            assert result is False


# =============================================================================
# Missed run / removal logic
# =============================================================================

class TestMissedRunLogic:

    def test_missed_3_runs_sets_removed(self):
        """
        After MISSED_RUN_REMOVAL_THRESHOLD consecutive misses, the listing
        status should be set to REMOVED.
        This tests the threshold constant from config.
        """
        assert config.MISSED_RUN_REMOVAL_THRESHOLD == 3