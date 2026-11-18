from types import SimpleNamespace
import pytest
from scraper.parsers.propertypro import PropertyProParser
from scripts.refresh_room_counts import primary_observation

URL='https://propertypro.ng/property/3-bedroom-flat-for-rent-7NUGY'
HTML='''<html><head><link rel="canonical" href="'''+URL+'''"/></head><body>
<h1 class="page-heading">3 Bedroom Flat</h1>
<div class="property-pricing"><div class="pricing"><h2>₦1,000,000/year</h2></div>
<div class="property-pros"><ul><li>3 Beds</li><li>5 Baths</li><li>6 Toilets</li></ul></div></div>
<div class="content-block"><p class="line-paragraph">A flat.</p></div></body></html>'''


def setup(response=None):
    parser=PropertyProParser({},load_robots=False)
    response=response or SimpleNamespace(status_code=200,url=URL,text=HTML)
    parser.session=SimpleNamespace(get=lambda *args,**kwargs:response)
    row=dict(source='propertypro',external_id='7NUGY',url=URL,title='3 Bedroom Flat',description='A flat.')
    return parser,row,SimpleNamespace(can_fetch=lambda *args:True)


def test_primary_metric_observation_is_separate_from_toilets():
    listing,status=primary_observation(*setup())
    assert status=='OBSERVED'
    assert (listing.bedrooms,listing.bathrooms)==(3,5)
    assert listing.raw_bathrooms=='5 Baths'


@pytest.mark.parametrize('response,expected',[
    (SimpleNamespace(status_code=404,url=URL,text=''),'HTTP_404'),
    (SimpleNamespace(status_code=200,url=URL.replace('7NUGY','8PNEW'),text=HTML),'IDENTITY_CHANGED'),
    (SimpleNamespace(status_code=200,url=URL,text=HTML.replace('A flat.','New source text.')),'SOURCE_CHANGED_REFRESH_FULL_LISTING'),
])
def test_unavailable_reused_or_changed_pages_do_not_supply_room_updates(response,expected):
    listing,status=primary_observation(*setup(response))
    assert listing is None and status==expected


def test_disallowed_page_is_not_requested():
    parser,row,_=setup();parser.session=SimpleNamespace(get=lambda *args,**kwargs:pytest.fail('HTTP should not run'))
    assert primary_observation(parser,row,SimpleNamespace(can_fetch=lambda *args:False))==(None,'ROBOTS_DISALLOWED')
