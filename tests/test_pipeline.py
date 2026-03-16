"""
test_pipeline.py — Integration tests for the parser → normalise → geocode chain.

These tests mock the database and Nominatim but run the real parser, real
normaliser, and real geocoder code in sequence. This is the closest thing to
a dry run of the orchestrator without touching any external services.

Run all:               pytest tests/test_pipeline.py -v
Run one test:          pytest tests/test_pipeline.py::TestParserToNormaliser::test_propertypro_fixture -v
"""

import pytest
from unittest.mock import patch

from tests.conftest import load_fixture, mock_db, mock_nominatim
from scraper import normaliser
from scraper.geocoder import Geocoder


# =============================================================================
# Parser → Normaliser
# Tests that the raw output of each parser survives normalisation without errors
# and produces the expected typed fields.
# =============================================================================

class TestParserToNormaliser:

    def _parse_and_normalise(self, parser_cls, fixture_file, url):
        parser = parser_cls(active_listings={})
        soup   = load_fixture(fixture_file)
        raw    = parser.parse_listing(soup, url)
        assert raw is not None, "parse_listing returned None — check parser selectors"
        return normaliser.normalise(raw)

    def test_propertypro_fixture(self):
        from scraper.parsers.propertypro import PropertyProParser
        url    = "https://propertypro.ng/property/3-bedroom-flat-apartment-for-rent-old-ikoyi-ikoyi-lagos-7NUGY"
        result = self._parse_and_normalise(PropertyProParser, "propertypro_listing.html", url)

        assert result.external_id == "7NUGY"
        assert result.price_kobo == 7_500_000_000
        assert result.price_parse_failed is False
        assert result.price_type == "FOR_RENT"
        assert result.bedrooms == 3
        assert result.bathrooms == 3
        assert result.property_type == "FLAT_APARTMENT"
        assert result.city == "LAGOS"
        assert result.neighbourhood is not None

    def test_privateproperty_fixture(self):
        from scraper.parsers.privateproperty import PrivatePropertyParser
        url    = "https://privateproperty.ng/listings/10-bedroom-hotel-for-sale-oniru-victoria-island-lagos-6PBUWY"
        result = self._parse_and_normalise(PrivatePropertyParser, "privateproperty_listing.html", url)

        assert result.external_id == "6PBUWY"
        assert result.price_parse_failed is False
        assert result.price_type == "FOR_SALE"
        assert result.city == "LAGOS"

    def test_nigeriapropertycentre_fixture(self):
        from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
        url    = "https://nigeriapropertycentre.com/for-rent/flats-apartments/lagos/ajah/3364115-brand-new-2-bedrooms-apartment"
        result = self._parse_and_normalise(NigeriaPropertyCentreParser, "nigeriapropertycentre_listing.html", url)

        assert result.external_id == "3364115"
        assert result.price_kobo == 400_000_000
        assert result.price_type == "FOR_RENT"
        assert result.bedrooms == 2
        assert result.bathrooms == 2
        assert result.city == "LAGOS"

    def test_jiji_fixture(self):
        from scraper.parsers.jiji import JijiParser
        url    = "https://jiji.ng/lugbe/houses-apartments-for-sale/4bdrm-duplex-in-voice-of-nigeria-lugbe-district-for-sale-saFgVBX3QXLb3rsljTXA53Ls.html"
        parser = JijiParser(active_listings={})
        soup   = load_fixture("jiji_listing.html")
        raw    = parser._parse_listing(soup, url)
        assert raw is not None
        result = normaliser.normalise(raw)

        assert result.external_id == "saFgVBX3QXLb3rsljTXA53Ls"
        assert result.price_kobo == 14_500_000_000
        assert result.price_type == "FOR_SALE"
        assert result.bedrooms == 4
        assert result.bathrooms == 5
        assert result.city == "ABUJA"

    def test_all_fixtures_normalise_without_exception(self):
        """Smoke test: all four fixtures must complete without raising."""
        test_cases = [
            ("scraper.parsers.propertypro",          "PropertyProParser",
             "propertypro_listing.html",
             "https://propertypro.ng/property/test-7NUGY"),
            ("scraper.parsers.privateproperty",       "PrivatePropertyParser",
             "privateproperty_listing.html",
             "https://privateproperty.ng/listings/test-6PBUWY"),
            ("scraper.parsers.nigeriapropertycentre", "NigeriaPropertyCentreParser",
             "nigeriapropertycentre_listing.html",
             "https://nigeriapropertycentre.com/for-rent/flats/lagos/3364115-test"),
        ]
        import importlib
        for module_name, cls_name, fixture, url in test_cases:
            mod    = importlib.import_module(module_name)
            cls    = getattr(mod, cls_name)
            parser = cls(active_listings={})
            soup   = load_fixture(fixture)
            raw    = parser.parse_listing(soup, url)
            if raw is not None:
                normaliser.normalise(raw)   # must not raise


# =============================================================================
# Normaliser → Geocoder
# Tests that normalised listings flow through the geocoder correctly.
# =============================================================================

class TestNormaliserToGeocoder:

    def test_geocoder_enriches_normalised_listing(self):
        from tests.conftest import make_raw
        raw    = make_raw(raw_address="Lekki Phase 1, Lagos")
        normed = normaliser.normalise(raw)

        db  = mock_db()
        geo = Geocoder(db)
        geo.session = mock_nominatim(lat=6.4698, lng=3.5852)

        with patch("scraper.geocoder.time.sleep"):
            results = geo.enrich([normed])

        assert results[0].geocoded is True
        assert results[0].lat == pytest.approx(6.4698, abs=0.001)

    def test_full_chain_propertypro_fixture(self):
        """Parser → normalise → geocode without any live calls."""
        from scraper.parsers.propertypro import PropertyProParser

        url    = "https://propertypro.ng/property/3-bedroom-flat-apartment-for-rent-old-ikoyi-ikoyi-lagos-7NUGY"
        parser = PropertyProParser(active_listings={})
        soup   = load_fixture("propertypro_listing.html")
        raw    = parser.parse_listing(soup, url)
        normed = normaliser.normalise(raw)

        db  = mock_db()
        geo = Geocoder(db)
        geo.session = mock_nominatim(lat=6.44, lng=3.43)

        with patch("scraper.geocoder.time.sleep"):
            enriched = geo.enrich([normed])

        result = enriched[0]
        assert result.external_id == "7NUGY"
        assert result.price_kobo == 7_500_000_000
        assert result.geocoded is True
        assert result.lat == pytest.approx(6.44, abs=0.01)
        assert result.city == "LAGOS"


# =============================================================================
# Normaliser — batch behaviour
# =============================================================================

class TestNormaliserBatch:

    def test_batch_of_mixed_sources(self):
        """Normalising listings from different portals in one batch works correctly."""
        from tests.conftest import make_raw

        raws = [
            make_raw(source="propertypro",          external_id="A", raw_price="₦45M",          raw_price_type="FOR_SALE"),
            make_raw(source="privateproperty",       external_id="B", raw_price="₦80,000,000",   raw_price_type="FOR_SALE"),
            make_raw(source="nigeriapropertycentre", external_id="C", raw_price="₦4M per annum", raw_price_type="FOR_RENT"),
            make_raw(source="jiji",                  external_id="D", raw_price="145M",           raw_price_type="FOR_SALE"),
        ]
        results = [normaliser.normalise(r) for r in raws]

        assert len(results) == 4
        assert all(not r.price_parse_failed for r in results)
        assert results[0].price_kobo == 4_500_000_000
        assert results[2].price_type == "FOR_RENT"
        assert results[3].price_kobo == 14_500_000_000