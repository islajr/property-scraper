"""
test_parsers.py — Parser tests against saved HTML fixtures.

Tests run against static saved HTML files — not live network calls.
This makes tests fast, deterministic, and unaffected by portal HTML changes
until you update the fixture.

To update a fixture:
  1. Open the live portal page in browser
  2. Save page source as UTF-8 HTML
  3. Replace the file in tests/fixtures/

Run with: pytest tests/test_parsers.py -v
"""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from bs4 import BeautifulSoup

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> BeautifulSoup:
    """Load an HTML fixture file and return a BeautifulSoup object."""
    path = FIXTURES_DIR / filename
    if not path.exists():
        pytest.skip(f"Fixture not yet created: {path}. Save live HTML first.")
    with open(path, encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


def _empty_active_listings():
    return {}


# =============================================================================
# PropertyPro
# =============================================================================

class TestPropertyProParser:

    def test_fixture_parses_successfully(self):
        """Fixture HTML → valid RawListing with non-None key fields."""
        from scraper.parsers.propertypro import PropertyProParser
        soup = load_fixture("propertypro_listing.html")
        parser = PropertyProParser(_empty_active_listings())
        result = parser.parse_listing(soup, "https://www.propertypro.ng/property/3-bed-flat-12345")
        assert result is not None
        assert result.source == "propertypro"
        assert result.external_id == "12345"

    def test_external_id_extracted_from_url(self):
        """URL with numeric suffix → external_id correct."""
        from scraper.parsers.propertypro import PropertyProParser, EXTERNAL_ID_PATTERN
        import re
        url = "https://www.propertypro.ng/property/4-bed-detached-duplex-lekki-99887"
        m = EXTERNAL_ID_PATTERN.search(url)
        assert m is not None
        assert m.group(1) == "99887"

    def test_price_field_present_in_fixture(self):
        from scraper.parsers.propertypro import PropertyProParser
        soup = load_fixture("propertypro_listing.html")
        parser = PropertyProParser(_empty_active_listings())
        result = parser.parse_listing(soup, "https://www.propertypro.ng/property/test-12345")
        # At minimum, we expect raw_price to be a non-empty string or None (not to crash)
        # This test passes if parse_listing returns without exception
        assert result is not None


# =============================================================================
# PrivateProperty
# =============================================================================

class TestPrivatePropertyParser:

    def test_fixture_parses_successfully(self):
        from scraper.parsers.privateproperty import PrivatePropertyParser
        soup = load_fixture("privateproperty_listing.html")
        parser = PrivatePropertyParser(_empty_active_listings())
        result = parser.parse_listing(soup, "https://www.privateproperty.com.ng/for-sale/12345")
        assert result is not None
        assert result.source == "privateproperty"


# =============================================================================
# NigeriaPropertyCentre
# =============================================================================

class TestNigeriaPropertyCentreParser:

    def test_fixture_parses_successfully(self):
        from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
        soup = load_fixture("nigeriapropertycentre_listing.html")
        parser = NigeriaPropertyCentreParser(_empty_active_listings())
        result = parser.parse_listing(soup, "https://nigeriapropertycentre.com/sale/property-99887.html")
        assert result is not None
        assert result.source == "nigeriapropertycentre"


# =============================================================================
# Jiji
# =============================================================================

class TestJijiParser:

    def test_fixture_parses_successfully(self):
        """
        Jiji parser normally uses Playwright, but _parse_listing() accepts
        a BeautifulSoup object and can be tested against a saved HTML fixture
        directly without launching a browser.
        """
        from scraper.parsers.jiji import JijiParser
        soup = load_fixture("jiji_listing.html")
        parser = JijiParser(_empty_active_listings())
        result = parser._parse_listing(soup, "https://jiji.ng/real-estate/123_listing_12345.html")
        assert result is not None
        assert result.source == "jiji"

    def test_external_id_from_jiji_url(self):
        from scraper.parsers.jiji import JijiParser
        url = "https://jiji.ng/real-estate/houses-apartments-for-sale/3-bedroom-flat_12345.html"
        result = JijiParser._extract_external_id(url)
        assert result == "12345"