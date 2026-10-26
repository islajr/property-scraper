import pytest
from scraper.pricing import parse_terms, parse_amount, comparable, classify_change
from scraper.normaliser import normalise, parse_price_type
from tests.conftest import make_raw


@pytest.mark.parametrize('label,period,count', [
 ('₦3,000,000 per annum','YEAR',1), ('₦3M/year','YEAR',1),
 ('₦300,000/month','MONTH',1), ('₦300K monthly','MONTH',1),
 ('₦20,000 per week','WEEK',1), ('₦5,000 daily','DAY',1),
 ('₦75,000 per night','NIGHT',1), ('₦20,000/hr','HOUR',1),
 ('₦1,800,000 for 6 months','MONTH',6), ('₦1M per quarter','MONTH',3),
 ('₦50,000 fortnightly','WEEK',2), ('₦4000000per annum','YEAR',1),
 ('₦10,000 per night; minimum stay 3 nights','NIGHT',1),
 ('₦3M/year; 2 years upfront','YEAR',1),
])
def test_explicit_periods(label,period,count):
    terms=parse_terms(label,'FOR_RENT')
    assert (terms.price_period,terms.price_period_count,terms.price_period_status)==(period,count,'KNOWN')
    assert terms.raw_price_text and terms.price_period_evidence


@pytest.mark.parametrize('label,status', [
 ('₦200,000','UNKNOWN'), ('₦200,000 per stay','UNSUPPORTED'),
 ('₦200,000/month or per year','CONFLICT'), ('₦2,000 per 0 months','UNSUPPORTED'),
 ('₦200,000; minimum lease 2 years','UNKNOWN'),
 ('₦200,000; service charge paid annually','UNKNOWN'),
])
def test_ambiguity_is_visible(label,status):
    terms=parse_terms(label,'FOR_SHORT_LET')
    assert terms.price_period_status==status
    assert terms.price_period is None and terms.price_period_count is None


def test_sale_cadence_is_inapplicable_and_shortlet_is_not_assumed_daily():
    assert parse_terms('₦3M','FOR_SALE').price_period_status=='NOT_APPLICABLE'
    assert parse_terms('₦3M','FOR_SHORT_LET').price_period_status=='UNKNOWN'
    assert parse_price_type(None,'Short let apartment for rent',None)=='FOR_SHORT_LET'


def test_recommendation_and_unrelated_description_are_not_period_evidence():
    listing=normalise(make_raw(raw_price='₦200,000',raw_price_type='FOR_RENT',description='Annual service charge. 24 hour security. Minimum stay 2 weeks.'))
    assert listing.price_period_status=='UNKNOWN'


@pytest.mark.parametrize('label,value', [('₦3M/month',300000000), ('₦1,000.25 per day',100025), ('45M',4500000000)])
def test_exact_minor_amount(label,value):
    assert parse_amount(label)==(value,False)


@pytest.mark.parametrize('label', ['$300/month','USD 500/week','₦20,000–30,000/day','₦0/day','₦9999999999999999999999'])
def test_invalid_or_non_ngn_prices_never_become_kobo(label):
    assert parse_amount(label)==(None,True)


def test_per_area_is_not_a_whole_property_quote():
    assert parse_terms('₦5,000 per sqm per year','FOR_RENT').price_basis=='AREA'


def test_comparison_requires_known_identical_units():
    a=dict(price_kobo=30000000,price_type='FOR_RENT',price_period='MONTH',price_period_count=1,price_period_status='KNOWN',price_currency='NGN',price_basis='PROPERTY')
    assert comparable(a,a)
    assert classify_change(a,{**a,'price_kobo':20000000})=='PRICE_CHANGE'
    assert classify_change(a,{**a,'price_period':'YEAR'})=='PRICING_CONTEXT_CHANGE'
    assert not comparable({**a,'price_period_status':'UNKNOWN'},a)

@pytest.mark.parametrize('module,cls,fixture,selector,url', [
 ('propertypro','PropertyProParser','propertypro_listing_page.html','.property-pricing > .pricing > h2','https://propertypro.ng/property/test-for-short-let-AB123'),
 ('privateproperty','PrivatePropertyParser','privateproperty_listing.html','.property-info .price','https://privateproperty.ng/listings/short-let-test-AB123'),
 ('nigeriapropertycentre','NigeriaPropertyCentreParser','nigeriapropertycentre_listing.html','.property-details-price','https://nigeriapropertycentre.com/for-rent/short-let/123456-test'),
])
def test_portal_primary_quote_siblings_and_shortlet_precedence(module,cls,fixture,selector,url):
    import importlib
    from tests.conftest import load_fixture
    soup=load_fixture(fixture)
    soup.select_one(selector).clear()
    soup.select_one(selector).append('₦75,000 ')
    period=soup.new_tag('span'); period.string='per night'
    soup.select_one(selector).append(period)
    unrelated=soup.new_tag('aside'); unrelated.string='Recommended: ₦500,000 per month'
    soup.append(unrelated)
    parser=getattr(importlib.import_module('scraper.parsers.'+module),cls)({})
    raw=parser.parse_listing(soup,url)
    assert raw is not None
    result=normalise(raw)
    assert result.price_type=='FOR_SHORT_LET'
    assert result.price_kobo==7500000
    assert result.price_period=='NIGHT'
    assert 'Recommended' not in result.raw_price_text
