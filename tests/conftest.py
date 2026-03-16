"""
conftest.py — Shared fixtures and helpers for all test modules.

Provides:
  - HTML fixture loading (always offline — reads from tests/fixtures/)
  - RawListing and NormalisedListing factory functions
  - Mocked database and Nominatim session helpers

Run the full suite:   pytest tests/ -v
Run one module:       pytest tests/test_normaliser.py -v
Run one class:        pytest tests/test_parsers.py::TestPropertyProParser -v
Run one test:         pytest tests/test_parsers.py::TestPropertyProParser::test_price -v
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from scraper.models import RawListing, NormalisedListing

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── HTML fixture loader ────────────────────────────────────────────────────────

def load_fixture(filename: str) -> BeautifulSoup:
    """
    Load a saved portal HTML page. Always offline — never fetches live.
    Fixtures live in tests/fixtures/ and are committed to the repo.
    To refresh: open the live portal page, save source (UTF-8), replace the file.
    """
    path = FIXTURES_DIR / filename
    if not path.exists():
        pytest.fail(
            f"Fixture file missing: {path}\n"
            f"Run: python3 diagnose.py  to regenerate all fixtures"
        )
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


# ── RawListing factory ─────────────────────────────────────────────────────────

def make_raw(**overrides) -> RawListing:
    """Minimal valid RawListing with sensible defaults. Override as needed."""
    defaults = dict(
        external_id       = "TEST001",
        source            = "propertypro",
        url               = "https://propertypro.ng/property/test-listing-TEST001",
        title             = "3 Bedroom Flat for Sale",
        raw_price         = "₦45,000,000",
        raw_price_type    = "FOR_SALE",
        raw_bedrooms      = "3 Bedrooms",
        raw_bathrooms     = "2 Bathrooms",
        raw_address       = "Lekki Phase 1, Lekki, Lagos",
        raw_floor_area    = "150 sqm",
        description       = "Spacious 3-bed flat in a well-secured estate.",
        property_type_raw = "Flat / Apartment",
        agent_name        = "Test Realty Ltd",
    )
    defaults.update(overrides)
    return RawListing(**defaults)


# ── NormalisedListing factory ──────────────────────────────────────────────────

def make_normalised(**overrides) -> NormalisedListing:
    """Minimal valid NormalisedListing. Override as needed."""
    defaults = dict(
        external_id              = "TEST001",
        source                   = "propertypro",
        url                      = "https://propertypro.ng/property/test-TEST001",
        title                    = "3 Bedroom Flat for Sale",
        description              = "Spacious flat in Lekki.",
        price_kobo               = 4_500_000_000,
        price_parse_failed       = False,
        price_type               = "FOR_SALE",
        property_type            = "FLAT_APARTMENT",
        bedrooms                 = 3,
        bathrooms                = 2,
        floor_area_sqm           = 150.0,
        floor_area_source        = "PORTAL",
        raw_address              = "Lekki Phase 1, Lekki, Lagos",
        neighbourhood            = "Lekki Phase 1",
        neighbourhood_normalised = True,
        city                     = "LAGOS",
        lat                      = None,
        lng                      = None,
        geocoded                 = False,
        agent_name               = "Test Realty Ltd",
        diaspora_targeted        = False,
    )
    defaults.update(overrides)
    return NormalisedListing(**defaults)


# ── Mock database ──────────────────────────────────────────────────────────────

def mock_db(geocode_cache=None) -> MagicMock:
    """Return a DatabaseWriter mock with sensible defaults."""
    db = MagicMock()
    db.fetch_geocode_cache.return_value = geocode_cache or {}
    db.save_geocode_cache.return_value  = None
    db.fetch_active_listings.return_value = {}
    return db


# ── Mock Nominatim session ─────────────────────────────────────────────────────

def mock_nominatim(lat: float = 6.4698, lng: float = 3.5852) -> MagicMock:
    """Return a requests.Session mock that returns a Nominatim-shaped response."""
    resp = MagicMock()
    resp.json.return_value    = [{"lat": str(lat), "lon": str(lng)}]
    resp.raise_for_status.return_value = None
    session = MagicMock()
    session.get.return_value  = resp
    return session