from bs4 import BeautifulSoup
import pytest
from scraper.parsers.propertypro import PropertyProParser
from scraper.parsers.listing_identity import primary_identity_matches
from tests.test_pricing_database import pricing_writer,listing,get_row

URL='https://propertypro.ng/property/example-7NUGY'


@pytest.mark.parametrize('final,canonical,accepted',[
 (URL,URL,True),(URL+'/',URL,True),
 ('https://www.propertypro.ng/property/renamed-7NUGY',URL,True),
 (URL.replace('7NUGY','17NUGY'),URL,False),
 ('https://propertypro.ng/search?previous=example-7NUGY',URL,False),
 ('https://other.example/property/example-7NUGY',URL,False),
 (URL,URL.replace('7NUGY','17NUGY'),False),
 (URL,'https://other.example/property/example-7NUGY',False),
 (URL,'/property/example-7NUGY',True),
])
def test_only_exact_primary_identity_can_supply_observations(final,canonical,accepted):
    parser=PropertyProParser({},load_robots=False)
    soup=BeautifulSoup('<link rel="canonical" href="'+canonical+'">','html.parser')
    assert primary_identity_matches(parser,URL,final_url=final,soup=soup,expected_id='7NUGY') is accepted


def test_foreign_quote_is_rejected_before_any_saved_field_changes(pricing_writer):
    db=pricing_writer;old=listing();db.upsert([old],{});before=get_row(db,old.external_id);db.conn.rollback()
    foreign=listing('₦100,000 per month',raw_bedrooms='4 Bedrooms',raw_bathrooms='5 Bathrooms')
    with pytest.raises(ValueError):db.confirm_listing_active(before['id'],None,observed_quote=foreign)
    assert get_row(db,old.external_id)==before


@pytest.mark.parametrize('redirect,canonical',[
 ('https://portal.test/property/123456','https://portal.test/property/123456'),
 ('https://portal.test/property/12345','https://portal.test/property/123456'),
])
def test_discovery_does_not_parse_a_different_redirected_or_canonical_listing(redirect,canonical):
    from scraper.parsers.base_parser import BaseParser
    class Parser(BaseParser):
        source='test';base_url='https://portal.test';search_urls=['https://portal.test/feed']
        def get_listing_urls(self,soup):return ['https://portal.test/property/12345']
        def next_page_url(self,*args):return None
        def parse_listing(self,*args):pytest.fail('A different listing must not be parsed')
        def _polite_delay(self):pass
        def _get(self,url):
            self.last_response_url=redirect if '/property/' in url else url
            return '<link rel="canonical" href="'+canonical+'">' if '/property/' in url else '<html>feed</html>'
    parser=Parser({},load_robots=False)
    assert parser.scrape()==[]


@pytest.mark.parametrize('final,canonical,raises',[
 (URL.replace('7NUGY','17NUGY'),None,False),
 ('https://other.example/property/example-7NUGY',None,True),
 (URL,URL.replace('7NUGY','17NUGY'),True),
])
def test_health_does_not_extract_foreign_primary_metrics(final,canonical,raises):
    import asyncio
    from unittest.mock import MagicMock,AsyncMock
    from scraper.health_checker import HealthChecker
    checker=HealthChecker(MagicMock());checker._extract_observed_quote=MagicMock()
    response=MagicMock();response.status=200;response.url=final
    response.text=AsyncMock(return_value='<html>'+('<link rel="canonical" href="'+canonical+'">' if canonical else '')+'Active</html>')
    session=MagicMock();session.get.return_value.__aenter__.return_value=response
    operation=checker._check_listing_async(session,URL,'7NUGY','propertypro')
    if raises:
        with pytest.raises(ValueError):asyncio.run(operation)
    else:
        removed,quote=asyncio.run(operation);assert removed and quote is None
    checker._extract_observed_quote.assert_not_called()



def test_health_parses_a_valid_same_id_redirect_using_its_current_url():
    import asyncio
    from unittest.mock import MagicMock,AsyncMock
    from scraper.health_checker import HealthChecker
    final='https://propertypro.ng/property/flat-for-sale-7NUGY'
    checker=HealthChecker(MagicMock());checker._extract_observed_quote=MagicMock(return_value=None)
    response=MagicMock();response.status=200;response.url=final
    response.text=AsyncMock(return_value='<link rel="canonical" href="'+final+'">Active')
    session=MagicMock();session.get.return_value.__aenter__.return_value=response
    removed,quote=asyncio.run(checker._check_listing_async(session,URL,'7NUGY','propertypro'))
    assert not removed and quote is None
    assert checker._extract_observed_quote.call_args.args[1]==final
