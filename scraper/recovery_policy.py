"""Conservative automatic approval of primary live quotes; no saved-text guesses."""
import re
from scraper.pricing import parse_amount, parse_terms

POLICY_VERSION = 'automatic-primary-quote-v1'


def quote_decision(row, quote, visible_purpose=None):
    """Return (approved, reason). Uncertainty is a review item, never a default unit."""
    if row.get('listing_status') != 'ACTIVE':
        return False, 'listing_not_active'
    if row.get('price_type') not in ('FOR_RENT', 'FOR_SHORT_LET'):
        return False, 'not_a_rental'
    if row.get('price_period_status') == 'KNOWN':
        return False, 'period_already_known'
    if not quote:
        return False, 'quote_unavailable'
    if quote.get('price_type') != row.get('price_type'):
        return False, 'purpose_changed'
    if visible_purpose == 'FOR_SALE' or (
        visible_purpose == 'FOR_SHORT_LET' and quote.get('price_type') != 'FOR_SHORT_LET'
    ):
        return False, 'page_purpose_conflict'
    if quote.get('price_currency') != 'NGN':
        return False, 'currency_not_ngn'
    if quote.get('price_period_status') != 'KNOWN':
        return False, 'period_' + str(quote.get('price_period_status', 'UNKNOWN')).lower()
    if quote.get('price_basis') not in ('PROPERTY', 'AREA', 'ROOM', 'PERSON'):
        return False, 'basis_unknown'
    raw = quote.get('raw_price_text') or ''
    # A total in parentheses can turn "6M for 2 years (#12M)" into an advance
    # payment condition rather than the period covered by the saved amount.
    if re.search(r'#\s*\d|upfront|in\s+advance', raw, re.I):
        return False, 'advance_or_multiple_amounts'
    if len(re.findall(r'₦|\bNGN\b', raw, re.I)) > 1:
        return False, 'multiple_amounts'
    amount, failed = parse_amount(raw)
    if failed or amount != quote.get('price_kobo'):
        return False, 'amount_not_supported'
    terms = parse_terms(raw, quote['price_type'])
    if (terms.price_period_status, terms.price_period, terms.price_period_count) != (
        'KNOWN', quote.get('price_period'), quote.get('price_period_count')
    ):
        return False, 'period_evidence_mismatch'
    if terms.price_basis != quote.get('price_basis'):
        return False, 'basis_evidence_mismatch'
    if quote.get('price_period_source') != 'PORTAL_PRICE':
        return False, 'not_primary_price_evidence'
    return True, 'explicit_primary_quote'


def primary_purpose(soup, source):
    """Inspect only the primary header, never recommendations or marketing copy."""
    if source == 'privateproperty':
        header = soup.select_one('.property-info')
    elif source == 'nigeriapropertycentre':
        heading = soup.select_one('main h1')
        header = heading
        if heading:
            for parent in list(heading.parents)[:4]:
                if parent.name in ('main', 'body', 'html'):
                    break
                if parent.select_one('[class*="text-[1.625rem]"]'):
                    header = parent
                    break
        else:
            header = soup.select_one('.property-details')
    else:
        header = soup.select_one('h1.page-heading')
    text = header.get_text(' ', strip=True)[:700] if header else ''
    if re.search(r'\bfor\s+sale\b', text, re.I):
        return 'FOR_SALE'
    if re.search(r'\bfor\s+short[ -]?let\b', text, re.I):
        return 'FOR_SHORT_LET'
    if re.search(r'\bfor\s+rent\b', text, re.I):
        return 'FOR_RENT'
    return None
