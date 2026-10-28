"""Pure advertised-quote parsing. Never infer cadence from listing purpose or amount."""
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import re

PERIOD_FIELDS = ('price_period', 'price_period_count', 'price_period_status',
                 'price_period_source', 'raw_price_text', 'price_period_evidence',
                 'price_currency', 'price_basis')
QUOTE_FIELDS = ('price_kobo', 'price_type', *PERIOD_FIELDS)
UNITS = {
    'hour': ('HOUR', 1), 'hr': ('HOUR', 1), 'day': ('DAY', 1),
    'night': ('NIGHT', 1), 'week': ('WEEK', 1), 'wk': ('WEEK', 1),
    'fortnight': ('WEEK', 2), 'month': ('MONTH', 1), 'mo': ('MONTH', 1),
    'quarter': ('MONTH', 3), 'year': ('YEAR', 1), 'yr': ('YEAR', 1),
    'annum': ('YEAR', 1),
}
UNIT_PATTERN = '|'.join(sorted(UNITS, key=len, reverse=True))
PERIOD = re.compile(r'(?:/|(?<![a-z])per\s*(?:calendar\s+)?|\ba\s+)(?:(\d+)\s*)?(' + UNIT_PATTERN + r')s?\b', re.I)
MULTIPERIOD = re.compile(r'\b(?:for|every)\s+(\d+)\s+(' + UNIT_PATTERN + r')s?\b', re.I)
ADJECTIVES = re.compile(r'\b(hourly|daily|nightly|weekly|fortnightly|monthly|quarterly|yearly|annually|annual)\b', re.I)
ADJECTIVE_UNITS = dict(zip(('hourly','daily','nightly','weekly','fortnightly','monthly','quarterly','yearly','annually','annual'),
                          ('hour','day','night','week','fortnight','month','quarter','year','year','year')))
SHORT_LET = re.compile(r'\bshort[\s_-]*lets?\b', re.I)


@dataclass(frozen=True)
class PricingTerms:
    price_period: str | None = None
    price_period_count: int | None = None
    price_period_status: str = 'UNKNOWN'
    price_period_source: str = 'PORTAL_PRICE'
    raw_price_text: str | None = None
    price_period_evidence: str | None = None
    price_currency: str | None = None
    price_basis: str = 'UNKNOWN'


def currency(text):
    matches = []
    for code, pattern in [('NGN', r'₦|\bNGN\b|\bnaira\b|\bN(?=\s*\d)'),
                          ('USD', r'\$|\bUSD\b'), ('GBP', r'£|\bGBP\b'),
                          ('EUR', r'€|\bEUR\b')]:
        if re.search(pattern, text or '', re.I): matches.append(code)
    return matches[0] if len(matches) == 1 else None


def parse_amount(text):
    """Return an integer NGN minor amount, rejecting foreign and ambiguous quotes."""
    if not text or currency(text) in ('USD', 'EUR', 'GBP'):
        return None, True
    if re.search(r'\b(?:USD|GBP|EUR|JPY|CAD|AUD|CHF)\b|[$£€]', text, re.I):
        return None, True
    if currency(text) != 'NGN' and not re.match(r'^\s*\d', text):
        return None, True
    # Prefer the amount immediately following NGN evidence over a leading duration.
    marker = re.search(r'₦|\bNGN\b|\bN(?=\s*\d)', text, re.I)
    amount_text = text[marker.end():] if marker else text
    match = re.search(r'(?<![\d.,])([\d,]+(?:\.\d+)?)(?![\d.,])\s*(?:(billion|million|[kmb])\b)?', amount_text, re.I)
    if not match: return None, True
    # A range or multiple advertised amounts cannot be collapsed to the first number.
    remainder = amount_text[match.end():]
    if re.search(r'^\s*[-–]\s*(?:₦\s*)?\d|\b(?:or|to)\s*(?:₦\s*)?\d', remainder, re.I):
        return None, True
    try:
        value = Decimal(match[1].replace(',', ''))
        factor = {'k': 1000, 'm': 1000000, 'million': 1000000,
                  'b': 1000000000, 'billion': 1000000000}.get((match[2] or '').lower(), 1)
        minor = value * factor * 100
        if minor <= 0 or minor > 9223372036854775807 or minor != minor.to_integral_value():
            return None, True
        return int(minor), False
    except InvalidOperation:
        return None, True


def parse_terms(text, price_type, source='PORTAL_PRICE'):
    raw = ' '.join((text or '').split())[:1000] or None
    text = raw or ''
    basis = 'PROPERTY' if text else 'UNKNOWN'
    for name, pattern in [('AREA', r'(?:/|\bper\s*)(?:sq\.?\s*m|sqm|square\s+met|m[²2])'),
                          ('ROOM', r'(?:/|\bper\s+)room\b'),
                          ('PERSON', r'(?:/|\bper\s+)(?:person|guest|head)\b')]:
        if re.search(pattern, text, re.I): basis = name
    fields = dict(raw_price_text=raw, price_currency=currency(text), price_basis=basis,
                  price_period_source=source)
    if price_type == 'FOR_SALE':
        return PricingTerms(**fields, price_period_status='NOT_APPLICABLE')
    if price_type not in ('FOR_RENT', 'FOR_SHORT_LET'):
        return PricingTerms(**fields)
    # Separate minimum stay, deposits, charges, and advance-payment clauses from cadence.
    words = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'eleven':11,'twelve':12}
    text_for_period = re.sub(r'\b('+'|'.join(words)+r')(?=\s+(?:hours?|days?|nights?|weeks?|months?|years?)\b)', lambda m:str(words[m[1].lower()]), text, flags=re.I)
    text_for_period = re.sub(r'\b(?:for\s+)?\d+\s+(?:years?|months?|weeks?)\s+(?:in\s+advance|upfront)\b', '', text_for_period, flags=re.I)
    main = re.split(r'[;\n]|\b(?:minimum\s+(?:stay|lease)|min\.?\s+stay|service\s+charge|deposit|payable|upfront)\b', text_for_period, maxsplit=1, flags=re.I)[0]
    periods = set()
    for pattern in (PERIOD, MULTIPERIOD):
        for match in pattern.finditer(main):
            unit, multiplier = UNITS[match[2].lower()]
            count = int(match[1] or 1) * multiplier
            if count <= 0 or count > 2147483647:
                return PricingTerms(**fields, price_period_status='UNSUPPORTED', price_period_evidence=raw)
            periods.add((unit, count))
    for match in ADJECTIVES.finditer(main): periods.add(UNITS[ADJECTIVE_UNITS[match[1].lower()]])
    if len(periods) > 1:
        return PricingTerms(**fields, price_period_status='CONFLICT', price_period_evidence=raw)
    if re.search(r'(?:per|/)\s*(?:stay|package|session)|\bpackage\b', main, re.I):
        return PricingTerms(**fields, price_period_status='UNSUPPORTED', price_period_evidence=raw)
    if periods:
        period, count = periods.pop()
        return PricingTerms(**fields, price_period=period, price_period_count=count,
                            price_period_status='KNOWN', price_period_evidence=raw)
    return PricingTerms(**fields)


def quote_dict(value):
    data = asdict(value) if hasattr(value, '__dataclass_fields__') else value
    return {key: data.get(key) for key in QUOTE_FIELDS}


def comparable(old, new):
    if old.get('price_kobo') is None or new.get('price_kobo') is None: return False
    if old.get('price_type') != new.get('price_type'): return False
    if any(q.get('price_currency') != 'NGN' or q.get('price_basis') != 'PROPERTY' for q in (old, new)): return False
    if old.get('price_type') == 'FOR_SALE': return True
    return (all(q.get('price_period_status') == 'KNOWN' for q in (old, new))
            and (old.get('price_period'), old.get('price_period_count'))
            == (new.get('price_period'), new.get('price_period_count')))


def classify_change(old, new):
    """An amount change with unknown/different units is not a comparable price move."""
    if comparable(old, new):
        return 'PRICE_CHANGE' if old['price_kobo'] != new['price_kobo'] else None
    keys = ('price_kobo', 'price_type', 'price_period', 'price_period_count',
            'price_period_status', 'price_currency', 'price_basis')
    return 'PRICING_CONTEXT_CHANGE' if any(old.get(k) != new.get(k) for k in keys) else None
