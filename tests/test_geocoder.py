"""
test_geocoder.py — Unit tests for scraper/geocoder.py (Nominatim version).

Uses mock objects — no real network calls, no database.
Run with: pytest tests/test_geocoder.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from scraper.geocoder import Geocoder
from scraper.models import NormalisedListing


def _make_listing(neighbourhood="Lekki Phase 1", city="LAGOS") -> NormalisedListing:
    return NormalisedListing(
        external_id="12345", source="propertypro", url="https://example.com",
        title="Test", description=None,
        price_kobo=4_500_000_000, price_parse_failed=False, price_type="FOR_SALE",
        property_type="FLAT_APARTMENT", bedrooms=3, bathrooms=2,
        floor_area_sqm=120.0, floor_area_source="PORTAL",
        raw_address="Lekki Phase 1, Lagos",
        neighbourhood=neighbourhood, neighbourhood_normalised=True,
        city=city, lat=None, lng=None, geocoded=False,
        agent_name="Test Agent", diaspora_targeted=False,
    )


def _mock_db(preloaded=None):
    db = MagicMock()
    db.fetch_geocode_cache.return_value = preloaded or {}
    db.save_geocode_cache.return_value  = None
    return db


def _mock_nominatim_response(lat=6.4698, lng=3.5852):
    """Return a mock requests.Session that yields a Nominatim-shaped JSON response."""
    resp = MagicMock()
    resp.json.return_value = [{"lat": str(lat), "lon": str(lng)}]
    resp.raise_for_status.return_value = None
    session = MagicMock()
    session.get.return_value = resp
    return session


class TestGeocodeCache:

    def test_preloads_db_cache_on_init(self):
        db  = _mock_db(preloaded={("lekki phase 1", "lagos"): (6.47, 3.58)})
        geo = Geocoder(db)
        assert ("lekki phase 1", "lagos") in geo.memory_cache

    def test_memory_cache_hit_skips_api(self):
        """Second call for same neighbourhood must NOT hit the API."""
        db  = _mock_db()
        geo = Geocoder(db)
        geo.session = _mock_nominatim_response()

        # Two listings, same neighbourhood
        results = geo.enrich([_make_listing(), _make_listing()])

        assert geo.session.get.call_count == 1   # only one real call
        assert all(r.geocoded for r in results)

    def test_db_cache_hit_skips_api(self):
        """Neighbourhood in DB pre-load → no API call."""
        preloaded = {("lekki phase 1", "lagos"): (6.4698, 3.5852)}
        db  = _mock_db(preloaded=preloaded)
        geo = Geocoder(db)
        geo.session = _mock_nominatim_response()

        results = geo.enrich([_make_listing()])

        geo.session.get.assert_not_called()
        assert results[0].lat == pytest.approx(6.4698, abs=0.001)
        assert results[0].geocoded is True

    def test_cache_miss_calls_api_and_saves(self):
        """Cache miss → Nominatim called + result persisted to DB."""
        db  = _mock_db()
        geo = Geocoder(db)
        geo.session = _mock_nominatim_response(lat=9.0574, lng=7.4898)

        with patch("scraper.geocoder.time.sleep"):  # don't actually wait 1s in tests
            results = geo.enrich([_make_listing("Maitama", "ABUJA")])

        geo.session.get.assert_called_once()
        db.save_geocode_cache.assert_called_once()
        assert results[0].geocoded is True

    def test_empty_api_response_returns_none(self):
        db  = _mock_db()
        geo = Geocoder(db)
        resp = MagicMock()
        resp.json.return_value = []
        resp.raise_for_status.return_value = None
        geo.session.get.return_value = resp

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([_make_listing("Unknown Estate", "UNKNOWN")])

        assert results[0].geocoded is False
        assert results[0].lat is None

    def test_api_exception_handled_gracefully(self):
        db  = _mock_db()
        geo = Geocoder(db)
        geo.session.get.side_effect = Exception("Connection error")

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([_make_listing()])

        assert results[0].geocoded is False

    def test_listing_without_neighbourhood_skipped(self):
        db  = _mock_db()
        geo = Geocoder(db)
        geo.session = _mock_nominatim_response()

        results = geo.enrich([_make_listing(neighbourhood=None)])

        geo.session.get.assert_not_called()
        assert results[0].geocoded is False