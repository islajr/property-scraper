from decimal import Decimal
import pytest
from bs4 import BeautifulSoup
from scraper.area_measurements import assess
from scraper.area_store import proposal
from scraper.normaliser import normalise
from scraper.parsers.area_metrics import extract_area_metrics
from tests.conftest import make_raw


def row(**kwargs):
    return {**dict(source='test',external_id='1',title='',description='',property_type='HOUSE',
                property_category='RESIDENTIAL',property_asset_scope='UNIT'),**kwargs}


@pytest.mark.parametrize('text,value',[
 ('Floor area: 2,700 sqft','250.84'),('Floor area: 250 m²','250.00'),
 ('Floor area: 250 sq.m','250.00'),('Floor area: 250 square metres','250.00'),
 ('Floor area: 250 m2','250.00')])
def test_converts_explicit_floor_units(text,value):
    a=assess(row(description=text));assert a['floor_area_sqm']['value']==value


def test_land_and_floor_are_separate_and_generic_area_is_retained():
    a=assess(row(description='Land size: 600sqm. Floor area: 240sqm.'))
    assert a['floor_area_sqm']['value']=='240.00' and a['land_area_sqm']['value']=='600.00'
    a=assess(row(title='Luxury house 500sqm'))
    assert a['floor_area_sqm']['value'] is None and a['land_area_sqm']['value'] is None
    assert a['claims'][0]['role']=='UNSPECIFIED' and a['claims'][0]['sqm']=='5E+2'


@pytest.mark.parametrize('text',[
 'Land area: 500-600sqm','Land area: 500sqm to 600sqm','Land area: between 500sqm and 600sqm',
 'Land area: -500sqm','Land area: 0sqm','Land area: 12,34sqm','Land price ₦50,000/sqm',
 'Land area: over 500sqm','We also have land area: 500sqm',
 'Land area: not 500sqm','Land area: 999999999999999999999999999999999sqm',
 'Pool size: 500sqm','Land area: 500sqm per plot',
])
def test_held_claims_never_populate_asset_area(text):
    data=row(description=text);data['property_category']='LAND';data['property_asset_scope']='MULTIPLE_UNITS'
    a=assess(data);assert a['floor_area_sqm']['value'] is None and a['land_area_sqm']['value'] is None


def test_land_category_can_identify_role_but_not_shared_apartment_site():
    data=row(title='600sqm land');data['property_category']='LAND'
    assert assess(data)['land_area_sqm']['value']=='600.00'
    data=row(title='Apartment on 600sqm');data['property_type_family']='APARTMENT'
    assert assess(data)['land_area_sqm']['value'] is None


def test_hectares_acres_conflicts_and_approximate_precision():
    data=row(title='Land area: 1 hectare');data['property_category']='LAND'
    assert assess(data)['land_area_sqm']['value']=='10000.00'
    data['title']='Land area: 1 acre';a=assess(data)
    assert Decimal(a['claims'][0]['sqm'])==Decimal('4046.8564224')
    assert a['land_area_sqm']['value']=='4046.86'
    data.update(title='Land area: 500sqm',description='Land area: 600sqm')
    assert assess(data)['land_area_sqm']['status']=='AMBIGUOUS'
    a=assess(row(description='Floor area: about 500sqm'))
    assert a['claims'][0]['precision']=='APPROXIMATE'


def test_preserve_unsupported_existing_area_and_first_legacy():
    data=row(title='Land area: 600sqm');data.update(floor_area_sqm=150,floor_area_source='PORTAL',area_legacy=None)
    a=proposal(data)
    assert a['floor_area_sqm']=='150' and a['land_area_sqm']=='600.00'
    assert a['area_data']['floor_area_sqm']['status']=='UNVERIFIED'
    assert a['area_legacy']['floor_area_sqm']==150
    assert proposal({**data,**a})==a


def test_normaliser_reads_title_description_and_explicit_floor_field():
    item=normalise(make_raw(raw_floor_area=None,title='House on 600sqm',description='Floor area: 250 sqm'))
    assert item.floor_area_sqm==250 and item.land_area_sqm==600
    item=normalise(make_raw(raw_floor_area='2700 sqft'))
    assert item.floor_area_sqm==250.84


def test_primary_area_widgets_exclude_related_cards_and_keep_generic_role():
    soup=BeautifulSoup('''<div class="property-pricing"><div class="property-pros"><ul>
      <li><span data-tooltip="Size"><strong>500 sqm</strong></span></li>
      <li>Floor area: 120 sqm</li></ul></div></div>
      <aside><li>Floor area: 999 sqm</li></aside>''','html.parser')
    fields=extract_area_metrics(soup,'propertypro')
    assert len(fields)==2 and fields[0]['role']=='UNSPECIFIED'
    a=assess({**row(), 'raw_area_fields':fields})
    assert a['floor_area_sqm']['value']=='120.00'


def test_old_pagewide_size_does_not_certify_floor_or_land():
    a=assess({**row(), 'raw_area_fields':[dict(role='FLOOR',label='Floor area',value='120sqm',source='LEGACY_UNSCOPED_FIELD')]})
    assert a['floor_area_sqm']['value'] is None


def test_measuring_does_not_mean_land_and_multi_floor_inventory_is_held():
    a=assess(row(title='Office space measuring 660sqm'))
    assert a['land_area_sqm']['value'] is None
    a=assess(row(description='Available Spaces9th Floor: 662sqm (Entire Floor)3rd Floor: 235sqmRent $200 per sqm'))
    assert a['floor_area_sqm']['value'] is None
    assert {c['rounded_sqm'] for c in a['claims']}=={'662.00','235.00'}
    assert assess(row(description='Total lettable space: 660sqm'))['floor_area_sqm']['value']=='660.00'
