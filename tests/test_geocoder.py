"""
test_geocoder.py — Tests for scraper/geocoder.py.

All tests are fully offline — no real HTTP calls, no database.
Nominatim is mocked at the requests.Session level.
time.sleep is patched to avoid 1-second delays in tests.

Run all:               pytest tests/test_geocoder.py -v
Run one test:          pytest tests/test_geocoder.py::TestGeocodeCache::test_cache_miss_calls_api -v
"""

import pytest
from unittest.mock import MagicMock, patch

from tests.conftest import make_normalised, mock_db, mock_nominatim
from scraper.geocoder import Geocoder


def _geo(preloaded=None):
    """Convenience: build a Geocoder with mocked DB and no initial cache."""
    return Geocoder(mock_db(geocode_cache=preloaded or {}))


# =============================================================================
# Cache initialisation
# =============================================================================

class TestCacheInit:

    def test_preloads_db_cache_on_init(self):
        db = mock_db(geocode_cache={("lekki phase 1", "lagos"): (6.47, 3.58)})
        geo = Geocoder(db)
        assert ("lekki phase 1", "lagos") in geo.memory_cache

    def test_empty_cache_when_db_returns_nothing(self):
        geo = _geo()
        assert geo.memory_cache == {}

    def test_db_preload_failure_does_not_crash(self):
        db = mock_db()
        db.fetch_geocode_cache.side_effect = Exception("DB unavailable")
        geo = Geocoder(db)   # must not raise
        assert geo.memory_cache == {}


# =============================================================================
# Memory cache hits
# =============================================================================

class TestMemoryCacheHits:

    def test_db_preload_hit_skips_api(self):
        """Neighbourhood loaded from DB at init → no API call at all."""
        preloaded = {("lekki phase 1", "lagos"): (6.4698, 3.5852)}
        geo = _geo(preloaded=preloaded)
        geo.session = mock_nominatim()

        results = geo.enrich([make_normalised(neighbourhood="Lekki Phase 1", city="LAGOS")])

        geo.session.get.assert_not_called()
        assert results[0].lat == pytest.approx(6.4698, abs=0.001)
        assert results[0].geocoded is True

    def test_second_call_same_neighbourhood_uses_memory(self):
        """After first API call warms cache, second listing does not call API again."""
        geo = _geo()
        geo.session = mock_nominatim(lat=6.47, lng=3.58)

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([
                make_normalised(neighbourhood="Lekki Phase 1", city="LAGOS"),
                make_normalised(neighbourhood="Lekki Phase 1", city="LAGOS"),
            ])

        assert geo.session.get.call_count == 1   # only one real HTTP call
        assert all(r.geocoded for r in results)

    def test_cache_key_is_case_insensitive(self):
        preloaded = {("lekki phase 1", "lagos"): (6.47, 3.58)}
        geo = _geo(preloaded=preloaded)
        geo.session = mock_nominatim()

        # Pass in different capitalisation — should still hit cache
        results = geo.enrich([make_normalised(neighbourhood="LEKKI PHASE 1", city="Lagos")])

        geo.session.get.assert_not_called()
        assert results[0].geocoded is True


# =============================================================================
# API calls (cache miss)
# =============================================================================

class TestApiCalls:

    def test_cache_miss_calls_nominatim(self):
        geo = _geo()
        geo.session = mock_nominatim(lat=9.0574, lng=7.4898)

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([make_normalised(neighbourhood="Maitama", city="ABUJA")])

        geo.session.get.assert_called_once()
        assert results[0].lat == pytest.approx(9.0574, abs=0.001)
        assert results[0].lng == pytest.approx(7.4898, abs=0.001)
        assert results[0].geocoded is True

    def test_cache_miss_saves_to_db(self):
        db = mock_db()
        geo = Geocoder(db)
        geo.session = mock_nominatim(lat=9.0574, lng=7.4898)

        with patch("scraper.geocoder.time.sleep"):
            geo.enrich([make_normalised(neighbourhood="Maitama", city="ABUJA")])

        db.save_geocode_cache.assert_called_once_with("Maitama", "ABUJA", pytest.approx(9.0574, abs=0.001), pytest.approx(7.4898, abs=0.001))

    def test_cache_miss_saves_to_memory(self):
        geo = _geo()
        geo.session = mock_nominatim(lat=9.0574, lng=7.4898)

        with patch("scraper.geocoder.time.sleep"):
            geo.enrich([make_normalised(neighbourhood="Maitama", city="ABUJA")])

        assert ("maitama", "abuja") in geo.memory_cache

    def test_nominatim_query_includes_nigeria(self):
        """The query sent to Nominatim must include 'Nigeria' to avoid false matches."""
        geo = _geo()
        geo.session = mock_nominatim()

        with patch("scraper.geocoder.time.sleep"):
            geo.enrich([make_normalised(neighbourhood="Lekki Phase 1", city="LAGOS")])

        call_args = geo.session.get.call_args
        params = call_args[1].get("params") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["params"]
        assert "Nigeria" in params.get("q", "")

    def test_countrycode_constrained_to_ng(self):
        geo = _geo()
        geo.session = mock_nominatim()

        with patch("scraper.geocoder.time.sleep"):
            geo.enrich([make_normalised(neighbourhood="Lekki Phase 1", city="LAGOS")])

        call_args = geo.session.get.call_args
        params = call_args[1].get("params", {})
        assert params.get("countrycodes") == "ng"


# =============================================================================
# Error handling
# =============================================================================

class TestErrorHandling:

    def test_empty_nominatim_response_returns_not_geocoded(self):
        geo = _geo()
        resp = MagicMock()
        resp.json.return_value    = []
        resp.raise_for_status.return_value = None
        geo.session = MagicMock()
        geo.session.get.return_value = resp

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([make_normalised(neighbourhood="Ghost Town", city="UNKNOWN")])

        assert results[0].geocoded is False
        assert results[0].lat is None
        assert results[0].lng is None

    def test_network_exception_handled_gracefully(self):
        geo = _geo()
        geo.session = MagicMock()
        geo.session.get.side_effect = Exception("Connection refused")

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([make_normalised(neighbourhood="Lekki Phase 1", city="LAGOS")])

        assert results[0].geocoded is False

    def test_db_save_failure_does_not_crash(self):
        db = mock_db()
        db.save_geocode_cache.side_effect = Exception("DB write failed")
        geo = Geocoder(db)
        geo.session = mock_nominatim()

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([make_normalised(neighbourhood="Maitama", city="ABUJA")])

        # Result should still be geocoded from the API response
        assert results[0].geocoded is True

    def test_listing_without_neighbourhood_not_geocoded(self):
        geo = _geo()
        geo.session = mock_nominatim()

        results = geo.enrich([make_normalised(neighbourhood=None)])

        geo.session.get.assert_not_called()
        assert results[0].geocoded is False

    def test_listing_with_empty_neighbourhood_not_geocoded(self):
        geo = _geo()
        geo.session = mock_nominatim()

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([make_normalised(neighbourhood="")])

        geo.session.get.assert_not_called()
        assert results[0].geocoded is False


# =============================================================================
# Batch behaviour
# =============================================================================

class TestBatchEnrich:

    def test_mixed_batch_geocodes_only_new(self):
        """Batch with one cached + one new → only one API call."""
        preloaded = {("lekki phase 1", "lagos"): (6.47, 3.58)}
        geo = _geo(preloaded=preloaded)
        geo.session = mock_nominatim(lat=9.06, lng=7.49)

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([
                make_normalised(neighbourhood="Lekki Phase 1", city="LAGOS"),   # cache hit
                make_normalised(neighbourhood="Maitama", city="ABUJA"),          # cache miss
            ])

        assert geo.session.get.call_count == 1
        assert results[0].geocoded is True
        assert results[1].geocoded is True

    def test_returns_same_count_as_input(self):
        geo = _geo()
        geo.session = mock_nominatim()

        with patch("scraper.geocoder.time.sleep"):
            listings = [make_normalised(neighbourhood=f"Area {i}", city="LAGOS") for i in range(5)]
            results  = geo.enrich(listings)

        assert len(results) == 5