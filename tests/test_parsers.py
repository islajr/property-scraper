"""
test_parsers.py — Parser tests against committed HTML fixtures.

ALL tests are fully offline. The fixtures in tests/fixtures/ were captured
from live pages and committed to the repo. To refresh a fixture after a portal
HTML change, save the live page source (UTF-8) and replace the file.

Tests assert specific field values extracted from the known fixture content,
not just "did it return something." This means a selector regression is caught
immediately — you'll see exactly which field broke and what was expected.

Run all:                   pytest tests/test_parsers.py -v
Run one portal:            pytest tests/test_parsers.py::TestPropertyProParser -v
Run one test:              pytest tests/test_parsers.py::TestJijiParser::test_attributes -v
"""

import pytest
from tests.conftest import load_fixture


# ── Shared URL constants (the canonical URL embedded in each fixture) ──────────
PP_URL   = "https://propertypro.ng/property/3-bedroom-flat-apartment-for-rent-old-ikoyi-ikoyi-lagos-7NUGY"
PRIV_URL = "https://privateproperty.ng/listings/10-bedroom-hotel-for-sale-oniru-victoria-island-lagos-6PBUWY"
NPC_URL  = "https://nigeriapropertycentre.com/for-rent/flats-apartments/lagos/ajah/3364115-brand-new-2-bedrooms-apartment"
JIJI_URL = "https://jiji.ng/lugbe/houses-apartments-for-sale/4bdrm-duplex-in-voice-of-nigeria-lugbe-district-for-sale-saFgVBX3QXLb3rsljTXA53Ls.html"


# =============================================================================
# PropertyPro
# =============================================================================

class TestPropertyProParser:
    """
    Fixture: tests/fixtures/propertypro_listing.html
    Source:  Newly Furnished 3 Bedroom Luxury Apartment, Old Ikoyi
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        from scraper.parsers.propertypro import PropertyProParser
        self.parser = PropertyProParser(active_listings={})
        self.soup   = load_fixture("propertypro_listing_page.html")
        self.result = self.parser.parse_listing(self.soup, PP_URL)

    def test_parse_does_not_crash(self):
        assert self.result is not None

    def test_source(self):
        assert self.result.source == "propertypro"

    def test_external_id(self):
        # ID is the alphanumeric suffix after the last dash in the canonical URL
        assert self.result.external_id == "7NUGY"

    def test_title(self):
        assert "3 Bedroom" in self.result.title
        assert "Luxury" in self.result.title
        
    def test_description(self):
        assert self.result.description != None
        assert "Newly furnished 3 Bedroom Apartment" in self.result.description 

    def test_price_raw(self):
        # Fixture: ₦75,000,000/year — must be present and contain the amount
        assert self.result.raw_price is not None
        assert "75" in self.result.raw_price

    def test_price_type_inferred_as_rent(self):
        # "/year" in price string → FOR_RENT
        assert self.result.raw_price_type == "FOR_RENT"

    def test_bedrooms(self):
        assert self.result.raw_bedrooms is not None
        assert "3" in self.result.raw_bedrooms

    def test_bathrooms(self):
        assert self.result.raw_bathrooms is not None
        assert "3" in self.result.raw_bathrooms

    def test_address_contains_ikoyi(self):
        assert self.result.raw_address is not None
        assert "Ikoyi" in self.result.raw_address

    def test_agent_name(self):
        assert self.result.agent_name is not None
        assert "First Colony" in self.result.agent_name

    def test_url_is_canonical(self):
        assert self.result.url == PP_URL

    # ── External ID extraction (no HTML needed) ──────────────────────────────

    @pytest.mark.parametrize("url,expected_id", [
        ("https://propertypro.ng/property/3-bed-flat-lekki-7NUGY",   "7NUGY"),
        ("https://propertypro.ng/property/land-for-sale-ajah-3PFWM", "3PFWM"),
        ("https://propertypro.ng/property/duplex-abuja-AB12C",        "AB12C"),
    ])
    def test_external_id_regex(self, url, expected_id):
        from scraper.parsers.propertypro import EXTERNAL_ID_PATTERN
        m = EXTERNAL_ID_PATTERN.search(url)
        assert m is not None, f"Pattern did not match: {url}"
        assert m.group(1) == expected_id


# =============================================================================
# PrivateProperty
# =============================================================================

class TestPrivatePropertyParser:
    """
    Fixture: tests/fixtures/privateproperty_listing.html
    Source:  10-bedroom hotel for sale, Victoria Island
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        from scraper.parsers.privateproperty import PrivatePropertyParser
        self.parser = PrivatePropertyParser(active_listings={})
        self.soup   = load_fixture("privateproperty_listing_page.html")
        self.result = self.parser.parse_listing(self.soup, PRIV_URL)

    def test_parse_does_not_crash(self):
        assert self.result is not None

    def test_source(self):
        assert self.result.source == "privateproperty"

    def test_external_id(self):
        assert self.result.external_id == "6PBUWY"

    def test_title_present(self):
        assert self.result.title
        assert len(self.result.title) > 10

    def test_description(self):
        assert self.result.description is not None
        assert "A Building Suitable for a Hotel" in self.result.description

    def test_price_raw(self):
        # Fixture price is in USD for this commercial listing
        assert self.result.raw_price is not None
        assert "12,000,000" in self.result.raw_price or "12000000" in self.result.raw_price

    def test_price_type_inferred_as_sale(self):
        assert self.result.raw_price_type == "FOR_SALE"

    def test_address_contains_victoria_island(self):
        assert self.result.raw_address is not None
        assert "Victoria Island" in self.result.raw_address or "Oniru" in self.result.raw_address

    # def test_agent_name(self):
    #     assert self.result.agent_name is not None
    #     assert "Absaat" in self.result.agent_name

    # def test_property_type_commercial(self):
    #     # Fixture is a hotel — property type should indicate commercial
    #     assert self.result.property_type_raw is not None
    #     assert "Commercial" in self.result.property_type_raw or "Hotel" in self.result.property_type_raw

    @pytest.mark.parametrize("url,expected_id", [
        ("https://privateproperty.ng/listings/3-bed-duplex-lekki-6PBUWY",     "6PBUWY"),
        ("https://privateproperty.ng/listings/flat-yaba-lagos-XY99ZZ",         "XY99ZZ"),
    ])
    def test_external_id_regex(self, url, expected_id):
        from scraper.parsers.privateproperty import EXTERNAL_ID_PATTERN
        m = EXTERNAL_ID_PATTERN.search(url)
        assert m is not None
        assert m.group(1) == expected_id


# =============================================================================
# NigeriaPropertyCentre
# =============================================================================

class TestNigeriaPropertyCentreParser:
    """
    Fixture: tests/fixtures/nigeriapropertycentre_listing.html
    Source:  Brand New 2 Bedrooms Apartment, Sangotedo Ajah Lagos
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
        self.parser = NigeriaPropertyCentreParser(active_listings={})
        self.soup   = load_fixture("nigeriapropertycentre_listing_page.html")
        self.result = self.parser.parse_listing(self.soup, NPC_URL)

    def test_parse_does_not_crash(self):
        assert self.result is not None

    def test_source(self):
        assert self.result.source == "nigeriapropertycentre"

    def test_external_id(self):
        assert self.result.external_id == "3364115"

    def test_title(self):
        assert "2 Bedroom" in self.result.title or "2 bedroom" in self.result.title

    def test_price_raw(self):
        assert self.result.raw_price is not None
        assert "4,000,000" in self.result.raw_price

    def test_price_type_inferred_as_rent(self):
        # "per annum" in price → FOR_RENT
        assert self.result.raw_price_type == "FOR_RENT"

    def test_address(self):
        assert self.result.raw_address is not None
        assert "Ajah" in self.result.raw_address or "Sangotedo" in self.result.raw_address

    def test_bedrooms_structured(self):
        assert self.result.raw_bedrooms is not None
        assert "2" in self.result.raw_bedrooms

    def test_bathrooms_structured(self):
        assert self.result.raw_bathrooms is not None
        assert "2" in self.result.raw_bathrooms

    def test_description_present(self):
        assert self.result.description is not None
        assert len(self.result.description) > 30

    def test_agent_name(self):
        assert self.result.agent_name is not None
        assert "Matrealty" in self.result.agent_name

    @pytest.mark.parametrize("url,expected_id", [
        ("https://nigeriapropertycentre.com/for-sale/houses/lagos/lekki/3364115-some-house", "3364115"),
        ("https://nigeriapropertycentre.com/for-rent/flats/abuja/maitama/9876543-nice-flat", "9876543"),
    ])
    def test_external_id_regex(self, url, expected_id):
        from scraper.parsers.nigeriapropertycentre import EXTERNAL_ID_PATTERN
        m = EXTERNAL_ID_PATTERN.search(url)
        assert m is not None
        assert m.group(1) == expected_id


# =============================================================================
# Jiji
# =============================================================================

# class TestJijiParser:
#     """
#     Fixture: tests/fixtures/jiji_listing.html
#     Source:  4bdrm Duplex in Voice of Nigeria, Lugbe District, Abuja

#     Note: _parse_listing() accepts a BeautifulSoup directly, so Playwright is
#     never launched in these tests. The Playwright-dependent scrape() method is
#     excluded from unit testing — it is integration-tested manually.
#     """

#     @pytest.fixture(autouse=True)
#     def setup(self):
#         from scraper.parsers.jiji import JijiParser
#         self.parser = JijiParser(active_listings={})
#         self.soup   = load_fixture("jiji_listing.html")
#         self.result = self.parser._parse_listing(self.soup, JIJI_URL)

#     def test_parse_does_not_crash(self):
#         assert self.result is not None

#     def test_source(self):
#         assert self.result.source == "jiji"

#     def test_external_id(self):
#         assert self.result.external_id == "saFgVBX3QXLb3rsljTXA53Ls"

#     def test_title(self):
#         assert "Duplex" in self.result.title or "duplex" in self.result.title

#     def test_price_raw(self):
#         assert self.result.raw_price is not None
#         assert "145" in self.result.raw_price

#     def test_price_type_sale_from_url(self):
#         assert self.result.raw_price_type == "FOR_SALE"

#     def test_address_contains_abuja(self):
#         assert self.result.raw_address is not None
#         assert "Abuja" in self.result.raw_address or "Lugbe" in self.result.raw_address

#     def test_property_type_attribute(self):
#         # First attribute element is property type
#         assert self.result.property_type_raw is not None
#         assert "Duplex" in self.result.property_type_raw

#     def test_bedrooms_from_attributes(self):
#         assert self.result.raw_bedrooms is not None
#         assert "4" in self.result.raw_bedrooms

#     def test_bathrooms_from_attributes(self):
#         assert self.result.raw_bathrooms is not None
#         assert "5" in self.result.raw_bathrooms

#     def test_description_present(self):
#         assert self.result.description is not None
#         assert len(self.result.description) > 20

#     def test_agent_name(self):
#         assert self.result.agent_name is not None
#         assert "Mubarak" in self.result.agent_name

#     @pytest.mark.parametrize("url,expected_id", [
#         (JIJI_URL, "saFgVBX3QXLb3rsljTXA53Ls"),
#         ("https://jiji.ng/abuja/houses/3bed-flat-XYZ1234567890AB.html", "XYZ1234567890AB"),
#     ])
#     def test_external_id_regex(self, url, expected_id):
#         from scraper.parsers.jiji import JijiParser
#         result = JijiParser._extract_external_id(url)
#         assert result == expected_id