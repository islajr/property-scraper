from pathlib import Path
from bs4 import BeautifulSoup
import pytest
from scraper.room_counts import assess,source_hash
from scraper.normaliser import normalise,parse_integer
from scraper.parsers.room_metrics import extract_room_metrics
from tests.conftest import make_raw


def row(**kwargs):
    return dict(source='test',external_id='1',title='3 bedroom flat',description='',property_type='FLAT_APARTMENT',
        property_category='RESIDENTIAL',property_type_family='APARTMENT',property_asset_scope='UNIT',**kwargs)


def test_primary_bedroom_bathroom_and_toilet_roles_are_distinct_and_order_independent():
    soup=BeautifulSoup('''<div class="property-contact-block"><div class="property-pros"><ul>
    <li>9 Toilets</li><li>5 Baths</li><li>3 Beds</li></ul></div></div>
    <aside><li>99 Bedrooms</li><li>88 Bathrooms</li></aside>''','html.parser')
    values,sources=extract_room_metrics(soup,'propertypro')
    assert values=={'bedrooms':'3 Beds','bathrooms':'5 Baths'}
    assert sources==dict(bedrooms='PRIMARY_LABEL',bathrooms='PRIMARY_LABEL')
    soup.select_one('.property-pros li:nth-of-type(2)').decompose()
    assert extract_room_metrics(soup,'propertypro')[0]['bathrooms'] is None


def test_privateproperty_svg_roles_survive_reordering_and_different_counts():
    soup=BeautifulSoup(Path('tests/fixtures/privateproperty_listing_page.html').read_text(),'html.parser')
    items=soup.select('.property-info .property-benefit>li')
    for item,value in zip(items,[3,5,9]):
        for text in list(item.find_all(string=True,recursive=False)):text.extract()
        item.append(str(value))
    parent=items[0].parent
    for item in reversed(items):parent.append(item.extract())
    values,_=extract_room_metrics(soup,'privateproperty')
    assert values==dict(bedrooms='3',bathrooms='5')
    items[1].select_one('path')['d']='unknown-new-icon'
    assert extract_room_metrics(soup,'privateproperty')[0]['bathrooms'] is None


def test_npc_metrics_from_old_schema_and_new_cards():
    for fixture,bed,bath in [('nigeriapropertycentre_listing.html','2','2'),('nigeriapropertycentre_listing_page.html','4','4')]:
        soup=BeautifulSoup(Path('tests/fixtures',fixture).read_text(),'html.parser')
        values,_=extract_room_metrics(soup,'nigeriapropertycentre')
        assert values==dict(bedrooms=bed,bathrooms=bath)


@pytest.mark.parametrize('text',['1 2 3 4 Beds','3 Beds 5 Baths','3-4 bedrooms','-2 bathrooms','3.5 baths','Phone 08012345678'])
def test_integer_parser_does_not_extract_one_number_from_mixed_context(text):
    assert parse_integer(text) is None


def test_invalid_primary_values_do_not_hide_supported_bedroom_evidence():
    r=row(raw_bedrooms='1234 Beds',raw_bathrooms='123 Baths',room_metric_sources=dict(bedrooms='PRIMARY_LABEL',bathrooms='PRIMARY_LABEL'))
    a=assess(r)
    assert a['bedrooms']['value']==3 and a['bedrooms']['warnings']
    assert a['bathrooms']['value'] is None and a['bathrooms']['status']=='REVIEW_REQUIRED'


def test_genuinely_conflicting_bedroom_claims_are_not_arbitrarily_ranked():
    r=row(raw_bedrooms='4 Bedrooms')
    a=assess(r)
    assert a['bedrooms']['value'] is None and a['bedrooms']['status']=='AMBIGUOUS'
    assert {c['value'] for c in a['bedrooms']['claims'] if c['usable']}=={3,4}


def test_bathrooms_do_not_come_from_bedrooms_ensuite_or_toilets():
    for description in ('All three rooms ensuite. Four guest toilets.','3 toilets','Six rooms with showers'):
        r=row();r['description']=description
        assert assess(r)['bathrooms']['value'] is None


@pytest.mark.parametrize('text',['2 bathrooms','Two bathrooms','2bathrooms'])
def test_explicit_bathroom_text(text):
    r=row();r['description']=text
    assert assess(r)['bathrooms']['value']==2


@pytest.mark.parametrize('text',['3-4 bathrooms','1 2 3 baths','At least four bathrooms','Near a house with 3 bathrooms','2 bathrooms in the BQ'])
def test_ambiguous_or_non_primary_bathroom_text_remains_unresolved(text):
    r=row();r['description']=text
    assert assess(r)['bathrooms']['value'] is None


def test_mixed_units_need_per_unit_bathroom_evidence():
    r=row(raw_bathrooms='4 Bathrooms');r['property_asset_scope']='MULTIPLE_UNITS'
    assert assess(r)['bathrooms']['value'] is None
    r['description']='2 bathrooms in each flat'
    assert assess(r)['bathrooms']['value']==2


def test_normalisation_preserves_raw_fields_and_room_provenance():
    listing=normalise(make_raw(raw_bedrooms='3 Bedrooms',raw_bathrooms='5 Baths'))
    assert (listing.bedrooms,listing.bathrooms)==(3,5)
    assert listing.raw_bathrooms=='5 Baths'
    assert listing.room_counts['bathrooms']['status']=='KNOWN'


def test_source_hash_covers_raw_metrics_and_identity_and_distinguishes_missing():
    r=row(raw_bedrooms=None,room_metric_sources={})
    before=source_hash(r)
    for key,value in [('raw_bedrooms',''),('raw_bathrooms','2'),('property_type','HOUSE'),('external_id','2')]:
        assert source_hash({**r,key:value})!=before
