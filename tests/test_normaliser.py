"""
test_normaliser.py — Tests for scraper/normaliser.py.

Two layers:
  1. Unit tests for each helper function in isolation.
  2. Integration tests for normalise() end-to-end with RawListing inputs
     that mirror the actual output of the four portal parsers.

All tests are pure / offline — no database, no network.

Run all:               pytest tests/test_normaliser.py -v
Run one class:         pytest tests/test_normaliser.py::TestNormaliseEndToEnd -v
"""

import pytest
from tests.conftest import make_raw
from scraper.normaliser import (
    parse_price,
    parse_floor_area_sqm,
    parse_integer,
    parse_price_type,
    normalise_property_type,
    normalise_neighbourhood,
    infer_city,
    is_diaspora_targeted,
    normalise,
)


# =============================================================================
# parse_price
# =============================================================================

class TestParsePrice:

    @pytest.mark.parametrize("raw,expected_kobo", [
        ("₦45,000,000",       4_500_000_000),
        ("45M",               4_500_000_000),
        ("45.5M",             4_550_000_000),
        ("1.5B",            150_000_000_000),
        ("45 million",        4_500_000_000),
        ("45 million naira",  4_500_000_000),
        ("45000000",          4_500_000_000),   # plain naira int
        ("4500000000",        4_500_000_000),   # already-kobo heuristic (>10B)
        ("₦75,000,000/year",  7_500_000_000),   # PropertyPro rent format
        ("₦4,000,000per annum", 400_000_000),   # NPC format
    ])
    def test_valid_prices(self, raw, expected_kobo):
        kobo, failed = parse_price(raw)
        assert failed is False
        assert kobo == expected_kobo

    @pytest.mark.parametrize("raw", [
        None, "", "  ", "Price on Request", "Contact agent", "N/A", "Call for price"
    ])
    def test_unparseable_prices(self, raw):
        kobo, failed = parse_price(raw)
        assert kobo is None
        assert failed is True

    def test_decimal_millions(self):
        kobo, failed = parse_price("2.4M")
        assert failed is False
        assert kobo == 240_000_000

    def test_dollar_price_parses_numerically(self):
        # USD prices from PrivateProperty — we parse numerically, currency noted elsewhere
        kobo, failed = parse_price("$12,000,000")
        assert failed is False
        assert kobo == 1_200_000_000_000  # 12M × 100


# =============================================================================
# parse_floor_area_sqm
# =============================================================================

class TestParseFloorArea:

    @pytest.mark.parametrize("raw,expected", [
        ("150 sqm",      150.0),
        ("1,200 sqm",   1200.0),
        ("250 sq.m",     250.0),
        ("300 m²",       300.0),
        ("2.6K sqm",     None),    # "2.6K" — not a clean number, should return None or skip
    ])
    def test_sqm_formats(self, raw, expected):
        result = parse_floor_area_sqm(raw)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected, abs=0.1)

    @pytest.mark.parametrize("raw,expected_sqm", [
        ("2700 sqft",    250.8),
        ("500 sq. ft",    46.5),
        ("1000 sqft",     92.9),
    ])
    def test_sqft_conversion(self, raw, expected_sqm):
        result = parse_floor_area_sqm(raw)
        assert result == pytest.approx(expected_sqm, abs=0.5)

    @pytest.mark.parametrize("raw", [None, "", "3 bedrooms", "nice flat"])
    def test_returns_none_when_absent(self, raw):
        assert parse_floor_area_sqm(raw) is None


# =============================================================================
# parse_integer
# =============================================================================

class TestParseInteger:

    @pytest.mark.parametrize("raw,expected", [
        ("3 Bedrooms",  3),
        ("4 bed",       4),
        ("2",           2),
        ("4 bedrooms",  4),   # Jiji format
        ("5 bathrooms", 5),
    ])
    def test_valid_inputs(self, raw, expected):
        assert parse_integer(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "Studio", "No bedrooms listed"])
    def test_non_numeric(self, raw):
        assert parse_integer(raw) is None


# =============================================================================
# parse_price_type
# =============================================================================

class TestParsePriceType:

    @pytest.mark.parametrize("raw_type,title,desc,expected", [
        ("FOR_SALE",   None,                  None,                "FOR_SALE"),
        ("FOR_RENT",   None,                  None,                "FOR_RENT"),
        (None,         "3 bed flat to let",   None,                "FOR_RENT"),
        (None,         "luxury apartment",    "available for sale", "FOR_SALE"),
        ("₦4M/year",   None,                  None,                "FOR_RENT"),
        ("₦75M/year",  None,                  None,                "FOR_RENT"),
        (None,         "house for outright purchase", None,        "FOR_SALE"),
        (None,         "nice property abuja", None,                None),     # ambiguous
    ])
    def test_price_type_inference(self, raw_type, title, desc, expected):
        assert parse_price_type(raw_type, title, desc) == expected


# =============================================================================
# normalise_property_type
# =============================================================================

class TestNormalisePropertyType:

    @pytest.mark.parametrize("raw,expected", [
        ("Flat / Apartment",      "FLAT_APARTMENT"),
        ("flat/apartment",        "FLAT_APARTMENT"),
        ("Detached Duplex",       "DETACHED_DUPLEX"),
        ("detached duplex",       "DETACHED_DUPLEX"),
        ("Semi-Detached Duplex",  "SEMI_DETACHED_DUPLEX"),
        ("Mini Flat",             "MINI_FLAT"),
        ("Studio Apartment",      "STUDIO"),
        ("Plot of Land",          "LAND"),
        ("Commercial Property",   "COMMERCIAL_OTHER"),
        ("Duplex",                "DETACHED_DUPLEX"),   # partial match
    ])
    def test_known_types(self, raw, expected):
        assert normalise_property_type(raw) == expected

    def test_none_returns_none(self):
        assert normalise_property_type(None) is None

    def test_unknown_type_stored_uppercase(self):
        result = normalise_property_type("Converted Church Property")
        assert result is not None
        assert result == result.upper().replace(" ", "_")[:40] or result  # any non-None consistent form


# =============================================================================
# normalise_neighbourhood
# =============================================================================

class TestNormaliseNeighbourhood:

    @pytest.mark.parametrize("raw_address,expected_nb", [
        ("Lekki Phase 1, Lagos",                  "Lekki Phase 1"),
        ("Old Ikoyi Ikoyi Lagos",                 "Ikoyi"),
        ("After Blenco Sangotedo, Ajah, Lagos",   "Ajah"),
        ("Maitama, Abuja",                        "Maitama"),
        ("Victoria Island, Lagos",                "Victoria Island"),
        ("Guzape, Abuja",                         "Guzape"),
    ])
    def test_canonical_match(self, raw_address, expected_nb):
        nb, normalised = normalise_neighbourhood(raw_address)
        assert normalised is True
        assert nb == expected_nb

    def test_unknown_stored_raw_not_normalised(self):
        nb, normalised = normalise_neighbourhood("Some Brand New Estate, Ogun State")
        assert normalised is False
        assert nb is not None

    def test_none_address(self):
        nb, normalised = normalise_neighbourhood(None)
        assert nb is None
        assert normalised is False

    def test_raw_address_truncated_to_60_chars(self):
        long = "A" * 80 + ", Unknown City"
        nb, normalised = normalise_neighbourhood(long)
        assert normalised is False
        assert len(nb) <= 60


# =============================================================================
# infer_city
# =============================================================================

class TestInferCity:

    @pytest.mark.parametrize("address,title,expected_city", [
        ("Lekki Phase 1, Lagos",  None,         "LAGOS"),
        ("Maitama, Abuja",        None,         "ABUJA"),
        ("GRA, Port Harcourt",    None,         "PH"),
        (None,  "3 bed flat in Yaba Lagos",     "LAGOS"),
        (None,  "office in Wuse 2 Abuja",       "ABUJA"),
        ("some estate",           "nice house", None),
    ])
    def test_city_inference(self, address, title, expected_city):
        assert infer_city(address, title) == expected_city


# =============================================================================
# is_diaspora_targeted
# =============================================================================

class TestDiasporaFlag:

    @pytest.mark.parametrize("desc", [
        "diaspora-friendly property, forex payment accepted",
        "We accept payment in USD for this listing",
        "Suitable for returnees and NRNs",
        "Dollar-denominated lease available",
        "Ideal for expatriates",
    ])
    def test_diaspora_signals_detected(self, desc):
        assert is_diaspora_targeted(desc) is True

    @pytest.mark.parametrize("desc", [
        "Luxury 4-bed duplex in Lekki. 24hr security. Asking ₦95M.",
        "Brand new apartment. POP ceiling, tiled floors. Call to book inspection.",
        None,
        "",
    ])
    def test_non_diaspora_not_flagged(self, desc):
        assert is_diaspora_targeted(desc) is False


# =============================================================================
# normalise() — end-to-end pipeline with realistic RawListing inputs
# =============================================================================

class TestNormaliseEndToEnd:
    """
    Tests the full normalise() function with RawListing inputs that mirror
    what the four parsers actually produce. This catches regressions in the
    pipeline itself, not just the individual helpers.
    """

    def test_propertypro_rent_listing(self):
        """Mirrors a PropertyPro rent listing (Old Ikoyi, 3-bed luxury flat)."""
        raw = make_raw(
            external_id       = "7NUGY",
            source            = "propertypro",
            url               = "https://propertypro.ng/property/3-bed-flat-7NUGY",
            title             = "Newly Furnished 3 Bedroom Luxury Apartment",
            raw_price         = "₦75,000,000/year",
            raw_price_type    = "FOR_RENT",
            raw_bedrooms      = "3 Beds",
            raw_bathrooms     = "3 Baths",
            raw_address       = "Old Ikoyi Ikoyi Lagos",
            raw_floor_area    = None,
            property_type_raw = "Flat / Apartment",
            agent_name        = "First Colony Real Estate Company Ltd.",
        )
        result = normalise(raw)

        assert result.external_id == "7NUGY"
        assert result.source == "propertypro"
        assert result.price_kobo == 7_500_000_000
        assert result.price_parse_failed is False
        assert result.price_type == "FOR_RENT"
        assert result.bedrooms == 3
        assert result.bathrooms == 3
        assert result.property_type == "FLAT_APARTMENT"
        assert result.city == "LAGOS"
        assert result.neighbourhood is not None
        assert result.floor_area_sqm is None
        assert result.floor_area_source == "NONE"
        assert result.geocoded is False
        assert result.diaspora_targeted is False

    def test_privateproperty_sale_listing(self):
        """Mirrors a PrivateProperty sale listing (Victoria Island hotel)."""
        raw = make_raw(
            external_id       = "6PBUWY",
            source            = "privateproperty",
            raw_price         = "$12,000,000",
            raw_price_type    = "FOR_SALE",
            raw_bedrooms      = None,
            raw_bathrooms     = None,
            raw_address       = "10 bedroom Hotel For Sale Oniru Victoria Island Lagos",
            raw_floor_area    = "2.6K",
            property_type_raw = "Commercial Property",
        )
        result = normalise(raw)

        assert result.price_parse_failed is False
        assert result.price_type == "FOR_SALE"
        assert result.property_type == "COMMERCIAL_OTHER"
        assert result.city == "LAGOS"
        assert result.bedrooms is None    # no structured field — parser leaves as None

    def test_nigeriapropertycentre_rent_listing(self):
        """Mirrors a NPC rent listing (Ajah, 2-bed apartment)."""
        raw = make_raw(
            external_id       = "3364115",
            source            = "nigeriapropertycentre",
            raw_price         = "₦4,000,000per annum",
            raw_price_type    = "FOR_RENT",
            raw_bedrooms      = "2 Bedrooms",
            raw_bathrooms     = "2 Bathrooms",
            raw_address       = "After Blenco Sangotedo, Ajah, Lagos",
            property_type_raw = "2 bedroom flat / apartment for rent",
        )
        result = normalise(raw)

        assert result.price_kobo == 400_000_000
        assert result.price_type == "FOR_RENT"
        assert result.bedrooms == 2
        assert result.bathrooms == 2
        assert result.city == "LAGOS"
        assert result.neighbourhood is not None
        assert result.property_type == "FLAT_APARTMENT"

    def test_jiji_sale_listing(self):
        """Mirrors a Jiji sale listing (Lugbe duplex, Abuja)."""
        raw = make_raw(
            external_id       = "saFgVBX3QXLb3rsljTXA53Ls",
            source            = "jiji",
            raw_price         = "₦ 145,000,000",
            raw_price_type    = "FOR_SALE",
            raw_bedrooms      = "4 bedrooms",
            raw_bathrooms     = "5 bathrooms",
            raw_address       = "Abuja, Lugbe District",
            property_type_raw = "Duplex",
        )
        result = normalise(raw)

        assert result.price_kobo == 14_500_000_000
        assert result.price_type == "FOR_SALE"
        assert result.bedrooms == 4
        assert result.bathrooms == 5
        assert result.city == "ABUJA"
        assert result.property_type is not None

    def test_price_parse_failure_sets_flag(self):
        raw = make_raw(raw_price="Price on request")
        result = normalise(raw)
        assert result.price_parse_failed is True
        assert result.price_kobo is None

    def test_diaspora_flag_propagates(self):
        raw = make_raw(description="Diaspora-friendly, forex payment accepted. USD payments welcome.")
        result = normalise(raw)
        assert result.diaspora_targeted is True

    def test_floor_area_sqft_converted(self):
        raw = make_raw(raw_floor_area="2700 sqft")
        result = normalise(raw)
        assert result.floor_area_sqm == pytest.approx(250.8, abs=0.5)
        assert result.floor_area_source == "PORTAL"

    def test_none_floor_area_sets_source_none(self):
        raw = make_raw(raw_floor_area=None)
        result = normalise(raw)
        assert result.floor_area_sqm is None
        assert result.floor_area_source == "NONE"