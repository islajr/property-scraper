"""Accepted 16 November review decisions and contrasting asset evidence."""
import pytest
from scraper.property_types import classify
from scraper.normaliser import normalise
from tests.conftest import make_raw


@pytest.mark.parametrize('title,description,expected', [
    ('4bed Massionette+bq..', None, 'MAISONETTE'),  # review R06 / listing 57
    ('Executive Newly Built Roomself Contain', None, 'SELF_CONTAINED'),  # R08 / 3346
    ('For rent: Newly Renovated Of 3bed Room Flat', None, 'FLAT_APARTMENT'),  # R09 / 1666
    ('2 Bedroom All Rooms Ensuite Flat (upstairs)', None, 'FLAT_APARTMENT'),  # R10 / 4472
    ('For rent: Newly Renovated 4 Bedroom Semi Detached Duplex + Office + 2 Bq',
     'NEWLY RENOVATED 4-BEDROOM SEMI-DETACHED DUPLEX + OFFICE + 2 BQ. '
     'Newly renovated semi-detached duplex with a dedicated office space and 2 boys’ quarters.',
     'SEMI_DETACHED_DUPLEX'),  # R11 / 855; shortened identifying statements
    ('5 Bed Self Compound ,cinema , Pool , Snooker , Lekki',
     'Luxury 5 Bedroom Duplex\nFeatures:\nPrivate Cinema\nPrivate Swimming Pool',
     'DUPLEX'),  # R12 / 16313; shortened identity/features, no inferred form
])
def test_accepted_review_interpretations(title, description, expected):
    result = classify(title=title, description=description)
    assert result.property_type == expected
    assert result.property_type_status == 'CLASSIFIED'


@pytest.mark.parametrize('text,expected', [
    ('Massionette', 'MAISONETTE'), ('Massionettes', 'MAISONETTE'),
    ('Aroomself con', 'SELF_CONTAINED'), ('Roomself', 'SELF_CONTAINED'),
    ('3 bed room flat', 'FLAT_APARTMENT'), ('Luxury 3bed Rooms Flat', 'FLAT_APARTMENT'),
    ('2 bedroom all rooms en-suite flat', 'FLAT_APARTMENT'),
    ('3 bedroom duplex + home office', 'DUPLEX'),
    ('3 bedroom duplex + private cinema', 'DUPLEX'),
])
def test_bounded_variants(text, expected):
    assert classify(title=text).property_type == expected


@pytest.mark.parametrize('title', ['Massionetteville', 'Roomselfish', 'Aroomselfcontainedness'])
def test_aliases_have_word_boundaries(title):
    assert classify(title=title).property_type is None


@pytest.mark.parametrize('description,expected', [
    ('Massionette for sale', 'MAISONETTE'),
    ('Roomself contain for rent', 'SELF_CONTAINED'),
    ('Luxury 2bed Room Flat with private kitchen', 'FLAT_APARTMENT'),
])
def test_accepted_wording_in_leading_description_identity(description, expected):
    assert classify(title='Property available', description=description).property_type == expected


@pytest.mark.parametrize('title,expected', [
    ('A room for rent in a flat', 'ROOM'),
    ('All rooms ensuite for rent', 'ROOM'),
    ('Home office for rent', 'OFFICE'),
    ('Dedicated office space for rent', 'OFFICE'),
])
def test_independently_offered_rooms_and_offices_remain_assets(title, expected):
    assert classify(title=title).property_type == expected


@pytest.mark.parametrize('raw,title,description', [
    (None, 'Duplex and standalone office for rent', 'Luxury duplex with a dedicated office.'),
    (None, 'Duplex + Office for rent', 'Luxury duplex with a dedicated office.'),
    (None, 'Duplex + Cinema for sale', 'Luxury duplex with a private cinema.'),
    ('Office', 'Duplex + home office', None),
    ('Cinema', 'Duplex + private cinema', None),
    (None, 'Duplex + Office + BQ', 'Office building for sale. A duplex is also available.'),
    (None, 'Flat + Office', 'Luxury duplex with a dedicated office.'),
])
def test_separate_or_conflicting_assets_are_not_suppressed(raw, title, description):
    result = classify(raw, title, description)
    assert result.property_type is None
    assert result.property_type_status == 'AMBIGUOUS'


def test_standalone_cinema_remains_unsupported_even_with_home_description():
    result = classify(title='Private cinema for sale', description='Luxury duplex with private cinema.')
    assert result.property_type is None
    assert result.property_type_status == 'UNSUPPORTED'


def test_no_house_form_is_guessed_from_bedrooms_and_cinema():
    result = classify(title='5 bed self compound, private cinema, pool')
    assert result.property_type is None


def test_context_correction_does_not_certify_an_unclear_whole_building_offer():
    result = classify(title='2bed Room Blocks Of Flat',
                      description='3bed room blocks of flat, first floor available.')
    assert result.property_type is None
    assert result.property_type_status == 'AMBIGUOUS'
    assert result.property_type_evidence['candidates'] == ['BLOCK_OF_FLATS', 'SCOPE_UNRESOLVED']


def test_home_office_description_support_is_preserved_and_negation_is_respected():
    title = 'Semi Detached Duplex + Office + BQ'
    result = classify(title=title, description='Luxury duplex with a dedicated office.')
    assert result.property_type == 'SEMI_DETACHED_DUPLEX'
    assert any(m['source'] == 'DESCRIPTION' and m['text'] == 'dedicated office'
               and m['rule'] == 'context:office_support'
               for m in result.property_type_evidence['matches'])
    result = classify(title=title, description='Luxury duplex with no dedicated office.')
    assert result.property_type_status == 'AMBIGUOUS'


def test_other_agent_inventory_cannot_corroborate_a_home_amenity():
    result = classify(title='Duplex + Office', description=(
        'Luxury duplex for rent. Other properties: another home with a dedicated office.'))
    assert result.property_type_status == 'AMBIGUOUS'


@pytest.mark.parametrize('title,rule', [
    ('3bed Room Flat', 'context:bedroom_wording'),
    ('All Rooms Ensuite Flat', 'context:ensuite_rooms'),
    ('Duplex + home office', 'context:home_office'),
    ('Duplex + private cinema', 'context:private_cinema'),
])
def test_excluded_asset_keywords_keep_exact_evidence(title, rule):
    result = classify(title=title)
    matches = result.property_type_evidence['matches']
    assert any(m['rule'] == rule and m['text'] in title and m['source'] == 'TITLE'
               for m in matches)


@pytest.mark.parametrize('title,raw_bedrooms,expected', [
    ('Flat, all rooms ensuite', None, None),
    ('3bed Room Flat', '3 bedrooms', 3),
    ('Duplex + home office + private cinema', None, None),
])
def test_type_context_rules_do_not_invent_or_increase_bedrooms(title, raw_bedrooms, expected):
    result = normalise(make_raw(title=title, property_type_raw=None, description=None,
                                raw_bedrooms=raw_bedrooms))
    assert result.bedrooms == expected
