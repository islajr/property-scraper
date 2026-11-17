"""Read-only text profiling candidates, never persisted property-count facts."""
import re

VERSION = 'property-count-profile-v1'
TITLE_LIMIT = 2000
DESCRIPTION_LIMIT = 20000
CANDIDATE_LIMIT = 100

_ONES = 'one two three four five six seven eight nine'.split()
_SMALL = ['zero'] + _ONES + 'ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
_TENS = 'twenty thirty forty fifty sixty seventy eighty ninety'.split()
_WORDS = '|'.join(_SMALL)
_NUMBER = rf'(?:\d{{1,3}}(?:,\d{{3}})+|\d+|(?:{"|".join(_TENS)})(?:[ -]+(?:{"|".join(_ONES)}))?|(?:{_WORDS}))'
_QUANTITY = rf'(?:(?:at\s+least|minimum\s+of|not\s+less\s+than)\s+)?{_NUMBER}(?:\s*(?:[-–—]|to)\s*{_NUMBER})?'
_BED = r'(?:bedrooms?|bed[ -]+rooms?|beds?)'
_NOUN = r'(?:mini[ -]*flats?|studio[ -]+apartments?|maisonettes?|duplex(?:es)?|bungalows?|houses?|flats?|apartments?|buildings?|blocks?|rooms?|units?)'
_MODIFIER = rf'(?:(?:fully[ -]+)?detached|semi[ -]+detached|terraced?|newly[ -]+built|separate|residential|commercial|{_NUMBER}[ -]*{_BED})'
_START = r'(?<![\w,])\b'
_ASSETS = re.compile(rf'{_START}(?P<quantity>{_QUANTITY})[ -]*(?:[×x]\s*)?(?:(?:{_MODIFIER})[ -]+){{0,3}}(?P<noun>{_NOUN})\b', re.I)
_BEDROOMS = re.compile(rf'{_START}(?P<quantity>{_QUANTITY})[ -]*(?P<noun>{_BED})\b', re.I)
_QUANTITY_PARTS = re.compile(rf'^(?P<lower>at\s+least|minimum\s+of|not\s+less\s+than)?\s*(?P<first>{_NUMBER})(?:\s*(?:[-–—]|to)\s*(?P<second>{_NUMBER}))?$', re.I)
_MONEY = re.compile(r'(?:[₦$£€]|\b(?:NGN|USD|GBP|EUR)|\bN(?=\d))\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|[mb])\b)?',re.I)


def _number(text):
    text = text.lower().strip()
    if text.replace(',','').isdigit():
        return int(text.replace(',',''))
    parts = re.split(r'[ -]+', text)
    if parts[0] in _TENS:
        return 20 + 10 * _TENS.index(parts[0]) + (_SMALL.index(parts[1]) if len(parts) > 1 else 0)
    return _SMALL.index(text)


def _quantity(text):
    match = _QUANTITY_PARTS.fullmatch(text)
    first = _number(match['first'])
    second = _number(match['second']) if match['second'] else None
    return dict(kind='RANGE' if second is not None else 'AT_LEAST' if match['lower'] else 'EXACT',
                minimum=first, maximum=second if second is not None else None if match['lower'] else first)


def _entity(noun):
    noun = noun.lower()
    if noun.startswith(('building', 'block')):
        return 'BUILDING'
    if noun.startswith('unit'):
        return 'UNSPECIFIED_UNIT'
    if noun.startswith('room'):
        return 'ROOM'
    if noun.startswith('bed'):
        return 'BEDROOM' if 'room' in noun else 'BEDROOM_SHORTHAND'
    return 'DWELLING_UNIT'


def _hints(text, match):
    before, after = text[max(0, match.start()-100):match.start()], text[match.end():match.end()+100]
    hints, flags = [], []
    if re.search(r'\b(?:containing|comprising|consisting\s+of|contains|blocks?\s+of)\s*$', before, re.I):
        hints.append('CONTAINED_UNITS')
    if re.search(r'\b(?:available|remaining)\b', after[:45], re.I):
        hints.append('AVAILABILITY')
    if re.search(r'\b(?:sold|rented|leased|taken)\s+together\b|\bat\s+once\b', after, re.I):
        hints.append('BUNDLE')
    if _entity(match['noun']) in {'BEDROOM','BEDROOM_SHORTHAND','ROOM'} and re.search(
            r'\b(?:each|per\s+(?:flat|unit|apartment|dwelling))\b', before[-45:]+' '+after[:45], re.I):
        hints.append('PER_DWELLING')
    clause = re.split(r'[.!?;\n]', before)[-1]
    if re.search(r'\b(?:near|beside|opposite|close\s+to|suitable\s+for|ideal\s+for|contact|other\s+properties)\b', clause, re.I):
        flags.append('POSSIBLY_NONPRIMARY_CONTEXT')
    if re.search(r'\b(?:no|not|without)\s*$', before, re.I):
        flags.append('NEGATED')
    if _entity(match['noun']) == 'ROOM' and re.match(r'\s+(?:bq\b|boys?[’\x27]?\s+quarters?\b)', after, re.I):
        flags.append('POSSIBLY_ANCILLARY_BQ')
    return hints, flags


def profile_text(title=None, description=None):
    """Find literal quantity mentions, with review flags rather than inferred roles.

    A no-match result means no supported pattern matched, not that the listing
    lacks counts. Relation hints are prompts to inspect, never accepted scopes.
    Existing canonical types and numeric bedroom columns are deliberately absent.
    """
    candidates, truncated = [], []
    texts = []
    for source, original, limit in [('TITLE', title or '', TITLE_LIMIT),
                                    ('DESCRIPTION', description or '', DESCRIPTION_LIMIT)]:
        text = original[:limit]
        # Mask prices in place so a concatenated amount cannot become the first
        # number in a false range. Offsets always refer to the original source.
        scan = _MONEY.sub(lambda m:' '*len(m.group()),text)
        texts.append(text)
        if len(original) > limit:
            truncated.append(source)
        seen = set()
        for pattern in (_BEDROOMS, _ASSETS):
            for match in pattern.finditer(scan):
                if text[match.start():match.end()] != scan[match.start():match.end()]:
                    continue
                entity = _entity(match['noun'])
                # BED ROOM is a bedroom phrase, not a separate offered ROOM.
                if entity == 'ROOM' and re.search(r'(?:\bbed|\d+bed)\s*$', text[:match.start()], re.I):
                    continue
                signature = (match.start(), match.end(), entity)
                if signature in seen:
                    continue
                seen.add(signature)
                quantity = _quantity(match['quantity'])
                hints, flags = _hints(text, match)
                if quantity['maximum'] is not None and quantity['minimum'] > quantity['maximum']:
                    flags.append('REVERSED_RANGE')
                if quantity['kind']=='RANGE':
                    flags.append('RANGE_REQUIRES_CONTEXT')
                if entity != 'BEDROOM' and quantity['minimum'] == 0:
                    flags.append('ZERO_ASSET_OR_UNRESOLVED_COUNT')
                if entity == 'BEDROOM_SHORTHAND':
                    flags.append('BED_SHORTHAND_REQUIRES_CONTEXT')
                candidates.append(dict(source=source, entity=entity, quantity=quantity,
                                       noun=match['noun'], start=match.start(), end=match.end(),
                                       text=match.group(), relation_hints=hints, review_flags=flags,
                                       context=text[max(0,match.start()-80):match.end()+80]))
    candidates.sort(key=lambda c:(0 if c['source']=='TITLE' else 1, c['start'], c['end']))
    if len(candidates) > CANDIDATE_LIMIT:
        truncated.append('CANDIDATE_LIMIT')
        candidates = candidates[:CANDIDATE_LIMIT]
    combined = '\n'.join(texts)
    alternative = bool((re.search(r'\bper\s+unit\b', combined, re.I) and
                        re.search(r'\ball\s+units\b', combined, re.I)) or
                       (re.search(r'\bindividually\b', combined, re.I) and
                        re.search(r'\btogether\b', combined, re.I)))
    by_source = {}
    for candidate in candidates:
        if candidate['quantity']['kind'] != 'EXACT' or candidate['review_flags']:
            continue
        by_source.setdefault((candidate['source'],candidate['entity']),set()).add(candidate['quantity']['minimum'])
    conflicts = sorted(entity for entity in {c['entity'] for c in candidates}
                       if by_source.get(('TITLE',entity)) and by_source.get(('DESCRIPTION',entity))
                       and by_source[('TITLE',entity)].isdisjoint(by_source[('DESCRIPTION',entity)]))
    state = ('OFFER_ALTERNATIVES' if alternative else 'POSSIBLE_CONFLICT' if conflicts else
             'COUNT_CANDIDATES' if candidates else 'NO_PATTERN_MATCH')
    return dict(profile_version=VERSION, state=state, candidates=candidates,
                possible_conflict_entities=conflicts, offer_alternative_hint=alternative,
                truncated=truncated, requires_review=bool(candidates or truncated or alternative))
