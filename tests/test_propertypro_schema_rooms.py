import json
import pytest
from bs4 import BeautifulSoup
from scraper.parsers.room_metrics import extract_room_metrics
from scraper.room_counts import assess
from tests.conftest import load_fixture

URL='https://propertypro.ng/property/example-ABC12'


def page(*,bedrooms=3,bathrooms=2,name='Primary advert',listing_url=URL,canonical=URL):
    nodes=[dict(**{'@type':'RealEstateListing'},url=listing_url,name='Primary advert'),
           dict(**{'@type':'SingleFamilyResidence'},name=name,numberOfBedrooms=bedrooms,numberOfBathroomsTotal=bathrooms),
           dict(**{'@type':'SingleFamilyResidence'},name='Related advert',numberOfBedrooms=9,numberOfBathroomsTotal=8)]
    return BeautifulSoup('<link rel="canonical" href="'+canonical+'"><script type="application/ld+json">'+json.dumps({'@graph':nodes})+'</script>','html.parser')


def test_positive_primary_schema_counts_without_old_widgets():
    values,sources=extract_room_metrics(page(),'propertypro')
    assert values==dict(bedrooms='3',bathrooms='2')
    assert sources==dict(bedrooms='PRIMARY_SCHEMA_PROPERTY',bathrooms='PRIMARY_SCHEMA_PROPERTY')


@pytest.mark.parametrize('changes',[
 dict(bedrooms=0,bathrooms=0),dict(name='Unrelated name'),dict(listing_url=URL+'other'),
 dict(canonical='https://other.example/property/example-ABC12'),dict(bedrooms=True,bathrooms=False),
 dict(bedrooms='three',bathrooms='2 bathrooms'),
])
def test_defaults_unmatched_identity_and_invalid_values_are_not_metrics(changes):
    values,sources=extract_room_metrics(page(**changes),'propertypro')
    assert values==dict(bedrooms=None,bathrooms=None) and sources=={}


def test_schema_and_widget_disagreement_is_retained_as_conflict():
    soup=page();soup.append(BeautifulSoup('<div class="property-pricing"><div class="property-pros"><ul><li>4 bedrooms</li></ul></div></div>','html.parser'))
    values,sources=extract_room_metrics(soup,'propertypro')
    assert values['bedrooms']=='4 bedrooms | 3'
    a=assess(dict(source='propertypro',external_id='ABC12',title='House',property_category='RESIDENTIAL',
       property_type='HOUSE',property_type_family='HOUSE',property_asset_scope='UNIT',raw_bedrooms=values['bedrooms'],
       raw_bathrooms=values['bathrooms'],room_metric_sources=sources))
    assert a['bedrooms']['status']=='AMBIGUOUS' and a['bedrooms']['value'] is None


def test_saved_real_portal_schema_recovers_positive_primary_counts():
    soup=load_fixture('propertypro_listing_page.html')
    for widget in soup.select('.property-pros'):widget.decompose()
    values,_=extract_room_metrics(soup,'propertypro')
    assert values['bedrooms']=='3' and values['bathrooms']=='3'
