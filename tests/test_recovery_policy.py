from dataclasses import asdict
from bs4 import BeautifulSoup
import pytest
from scraper.normaliser import normalise
from scraper.pricing import quote_dict
from scraper.recovery_policy import quote_decision, primary_purpose
from tests.conftest import make_raw


def inputs(text='₦3M/year'):
    row=asdict(normalise(make_raw(raw_price='₦3M',raw_price_type='FOR_RENT')))
    quote=quote_dict(normalise(make_raw(raw_price=text,raw_price_type='FOR_RENT')))
    return row,quote


def test_current_amount_change_is_supported_without_assuming_old_cadence():
    row,quote=inputs('₦4M/year')
    assert quote_decision(row,quote)==(True,'explicit_primary_quote')


@pytest.mark.parametrize('text,reason',[
 ('₦3M','period_unknown'), ('₦6M for 2 years (#12m)','advance_or_multiple_amounts'),
 ('$300/month','currency_not_ngn'), ('₦300,000 per month or per year','period_conflict'),
])
def test_ambiguous_live_quotes_are_held(text,reason):
    row,quote=inputs(text)
    assert quote_decision(row,quote)==(False,reason)


def test_sale_marketing_is_not_shortlet_purpose():
    row,quote=inputs()
    soup=BeautifulSoup('<div class="property-info"><h1>For sale: furnished shortlet investment apartment</h1></div>','html.parser')
    assert primary_purpose(soup,'privateproperty')=='FOR_SALE'
    assert quote_decision(row,quote,'FOR_SALE')==(False,'page_purpose_conflict')


def test_unknown_and_nonprimary_evidence_are_not_auto_applied():
    row,quote=inputs()
    assert quote_decision(row,{**quote,'price_period_source':'DESCRIPTION'})[0] is False
    assert quote_decision(row,{**quote,'price_type':'FOR_SHORT_LET'})[0] is False


def test_held_period_can_become_known_from_explicit_calendar_label():
    row,quote=inputs('₦260,000 per calendar month')
    assert quote_decision(row,quote)[0] is True
