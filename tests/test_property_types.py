"""Evidence-based regression cases; no database or portal requests."""
from dataclasses import asdict
import json
from pathlib import Path
import pytest
from scraper.property_types import TYPES, VERSION, FIELDS, classify, decision_key
from scraper.models import NormalisedListing, RawListing
from scraper.normaliser import normalise
from tests.conftest import make_raw, make_normalised, load_fixture

CASES = json.loads((Path(__file__).parent/'fixtures/property_type_cases.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda case: f"{case['source']}-{case['id']}")
def test_reviewed_title_evidence_cases(case):
    """These title-only expectations are regression examples, not an accuracy estimate."""
    result = classify(title=case['title'])
    assert result.property_type == case['type'], case['reason']
    assert result.property_type_status == case['status'], case['reason']


@pytest.mark.parametrize('code', sorted(TYPES))
def test_canonical_codes_are_idempotent(code):
    result = classify(code)
    assert result.property_type == code
    assert result.property_category == TYPES[code].category
    assert result.property_type_family == TYPES[code].family
    assert result.property_attachment == TYPES[code].attachment
    assert result.property_type_status == 'CLASSIFIED'
    assert result.property_type_version == VERSION
    assert decision_key(result) == decision_key(classify(result.property_type))


@pytest.mark.parametrize('text,expected', [
    ('4 bedroom semi-detached duplex for sale', 'SEMI_DETACHED_DUPLEX'),
    ('4 bedroom semi detached duplex for rent', 'SEMI_DETACHED_DUPLEX'),
    ('Semi–detached bungalow', 'SEMI_DETACHED_BUNGALOW'),
    ('Luxury terrace duplex', 'TERRACED_DUPLEX'),
    ('Terraces of 4 bedroom duplexes', 'TERRACED_DUPLEX'),
    ('Fully detached bungalow', 'DETACHED_BUNGALOW'),
    ('Luxury mini flat for rent', 'MINI_FLAT'), ('Newly built miniflat', 'MINI_FLAT'),
    ('A room and parlour self contain', 'MINI_FLAT'), ('Self contain apartment', 'SELF_CONTAINED'),
    ('Studio apartment for rent', 'STUDIO'), ('Studio flat', 'STUDIO'),
    ('Self contain (single rooms) for rent', 'SELF_CONTAINED'),
    ('A single room for rent', 'ROOM'), ('3 bedroom maisonette', 'MAISONETTE'),
    ('Plot of land for sale', 'LAND'), ('Serviced land for sale', 'LAND_SERVICED'),
    ('Two bedroom duplex', 'DUPLEX'), ('3 bedroom bungalow', 'BUNGALOW'),
    ('4 bedroom townhouse', 'TOWNHOUSE'), ('A block of 6 flats', 'BLOCK_OF_FLATS'),
    ('Apartment in a block of flats', 'FLAT_APARTMENT'),
    ('21 room luxury hotel for lease', 'HOTEL'), ('Office building for sale', 'OFFICE_BUILDING'),
    ('Commercial Property', 'COMMERCIAL_OTHER'), ('A warehouse', 'WAREHOUSE'),
    ('Mixed-use building', 'MIXED_USE_PROPERTY'), ('A purpose-built hospital', 'HOSPITAL'),
    ('A petrol station for sale', 'FILLING_STATION'),
])
def test_asset_phrases(text, expected):
    result = classify(title=text)
    assert result.property_type == expected
    assert result.property_type_status == 'CLASSIFIED'


@pytest.mark.parametrize('text', [
    '', 'A beautiful home', '4 bedrooms in Lekki', 'Shoprite nearby',
    'A building suitable for a hotel', 'A building ideal for a school',
    'Near a hospital', 'Not a duplex', 'For rent: 2BED',
])
def test_no_type_is_invented(text):
    result = classify(title=text)
    assert result.property_type is None
    assert result.property_type_status == 'INSUFFICIENT_EVIDENCE'


@pytest.mark.parametrize('raw,title,expected', [
    ('Semi-detached', '4 bedroom duplex', 'SEMI_DETACHED_DUPLEX'),
    ('Flat / Apartment', 'Mini flat', 'MINI_FLAT'),
    ('Commercial Property', 'Hotel for sale', 'HOTEL'),
    ('Unknown portal label', 'A 3 bedroom bungalow', 'BUNGALOW'),
    ('DETACHED_DUPLEX', 'A duplex', 'DETACHED_DUPLEX'),
])
def test_compatible_refinement(raw, title, expected):
    assert classify(raw, title).property_type == expected


@pytest.mark.parametrize('raw,title', [
    ('Block of flats', '2 bedroom apartment'), ('Land', 'Luxury apartment'),
    ('Mixed-use', '3 bedroom terrace duplex'), ('Commercial', '3 bedroom bungalow'),
    ('Warehouse', 'Hotel for sale'), ('Gas plant', 'A filling station'),
])
def test_conflicting_assets_stay_ambiguous(raw, title):
    result = classify(raw, title)
    assert result.property_type_status == 'AMBIGUOUS'
    assert result.property_type is None
    assert len(result.property_type_evidence['candidates']) >= 2


def test_attachment_conflict_retains_only_supported_broad_form():
    result = classify('Detached duplex', 'Semi-detached duplex')
    assert result.property_type == 'DUPLEX'
    assert result.property_attachment is None
    assert result.property_type_evidence['reason'] == 'attachment_conflict'


def test_amenities_and_development_opportunities_do_not_imply_form_or_attachment():
    result = classify(title='One Bedroom Bungalow W/Terrace')
    assert result.property_type == 'BUNGALOW'
    assert result.property_attachment is None
    assert classify(title='68-Hectare Mixed-Use Development Opportunity').property_type is None
    assert classify(title='Luxury Hous Wit Restaurant on 1 floor').property_type is None
    assert classify(title='4 Bedroom Detached', description='4 Bed Rooms fully detached').property_type is None
    result = classify(title='5 Bed Detached Home With Bq')
    assert result.property_type == 'HOUSE' and result.property_attachment == 'DETACHED'


@pytest.mark.parametrize('label', ['Gas plant', 'Converted church', 'Unmapped specialized asset'])
def test_unsupported_labels_have_explicit_marker(label):
    result = classify(label)
    assert result.property_type is None
    assert result.property_type_status == 'UNSUPPORTED'
    assert result.property_type_raw == label


def test_description_fallback_is_contextual_and_does_not_override_primary_asset():
    assert classify(None, 'A great opportunity', 'A semi-detached duplex for sale.').property_type == 'SEMI_DETACHED_DUPLEX'
    assert classify(None, '', 'Features:\nOffice space\nNear a hospital').property_type is None
    assert classify(None, '', 'This property is near a school and warehouse').property_type is None
    assert classify(None, 'Luxury apartment', 'Amenities:\nOffice space\nMini flat BQ').property_type == 'FLAT_APARTMENT'


@pytest.mark.parametrize('raw,title,use', [
    ('Residential', '400 sqm land for sale', 'RESIDENTIAL'),
    ('Commercial', '3,000 sqm land', 'COMMERCIAL'),
    ('Mixed-use', 'Land for sale', 'MIXED_USE'),
    (None, 'Industrial land', 'INDUSTRIAL'), (None, 'Agricultural land', 'AGRICULTURAL'),
])
def test_land_use_does_not_become_building_type(raw, title, use):
    result = classify(raw, title)
    assert result.property_type == 'LAND'
    assert result.property_category == 'LAND'
    assert result.property_asset_scope == 'LAND_PARCEL'
    assert result.property_land_use == use


def test_multiple_units_are_not_an_entire_block():
    result = classify(title='2 units of 3 bedroom apartments')
    assert result.property_type == 'FLAT_APARTMENT'
    assert result.property_asset_scope == 'MULTIPLE_UNITS'
    assert classify(title='1 unit of 3 bedroom flat').property_asset_scope == 'UNIT'
    assert classify(title='Two units of 3 bedroom flat').property_asset_scope == 'MULTIPLE_UNITS'


def test_category_can_be_known_without_form_and_bedrooms_do_not_guess_it():
    result = normalise(make_raw(property_type_raw='Residential', title='A great opportunity',
                                description=None, raw_bedrooms='4 bedrooms'))
    assert result.property_type is None
    assert result.property_category == 'RESIDENTIAL'
    assert result.property_type_status == 'INSUFFICIENT_EVIDENCE'
    assert result.bedrooms == 4


def test_evidence_contains_exact_primary_text_and_rule_ids():
    result = classify('Semi–detached', 'Luxury Duplex')
    assert result.property_type_raw == 'Semi–detached'
    assert any(e['text'] == 'Semi–detached' and e['source'] == 'PORTAL_TYPE'
               and e['rule'] == 'attachment:semi_detached' for e in result.property_type_evidence['matches'])


def test_old_checkpoint_shapes_remain_readable_without_certifying_old_types():
    raw = asdict(make_raw())
    raw.pop('property_type_raw_source')
    assert RawListing(**raw).property_type_raw_source == 'PORTAL_TYPE'
    data = asdict(make_normalised())
    for key in FIELDS:
        if key != 'property_type':
            data.pop(key)
    old = NormalisedListing(**data)
    assert old.property_type_status == 'LEGACY_UNREVIEWED'
    assert old.property_type_version is None


@pytest.mark.parametrize('parser_name,fixture,url,raw_type,source', [
    ('propertypro', 'propertypro_listing_page.html', 'https://propertypro.ng/property/test-7NUGY',
     'Flat Apartment for rent in Ikoyi', 'BREADCRUMB'),
    ('privateproperty', 'privateproperty_listing_page.html', 'https://privateproperty.ng/listings/test-6PBUWY',
     'Commercial Property', 'PORTAL_TYPE'),
    ('nigeriapropertycentre', 'nigeriapropertycentre_listing_page.html',
     'https://nigeriapropertycentre.com/for-sale/3370211-test', 'Semi-detached', 'PORTAL_TYPE'),
])
def test_primary_portal_labels_are_preserved(parser_name, fixture, url, raw_type, source):
    from scraper.parsers.propertypro import PropertyProParser
    from scraper.parsers.privateproperty import PrivatePropertyParser
    from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
    parser = dict(propertypro=PropertyProParser, privateproperty=PrivatePropertyParser,
                  nigeriapropertycentre=NigeriaPropertyCentreParser)[parser_name]({}, load_robots=False)
    raw = parser.parse_listing(load_fixture(fixture), url)
    assert raw.property_type_raw == raw_type
    result = normalise(raw)
    assert result.property_type_raw == raw_type
    assert result.property_type_raw_source == source
    if parser_name == 'nigeriapropertycentre':
        assert result.property_type == 'SEMI_DETACHED_DUPLEX'
