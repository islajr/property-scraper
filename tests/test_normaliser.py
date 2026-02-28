"""
test_normaliser.py — Unit tests for scraper/normaliser.py.

All tests are pure / offline — no database, no network, no parsers.
Run with: pytest tests/test_normaliser.py -v
"""

import pytest
from scraper.normaliser import (
    parse_price,
    parse_floor_area_sqm,
    parse_integer,
    parse_price_type,
    normalise_property_type,
    normalise_neighbourhood,
    is_diaspora_targeted,
)


# =============================================================================
# parse_price
# =============================================================================

class TestParsePrice:

    def test_naira_with_commas(self):
        kobo, failed = parse_price("₦45,000,000")
        assert kobo == 4_500_000_000
        assert failed is False

    def test_shorthand_M(self):
        kobo, failed = parse_price("45M")
        assert kobo == 4_500_000_000
        assert failed is False

    def test_shorthand_M_decimal(self):
        kobo, failed = parse_price("45.5M")
        assert kobo == 4_550_000_000
        assert failed is False

    def test_shorthand_B(self):
        kobo, failed = parse_price("1.5B")
        assert kobo == 150_000_000_000
        assert failed is False

    def test_million_word(self):
        kobo, failed = parse_price("45 million")
        assert kobo == 4_500_000_000
        assert failed is False

    def test_million_word_with_naira(self):
        kobo, failed = parse_price("45 million naira")
        assert kobo == 4_500_000_000
        assert failed is False

    def test_plain_naira_integer(self):
        kobo, failed = parse_price("45000000")
        assert kobo == 4_500_000_000
        assert failed is False

    def test_already_in_kobo_heuristic(self):
        # Value > ₦10B naira → assume it's already kobo
        kobo, failed = parse_price("4500000000")
        assert kobo == 4_500_000_000
        assert failed is False

    def test_none_input(self):
        kobo, failed = parse_price(None)
        assert kobo is None
        assert failed is True

    def test_empty_string(self):
        kobo, failed = parse_price("")
        assert kobo is None
        assert failed is True

    def test_price_on_request(self):
        kobo, failed = parse_price("Price on Request")
        assert kobo is None
        assert failed is True

    def test_garbage_string(self):
        kobo, failed = parse_price("Contact agent")
        assert kobo is None
        assert failed is True


# =============================================================================
# parse_floor_area_sqm
# =============================================================================

class TestParseFloorAreaSqm:

    def test_sqm_simple(self):
        assert parse_floor_area_sqm("250 sqm") == 250.0

    def test_sqm_with_comma(self):
        assert parse_floor_area_sqm("1,200 sqm") == 1200.0

    def test_sqm_abbreviated(self):
        assert parse_floor_area_sqm("250 sq.m") == 250.0

    def test_sqft_to_sqm_conversion(self):
        result = parse_floor_area_sqm("2,700 sqft")
        assert result == pytest.approx(250.8, abs=0.5)  # 2700 × 0.0929 ≈ 250.8

    def test_sqft_abbreviated(self):
        result = parse_floor_area_sqm("500 sq. ft")
        assert result is not None
        assert result == pytest.approx(46.5, abs=0.5)

    def test_m2_symbol(self):
        assert parse_floor_area_sqm("300 m²") == 300.0

    def test_none_returns_none(self):
        assert parse_floor_area_sqm(None) is None

    def test_empty_returns_none(self):
        assert parse_floor_area_sqm("") is None

    def test_no_area_in_string(self):
        assert parse_floor_area_sqm("3 bedrooms, 2 bathrooms") is None


# =============================================================================
# parse_integer (bedrooms / bathrooms)
# =============================================================================

class TestParseInteger:

    def test_bedroom_string(self):
        assert parse_integer("3 Bedrooms") == 3

    def test_bed_abbreviated(self):
        assert parse_integer("4 bed") == 4

    def test_standalone_number(self):
        assert parse_integer("2") == 2

    def test_none_returns_none(self):
        assert parse_integer(None) is None

    def test_no_number_returns_none(self):
        assert parse_integer("Studio") is None


# =============================================================================
# parse_price_type
# =============================================================================

class TestParsePriceType:

    def test_for_sale_from_raw_type(self):
        assert parse_price_type("For Sale", None, None) == "FOR_SALE"

    def test_for_rent_from_raw_type(self):
        assert parse_price_type("For Rent", None, None) == "FOR_RENT"

    def test_rent_detected_in_title(self):
        assert parse_price_type(None, "3-bed flat to let in Lekki", None) == "FOR_RENT"

    def test_per_year_is_rent(self):
        assert parse_price_type("₦2.4M per year", None, None) == "FOR_RENT"

    def test_sale_detected_in_description(self):
        result = parse_price_type(None, None, "Available for outright purchase")
        assert result == "FOR_SALE"

    def test_none_when_ambiguous(self):
        # No keywords → None
        result = parse_price_type(None, "Nice property in Abuja", None)
        assert result is None


# =============================================================================
# normalise_property_type
# =============================================================================

class TestNormalisePropertyType:

    def test_flat_apartment(self):
        assert normalise_property_type("Flat / Apartment") == "FLAT_APARTMENT"

    def test_detached_duplex(self):
        assert normalise_property_type("Detached Duplex") == "DETACHED_DUPLEX"

    def test_case_insensitive(self):
        assert normalise_property_type("detached duplex") == "DETACHED_DUPLEX"

    def test_mini_flat(self):
        assert normalise_property_type("Mini Flat") == "MINI_FLAT"

    def test_studio(self):
        assert normalise_property_type("Studio Apartment") == "STUDIO"

    def test_land(self):
        assert normalise_property_type("Plot of Land") == "LAND"

    def test_none_returns_none(self):
        assert normalise_property_type(None) is None


# =============================================================================
# normalise_neighbourhood
# =============================================================================

class TestNormaliseNeighbourhood:

    def test_exact_canonical_match(self):
        nb, normalised = normalise_neighbourhood("Lekki Phase 1, Lagos")
        assert nb == "Lekki Phase 1"
        assert normalised is True

    def test_fuzzy_match_lekki_variant(self):
        nb, normalised = normalise_neighbourhood("Lekki Ph1, Lagos")
        # Should fuzzy-match to "Lekki Phase 1"
        assert normalised is True
        assert "Lekki" in nb

    def test_victoria_island_in_address(self):
        nb, normalised = normalise_neighbourhood("5 Ozumba Mbadiwe Avenue, Victoria Island")
        assert nb == "Victoria Island"
        assert normalised is True

    def test_unknown_neighbourhood_stored_raw(self):
        nb, normalised = normalise_neighbourhood("Somewhere New Estate, Ogun")
        assert normalised is False
        assert nb is not None

    def test_none_address_returns_none(self):
        nb, normalised = normalise_neighbourhood(None)
        assert nb is None
        assert normalised is False

    def test_maitama_abuja(self):
        nb, normalised = normalise_neighbourhood("No 4, Maitama, Abuja")
        assert nb == "Maitama"
        assert normalised is True


# =============================================================================
# is_diaspora_targeted
# =============================================================================

class TestDiasporaFlag:

    def test_diaspora_keyword_detected(self):
        assert is_diaspora_targeted("This property is diaspora-friendly, forex payment accepted.") is True

    def test_forex_payment_accepted(self):
        assert is_diaspora_targeted("We accept forex payment for this listing.") is True

    def test_payment_in_usd(self):
        assert is_diaspora_targeted("Payment in USD accepted.") is True

    def test_suitable_for_returnees(self):
        assert is_diaspora_targeted("Suitable for returnees and NRNs.") is True

    def test_standard_description_not_flagged(self):
        desc = ("Luxury 4-bedroom detached duplex in Lekki Phase 1. "
                "En-suite bathrooms, swimming pool, 24hr security. Asking ₦95M.")
        assert is_diaspora_targeted(desc) is False

    def test_none_description_not_flagged(self):
        assert is_diaspora_targeted(None) is False

    def test_empty_description_not_flagged(self):
        assert is_diaspora_targeted("") is False