"""Preservation and correction are separate from evidence extraction."""
from types import SimpleNamespace
import pytest
from scraper.room_count_store import proposal


def row(**overrides):
    return dict(source='test',external_id='1',title='3 bedroom flat',description=None,
        property_type_raw=None,property_type='FLAT_APARTMENT',property_asset_scope='UNIT',
        property_category='RESIDENTIAL',property_type_family='APARTMENT',bedrooms=3,bathrooms=3,
        raw_bedrooms=None,raw_bathrooms=None,room_metric_sources={},**overrides)


@pytest.mark.parametrize('title,category,bedrooms,bathrooms',[
    ('3 bedroom flat','RESIDENTIAL',3,3),
    ('3 bedroom flat','RESIDENTIAL',1234,123),
    ('2 or 3 bedroom flats','RESIDENTIAL',2,4),
    ('500sqm land','LAND',1234,123),
    ('62 bedroom hotel','COMMERCIAL',62,65),
])
def test_backfill_never_replaces_or_clears_an_existing_number(title,category,bedrooms,bathrooms):
    before=row();before.update(title=title,property_category=category,bedrooms=bedrooms,bathrooms=bathrooms)
    after=proposal(before)
    assert (after['bedrooms'],after['bathrooms'])==(bedrooms,bathrooms)
    for field in ('bedrooms','bathrooms'):
        assert after['room_count_data'][field]['stored_value']==before[field]
        assert after['room_count_data'][field]['storage_action']=='PRESERVED'


def test_unlabelled_new_numbers_cannot_replace_existing_values():
    before=row()
    observed=SimpleNamespace(raw_bedrooms='3',raw_bathrooms='5',room_metric_sources={})
    after=proposal(before,listing=observed)
    assert (after['bedrooms'],after['bathrooms'])==(3,3)
    assert after['room_count_data']['bathrooms']['status']=='UNVERIFIED'


def test_a_clear_primary_metric_corrects_only_its_own_field():
    before=row()
    observed=SimpleNamespace(raw_bedrooms=None,raw_bathrooms='5',room_metric_sources={'bathrooms':'PRIMARY_LABEL'})
    after=proposal(before,listing=observed)
    assert (after['bedrooms'],after['bathrooms'])==(3,5)
    assert after['room_count_data']['bathrooms']['storage_action']=='CORRECTED_FROM_PRIMARY_METRIC'
    assert after['room_count_data']['bedrooms']['storage_action']=='PRESERVED'


def test_conflicting_new_metrics_cannot_overwrite_existing_values():
    before=row()
    observed=SimpleNamespace(raw_bedrooms='4 Bedrooms',raw_bathrooms='2 Baths | 5 Baths',room_metric_sources={})
    after=proposal(before,listing=observed)
    assert (after['bedrooms'],after['bathrooms'])==(3,3)
    assert all(after['room_count_data'][field]['status']=='UNVERIFIED' for field in ('bedrooms','bathrooms'))


def test_missing_value_can_be_filled_from_explicit_evidence_without_replacing_other_numbers():
    before=row();before.update(bedrooms=None)
    after=proposal(before)
    assert (after['bedrooms'],after['bathrooms'])==(3,3)
    assert after['room_count_data']['bedrooms']['storage_action']=='FILLED_FROM_EVIDENCE'
    assert after['room_count_data']['bathrooms']['status']=='UNVERIFIED'


@pytest.mark.parametrize('bedrooms,bathrooms,code',[
    (1234,123,'POSSIBLE_CONCATENATED_DIGITS'),(100,2,'ROOM_COUNT_100_PLUS'),
    (24,2,'ROOM_COUNT_OVER_20'),(-1,2,'NEGATIVE_ROOM_COUNT'),(0,2,'ZERO_REQUIRES_CONTEXT'),
    (1,12,'UNUSUAL_ROOM_RATIO'),
])
def test_eccentric_stored_counts_get_explicit_review_flags_without_being_changed(bedrooms,bathrooms,code):
    before=row();before.update(bedrooms=bedrooms,bathrooms=bathrooms)
    after=proposal(before)
    assert (after['bedrooms'],after['bathrooms'])==(bedrooms,bathrooms)
    assert code in {f['code'] for f in after['room_count_data']['review_flags']}
    assert after['room_count_data']['review_priority']<3


def test_large_hotel_count_is_reviewed_in_whole_asset_context_and_not_declared_wrong():
    before=row();before.update(title='120 bedroom hotel',bedrooms=120,bathrooms=120,
        property_type='HOTEL',property_category='COMMERCIAL',property_asset_scope='WHOLE_BUILDING')
    after=proposal(before)
    assert after['bedrooms']==120
    assert after['room_count_data']['review_priority']==0
    assert all(f['asset_context']=='WHOLE_ASSET_OR_MULTIPLE_UNITS' for f in after['room_count_data']['review_flags'])


def test_equal_ordinary_counts_are_not_an_outlier_flag():
    after=proposal(row())
    assert after['room_count_data']['review_flags']==[]
    assert after['room_count_data']['review_priority']==3
