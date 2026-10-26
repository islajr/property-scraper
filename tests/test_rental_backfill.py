from dataclasses import asdict
import pytest
from scraper.normaliser import normalise
from tests.conftest import make_raw
from scripts.backfill_rental_pricing import offline_proposal, metadata


def row(description=None,**kwargs):
    listing=normalise(make_raw(raw_price='₦300,000',raw_price_type='FOR_RENT',description=description))
    return {**asdict(listing),**kwargs}


def test_only_identical_saved_amount_can_receive_historical_period():
    original=row('Rent is ₦300,000 per month.')
    new=offline_proposal(original)
    assert new['price_period']=='MONTH'
    assert new['price_period_source']=='DESCRIPTION'
    assert new['price_kobo']==original['price_kobo']
    assert new['pricing_observed_at'] is None
    assert new['raw_price_text']==original['raw_price_text']
    assert offline_proposal(row('Rent is ₦400,000 per month.')) is None


@pytest.mark.parametrize('description',[
 'Rent available. Annual service charge.', 'Service charge ₦300,000 per year.',
 'Minimum stay 2 weeks. ₦300,000.', '24 hour security. Monthly income ₦300,000.',
 '₦300,000; refundable deposit payable per month.',
])
def test_unrelated_time_or_fee_signals_remain_unknown(description):
    assert offline_proposal(row(description)) is None


def test_shortlet_url_can_correct_type_without_guessing_period():
    new=offline_proposal(row(url='https://nigeriapropertycentre.com/for-rent/short-let/123456-test'))
    assert new['price_type']=='FOR_SHORT_LET'
    assert new['price_period_status']=='UNKNOWN'
    assert new['price_period'] is None and new['price_period_source']=='URL'


def test_conflicting_saved_quotes_remain_visible():
    new=offline_proposal(row('₦300,000 per month; ₦300,000 per year'))
    assert new['price_period_status']=='CONFLICT'
    assert new['price_period'] is None


def test_known_quote_is_not_overwritten_by_description():
    original=row('₦300,000 per year',price_period='MONTH',price_period_count=1,price_period_status='KNOWN')
    assert offline_proposal(original) is None


def test_live_revisit_ignores_redirects_without_changing_listing_lifecycle():
    from unittest.mock import MagicMock
    from scripts.backfill_rental_pricing import live_proposal
    parser=MagicMock()
    parser._get.return_value='<html>Different property</html>'
    parser.last_response_url='https://test/different'
    parser._extract_external_id.return_value='different'
    record=dict(source='propertypro',listing_status='ACTIVE',external_id='original',url='https://test/original')
    new,outcome=live_proposal(record,{'propertypro':parser})
    assert new is None and outcome=='redirected'
    parser.parse_listing.assert_not_called()


def test_pre_migration_preview_does_not_count_unknown_defaults_as_recovery():
    original=row()
    for field in ('price_period','price_period_count','price_period_status','price_period_source',
                  'raw_price_text','price_period_evidence','price_currency','price_basis','pricing_observed_at'):
        original.pop(field,None)
    assert offline_proposal(original) is None


def test_live_recovery_is_idempotent_for_identical_quotes():
    from unittest.mock import MagicMock
    from scripts.backfill_rental_pricing import live_proposal
    raw=make_raw(raw_price='₦300,000',raw_price_type='FOR_RENT')
    record=asdict(normalise(raw))
    record['listing_status']='ACTIVE'
    parser=MagicMock()
    parser.last_response_url=raw.url
    parser._extract_external_id.return_value=raw.external_id
    parser._get.return_value='<html>unchanged</html>'
    parser.parse_listing.return_value=raw
    new,outcome=live_proposal(record,{'propertypro':parser})
    assert new is None and outcome=='unchanged'
