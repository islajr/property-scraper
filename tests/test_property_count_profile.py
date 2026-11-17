"""Count-profile boundaries; candidates are never trusted storage values."""
import pytest
from scraper.property_count_profile import profile_text,DESCRIPTION_LIMIT


def mentions(result,entity):
    return [c for c in result['candidates'] if c['entity']==entity]


@pytest.mark.parametrize('word,value', [('one',1),('three',3),('fourteen',14),
                                      ('twenty-one',21),('ninety nine',99),('140',140)])
def test_explicit_asset_quantities(word,value):
    result=profile_text(f'{word} detached duplexes sold together')
    candidate=mentions(result,'DWELLING_UNIT')[0]
    assert candidate['quantity']==dict(kind='EXACT',minimum=value,maximum=value)
    assert 'BUNDLE' in candidate['relation_hints']


def test_bedrooms_and_offered_units_are_separate_without_derived_totals():
    result=profile_text('Four three-bedroom flats, all sold together')
    assert [c['quantity']['minimum'] for c in mentions(result,'BEDROOM')]==[3]
    assert [c['quantity']['minimum'] for c in mentions(result,'DWELLING_UNIT')]==[4]
    assert all(c['quantity']['minimum']!=12 for c in result['candidates'])


def test_bedroom_number_is_not_a_house_quantity_or_a_separate_room():
    result=profile_text('3bed Room Flat')
    assert len(mentions(result,'BEDROOM'))==1
    assert not mentions(result,'ROOM') and not mentions(result,'DWELLING_UNIT')
    assert not mentions(profile_text('A three-bedroom house'),'DWELLING_UNIT')


def test_one_building_can_contain_multiple_units_without_becoming_five_assets():
    result=profile_text('One block containing four flats')
    assert mentions(result,'BUILDING')[0]['quantity']['minimum']==1
    flats=mentions(result,'DWELLING_UNIT')[0]
    assert flats['quantity']['minimum']==4
    assert flats['relation_hints']==['CONTAINED_UNITS']


@pytest.mark.parametrize('phrase,kind,low,high', [
    ('4-6 flats','RANGE',4,6),('four to six flats','RANGE',4,6),
    ('at least four flats','AT_LEAST',4,None),('minimum of 12 apartments','AT_LEAST',12,None),
])
def test_ranges_and_lower_bounds_are_not_exact_values(phrase,kind,low,high):
    candidate=mentions(profile_text(phrase),'DWELLING_UNIT')[0]
    assert candidate['quantity']==dict(kind=kind,minimum=low,maximum=high)


def test_reverse_ranges_are_preserved_and_flagged_not_silently_reordered():
    candidate=mentions(profile_text('6-4 flats'),'DWELLING_UNIT')[0]
    assert candidate['quantity']['minimum']==6
    assert 'REVERSED_RANGE' in candidate['review_flags']


def test_bare_types_and_ensuite_claims_do_not_supply_default_counts():
    for text in ['House for sale','Room available','All rooms ensuite','Several flats']:
        result=profile_text(text)
        assert result['state']=='NO_PATTERN_MATCH' and result['candidates']==[]


def test_offer_alternatives_and_availability_are_not_fixed_bundles():
    result=profile_text('Four flats available individually or together')
    assert result['state']=='OFFER_ALTERNATIVES'
    assert 'AVAILABILITY' in mentions(result,'DWELLING_UNIT')[0]['relation_hints']
    result=profile_text('Four flats', 'Price per unit: 60m. All units: 200m.')
    assert result['state']=='OFFER_ALTERNATIVES'
    result=profile_text('Six apartments available in the development')
    assert result['state']=='COUNT_CANDIDATES'
    assert mentions(result,'DWELLING_UNIT')[0]['relation_hints']==['AVAILABILITY']


def test_conflicting_sources_are_only_a_review_flag():
    result=profile_text('Three bedroom flat','Four bedroom apartment')
    assert result['state']=='POSSIBLE_CONFLICT'
    assert result['possible_conflict_entities']==['BEDROOM']
    assert {c['quantity']['minimum'] for c in result['candidates']}=={3,4}


def test_landmarks_and_ancillary_room_counts_are_preserved_as_flagged_evidence():
    result=profile_text('Near two buildings', 'House and two rooms BQ')
    assert 'POSSIBLY_NONPRIMARY_CONTEXT' in mentions(result,'BUILDING')[0]['review_flags']
    assert 'POSSIBLY_ANCILLARY_BQ' in mentions(result,'ROOM')[0]['review_flags']


def test_furniture_beds_do_not_become_verified_bedroom_counts():
    candidate=mentions(profile_text('Two beds in a room'),'BEDROOM_SHORTHAND')[0]
    assert candidate['review_flags']==['BED_SHORTHAND_REQUIRES_CONTEXT']


def test_exact_source_offsets_and_independent_duplicate_sources_are_kept():
    title='Newly built: 4 flats'
    description='For sale: four flats'
    result=profile_text(title,description)
    assert len(result['candidates'])==2
    for c in result['candidates']:
        original=title if c['source']=='TITLE' else description
        assert original[c['start']:c['end']]==c['text']


def test_truncation_is_visible_even_when_no_pattern_matches():
    result=profile_text(description='x'*(DESCRIPTION_LIMIT+1))
    assert result['truncated']==['DESCRIPTION'] and result['requires_review']
    assert result['state']=='NO_PATTERN_MATCH'


def test_zero_assets_are_flagged_without_rejecting_source_text():
    result=profile_text('Zero flats')
    assert 'ZERO_ASSET_OR_UNRESOLVED_COUNT' in mentions(result,'DWELLING_UNIT')[0]['review_flags']


def test_report_candidate_limit_keeps_primary_title_and_marks_truncation():
    result=profile_text('Three flats',description='One flat. '*200)
    assert result['candidates'][0]['source']=='TITLE'
    assert 'CANDIDATE_LIMIT' in result['truncated']


def test_prices_do_not_spill_into_following_property_counts():
    result=profile_text(description='1 Bedroom Apartment: ₦150,000,000- 2 Bedroom Apartment')
    assert [c['quantity']['minimum'] for c in mentions(result,'BEDROOM')]==[1,2]
    assert not mentions(result,'DWELLING_UNIT')
    assert all(c['quantity']['kind']=='EXACT' for c in result['candidates'])


def test_grouped_and_attached_numbers_remain_count_mentions():
    result=profile_text('1,234 apartments and 5units')
    assert mentions(result,'DWELLING_UNIT')[0]['quantity']['minimum']==1234
    assert mentions(result,'UNSPECIFIED_UNIT')[0]['quantity']['minimum']==5


def test_mixed_layout_notation_is_not_multiplied_into_a_bedroom_total():
    result=profile_text(description='2 separate buildings: 4 × 3-Bedroom Flats; 4 × 2-Bedroom Flats; 6 × Mini-Flats')
    assert mentions(result,'BUILDING')[0]['quantity']['minimum']==2
    assert [c['quantity']['minimum'] for c in mentions(result,'DWELLING_UNIT')]==[4,4,6]
    assert [c['quantity']['minimum'] for c in mentions(result,'BEDROOM')]==[3,2]


def test_each_bedroom_count_does_not_relabel_unit_count_as_per_dwelling():
    result=profile_text('Block of 4 flats, 3 bedrooms each')
    assert mentions(result,'DWELLING_UNIT')[0]['relation_hints']==['CONTAINED_UNITS']
    assert 'PER_DWELLING' in mentions(result,'BEDROOM')[0]['relation_hints']


def test_cli_connection_errors_never_print_connection_details(monkeypatch,capsys,tmp_path):
    import psycopg2
    from scripts.profile_property_counts import main
    monkeypatch.setenv('DATABASE_URL','postgresql://private-password@example.invalid/db')
    def fail(*args,**kwargs):
        raise psycopg2.OperationalError('private-password example.invalid')
    monkeypatch.setattr(psycopg2,'connect',fail)
    assert main(['--output',str(tmp_path/'profile.jsonl')])==1
    output=capsys.readouterr()
    assert 'connection details suppressed' in output.err
    assert 'private-password' not in output.err+output.out
    assert not (tmp_path/'profile.jsonl').exists()
