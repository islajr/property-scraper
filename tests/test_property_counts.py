import pytest
from scraper.property_counts import assess_counts,source_hash


def accepted(title,description=None):
    return [o for o in assess_counts(title,description)['observations'] if o['decision']=='ACCEPT']


@pytest.mark.parametrize('text,entity,relationship,value',[
    ('Three detached duplexes sold together','DWELLING_UNIT','OFFERED_ASSET',3),
    ('One room in a shared apartment','ROOM','OFFERED_ASSET',1),
    ('One block containing four flats','BUILDING','OFFERED_ASSET',1),
    ('One block containing four flats','DWELLING_UNIT','CONTAINED_UNIT',4),
    ('Four three-bedroom flats, all sold together','DWELLING_UNIT','OFFERED_ASSET',4),
    ('Four three-bedroom flats, all sold together','BEDROOM','BEDROOMS_PER_DWELLING',3),
    ('Six apartments available in the development','DWELLING_UNIT','DEVELOPMENT_AVAILABILITY',6),
])
def test_explicit_accepted_semantics(text,entity,relationship,value):
    assert any(o['entity']==entity and o['relationship']==relationship and o['quantity']['minimum']==value for o in accepted(text))


@pytest.mark.parametrize('text',[
    'House for sale','Room available','All rooms ensuite','Zero flats sold together',
    '4-6 flats sold together','Near three duplexes sold together',
    'Four flats available individually or together', '1234 bedroom flat',
    'House with one room BQ','Two buildings containing fourteen residential units in total',
])
def test_no_defaults_or_unsupported_relationships(text):
    assert accepted(text)==[]
    assert assess_counts(text)['questions']


def test_missing_offered_quantity_remains_a_question_even_with_bedrooms():
    result=assess_counts('A three-bedroom house')
    assert len(accepted('A three-bedroom house'))==1
    assert result['questions'][0]['reason']=='offered_quantity_unestablished'
    assert result['state']=='REVIEW_REQUIRED'


def test_conflicts_and_mixed_layouts_are_not_summed_or_given_one_parent():
    assert accepted('3 bedroom flat','4 bedroom apartment')==[]
    assert accepted('Four 3-bedroom flats and two 2-bedroom flats')==[]
    assert not assess_counts('Four 3-bedroom flats and two 2-bedroom flats')['derived_totals']


def test_matching_sources_merge_evidence_instead_of_adding_quantities():
    observations=accepted('Three bedroom flat','Three bedroom apartment')
    assert len(observations)==1 and len(observations[0]['evidence'])==2
    assert observations[0]['quantity']['minimum']==3


def test_later_agent_inventory_is_held():
    assert accepted('Property available','Other properties: '+'x'*510+' three houses sold together')==[]


def test_relationship_qualifiers_and_exact_offsets_are_preserved():
    title='Three detached duplexes sold together'
    o=accepted(title)[0]
    evidence=o['evidence'][0]
    assert 'sold together' in evidence['text']
    assert title[evidence['start']:evidence['end']]==evidence['text']
    assert title[evidence['count_start']:evidence['count_end']]==evidence['count_text']


def test_mixed_asset_portfolio_does_not_gain_one_unqualified_bedroom_parent():
    result=assess_counts('Five houses and four three-bedroom flats sold together')
    assert all(o['decision']=='HOLD' for o in result['observations']
               if o['relationship']=='BEDROOMS_PER_DWELLING')


def test_bedroom_count_is_not_an_offered_asset_count():
    assert not any(o['relationship']=='OFFERED_ASSET' for o in accepted('12 bedroom detached duplex'))
    assert accepted('Beautiful One Room Self Contained')==[]
    assert not any(o['relationship']=='OFFERED_ASSET' for o in accepted(
        'For sale: Standard 1 Unit Of 2bedroom Flat 1 Unit Of Miniflat On A Full Plot'))
    assert accepted('Ninety-one-bedroom houses sold together')==[]


@pytest.mark.parametrize('title',[
    'One Room And Parlor','Executive 1 Room & Parlour Apartment',
    'For Sale 2 Bedroom Flat&1 Unit Of Mini Flat',
    '4 Nos of 2bedrooms Flats, 1 4bedroom Flats, a Mini Flats',
    'Three houses and three flats sold together',
])
def test_layout_counts_and_portfolio_components_are_not_one_primary_offer(title):
    assert not any(o['relationship']=='OFFERED_ASSET' for o in accepted(title))


def test_source_hash_distinguishes_framing_and_handles_unicode_and_nulls():
    assert source_hash(None,None)==source_hash('','')
    assert source_hash('a','bc')!=source_hash('ab','c')
    assert len(source_hash('₦三','😀'))==64
