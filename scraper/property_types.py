"""Versioned property vocabulary and conservative, I/O-free classification.

Rules identify the advertised asset, not its price, location, or bedroom count.
Unknown input never becomes a new canonical type. See docs/property-types.md.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re

VERSION = 'property-types-v1'


@dataclass(frozen=True)
class TypeDefinition:
    category: str
    family: str
    attachment: str | None = None
    scope: str | None = None


TYPES = {}
for _code in ('FLAT_APARTMENT', 'MINI_FLAT', 'STUDIO', 'PENTHOUSE', 'MAISONETTE'):
    TYPES[_code] = TypeDefinition('RESIDENTIAL', 'APARTMENT', scope='UNIT')
for _code in ('HOUSE', 'DUPLEX', 'BUNGALOW', 'TOWNHOUSE', 'MANSION', 'VILLA'):
    TYPES[_code] = TypeDefinition('RESIDENTIAL', _code if _code in ('DUPLEX', 'BUNGALOW') else 'HOUSE')
for _form in ('DUPLEX', 'BUNGALOW'):
    for _attachment in ('DETACHED', 'SEMI_DETACHED', 'TERRACED'):
        TYPES[f'{_attachment}_{_form}'] = TypeDefinition('RESIDENTIAL', _form, _attachment)
for _code in ('ROOM', 'SELF_CONTAINED'):
    TYPES[_code] = TypeDefinition('RESIDENTIAL', 'ROOM', scope='UNIT')
TYPES['BLOCK_OF_FLATS'] = TypeDefinition('RESIDENTIAL', 'BLOCK_OF_FLATS', scope='WHOLE_BUILDING')
for _code in ('OFFICE', 'COMMERCIAL_SHOP', 'SHOWROOM', 'COMMERCIAL_OTHER',
              'WAREHOUSE', 'OFFICE_BUILDING', 'HOTEL', 'GUEST_HOUSE', 'SCHOOL',
              'HOSPITAL', 'RESTAURANT', 'FACTORY', 'FILLING_STATION'):
    TYPES[_code] = TypeDefinition('COMMERCIAL', _code, scope=(
        'WHOLE_BUILDING' if _code in ('OFFICE_BUILDING', 'HOTEL', 'GUEST_HOUSE') else None))
for _code in ('LAND', 'LAND_SERVICED'):
    TYPES[_code] = TypeDefinition('LAND', 'LAND', scope='LAND_PARCEL')
TYPES['MIXED_USE_PROPERTY'] = TypeDefinition('MIXED_USE', 'MIXED_USE')

STATUSES = ('CLASSIFIED', 'INSUFFICIENT_EVIDENCE', 'AMBIGUOUS', 'UNSUPPORTED', 'LEGACY_UNREVIEWED')
FIELDS = ('property_type', 'property_category', 'property_type_family',
          'property_attachment', 'property_asset_scope', 'property_land_use',
          'property_type_raw', 'property_type_raw_source', 'property_type_status',
          'property_type_evidence', 'property_type_version', 'property_type_classified_at')


@dataclass
class Classification:
    property_type: str | None = None
    property_category: str | None = None
    property_type_family: str | None = None
    property_attachment: str | None = None
    property_asset_scope: str | None = None
    property_land_use: str | None = None
    property_type_raw: str | None = None
    property_type_raw_source: str | None = None
    property_type_status: str = 'INSUFFICIENT_EVIDENCE'
    property_type_evidence: dict = field(default_factory=dict)
    property_type_version: str = VERSION
    property_type_classified_at: datetime | None = None


# Specific phrases consume their own spans before generic rules run. Separate
# non-overlapping assets remain candidates, so precedence cannot hide conflicts.
_PATTERNS = [
    ('BLOCK_OF_FLATS', r'(?:blocks?\s+of\s+(?:\d+\s+)?(?:flats?|apartments?)|apartment\s+blocks?)'),
    ('OFFICE_BUILDING', r'office\s+(?:buildings?|blocks?)'),
    ('MINI_FLAT', r'(?:mini\s*flats?|rooms?\s*(?:and|&)\s*parl(?:ou|o)r(?:\s+self\s*contain(?:ed)?)?)'),
    ('STUDIO', r'studio(?:\s+(?:flats?|apartments?))?'),
    ('SELF_CONTAINED', r'self\s*contain(?:ed)?(?:\s*\(single\s+rooms?\)?)?'),
    ('LAND_SERVICED', r'(?:fully\s+)?serviced\s+(?:plots?\s+of\s+)?land'),
    ('GUEST_HOUSE', r'guest\s*houses?'),
    ('FILLING_STATION', r'(?:filling|petrol|fuel)\s+stations?'),
    ('MIXED_USE_PROPERTY', r'mixed\s+use\s+(?:propert(?:y|ies)|buildings?)'),
    ('COMMERCIAL_OTHER', r'commercial\s+(?:propert(?:y|ies)|premises|spaces?)'),
    ('PENTHOUSE', r'pent\s*houses?'), ('MAISONETTE', r'maisonettes?'),
    ('TOWNHOUSE', r'town\s*houses?'), ('MANSION', r'mansions?'), ('VILLA', r'villas?'),
    ('OFFICE', r'offices?(?:\s+spaces?)?'), ('WAREHOUSE', r'ware\s*houses?'),
    ('SHOWROOM', r'show\s*rooms?'), ('COMMERCIAL_SHOP', r'shops?'),
    ('HOTEL', r'hotels?'), ('SCHOOL', r'schools?'), ('HOSPITAL', r'hospitals?'),
    ('RESTAURANT', r'restaurants?'), ('FACTORY', r'factor(?:y|ies)'),
    ('DUPLEX', r'duplex(?:es)?'), ('BUNGALOW', r'bungalows?'),
    ('FLAT_APARTMENT', r'(?:flats?(?:\s*/?\s*apartments?)?|apartments?)'),
    ('LAND', r'(?:land|plots?(?:\s+of\s+land)?|farmland)'),
    ('HOUSE', r'(?:houses?|detached\s+homes?)'), ('ROOM', r'rooms?'),
]
RULES = [(code, re.compile(r'\b(?:' + pattern + r')\b', re.I)) for code, pattern in _PATTERNS]
ATTACHMENTS = [(code, re.compile(r'\b' + pattern + r'\b', re.I)) for code, pattern in (
    ('SEMI_DETACHED', r'semi\s*detached'), ('TERRACED', r'terrac(?:e|ed|es)'),
    ('DETACHED', r'(?:fully\s+)?detached'))]
UNSUPPORTED = re.compile(r'\b(?:gas\s+plants?|church(?:es)?|mosques?|cinemas?|farms?|hostels?)\b', re.I)
CONTEXT = re.compile(
    r'\b(?:near|beside|opposite|behind|adjacent\s+to|close\s+to|next\s+to|'
    r'suitable\s+for|ideal\s+for|can\s+be\s+used\s+as|convert(?:ed|ible)?\s+to|'
    r'with|wit|w|without|including|features?|facilities|amenities|at|on|in|within|not|no)\b', re.I)
LAND_USES = {name: re.compile(pattern, re.I) for name, pattern in (
    ('RESIDENTIAL', r'\bresidential\b'), ('COMMERCIAL', r'\bcommercial\b'),
    ('INDUSTRIAL', r'\bindustrial\b'), ('AGRICULTURAL', r'\b(?:agricultural|farm(?:land)?)\b'),
    ('MIXED_USE', r'\bmixed\s+use\b'))}
_TRANSLATION = str.maketrans({c: ' ' for c in '_-–—‑'})


def _text(value):
    return (value or '').translate(_TRANSLATION)


def _contextual(text, start):
    """Reject matches introduced as amenities, landmarks or alternative uses."""
    prefix = re.split(r'[.;\n]', text[:start])[-1]
    # Ignore routine marketing prefixes such as 'for sale in Lekki: apartment'.
    prefix = prefix.rsplit(':', 1)[-1]
    return bool(CONTEXT.search(prefix))


def _scan(value, source):
    original = value or ''
    if source == 'BREADCRUMB':
        original = re.split(r'\bfor\s+(?:sale|rent|short\s*let)\b', original, maxsplit=1, flags=re.I)[0]
    text = _text(original)
    candidates, evidence, occupied = [], [], []
    if source in ('PORTAL_TYPE', 'BREADCRUMB') and original.strip().upper() in TYPES:
        code = original.strip().upper()
        return [code], [dict(source=source, text=original.strip(), rule='canonical_code', candidate=code)]
    for code, pattern in RULES:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            if _contextual(text, match.start()):
                continue
            if code == 'ROOM' and re.search(r'\bbed\s*$', text[:match.start()], re.I):
                continue
            if code == 'ROOM' and source == 'DESCRIPTION' and match.group().lower() == 'rooms':
                continue
            if code == 'ROOM' and re.search(r'\d+\s*$', text[:match.start()]) and re.search(
                    r'\b(?:hotel|house|apartment|duplex|bungalow|guest)\b', text[match.end():], re.I):
                continue
            occupied.append(match.span())
            candidates.append(code)
            evidence.append(dict(source=source, text=original[match.start():match.end()],
                                 rule='alias:' + code.lower(), candidate=code))
    unsupported = [m for m in UNSUPPORTED.finditer(text) if not _contextual(text, m.start())
                   and not any(m.start() < end and m.end() > start for start, end in occupied)]
    for match in unsupported:
        evidence.append(dict(source=source, text=original[match.start():match.end()],
                             rule='unsupported_asset', candidate=None))
        candidates.append('UNSUPPORTED')
    return candidates, evidence


def _description_identity(description):
    """Only leading asset statements qualify; never scan a full feature list."""
    segments = []
    for line in re.split(r'\n|(?<=[.!?])\s+', (description or '')[:3000]):
        line = line.strip()
        if not line:
            continue
        if re.match(r'^(?:features?|facilities|amenities|location|contact|price|rent|service\s+charge)\s*:', line, re.I):
            break
        segments.append(line)
        if len(segments) == 3:
            break
    # A type must occur near the start of a self-identifying statement, before
    # narrative or advertising copy. Unknown marketing prose stays unresolved.
    for line in segments:
        if re.match(r'^(?:(?:for\s+(?:sale|rent|lease)|to\s+let|property\s+type)\s*[:\-]?\s*)?'
                    r'(?:(?:this|a|an|the|newly|built|brand|new|luxury|spacious|standard|'
                    r'beautiful|fully|furnished|serviced|purpose|bedrooms?|beds?|\d+)\s+){0,10}'
                    r'(?:semi|detached|terrace|duplex|bungalow|flat|apartment|studio|mini|'
                    r'self|room|penthouse|maisonette|townhouse|mansion|villa|land|plot|block|'
                    r'office|warehouse|shop|showroom|hotel|guest|school|hospital|restaurant|'
                    r'factory|filling|gas|commercial|mixed)\b', _text(line), re.I):
            yield line[:1000]


def _reduce(candidates):
    values = set(candidates)
    # Broad categories can be refined by compatible explicit forms.
    if 'HOUSE' in values and any(TYPES.get(c) and TYPES[c].family in ('HOUSE', 'DUPLEX', 'BUNGALOW') and c != 'HOUSE' for c in values):
        values.discard('HOUSE')
    if 'FLAT_APARTMENT' in values and values & {'MINI_FLAT', 'STUDIO', 'PENTHOUSE', 'MAISONETTE', 'SELF_CONTAINED'}:
        values.discard('FLAT_APARTMENT')
    if 'SELF_CONTAINED' in values and values & {'MINI_FLAT', 'STUDIO'}:
        values.discard('SELF_CONTAINED')
    if 'ROOM' in values and values & {'SELF_CONTAINED', 'MINI_FLAT', 'STUDIO'}:
        values.discard('ROOM')
    if 'COMMERCIAL_OTHER' in values and any(TYPES.get(c) and TYPES[c].category == 'COMMERCIAL' and c != 'COMMERCIAL_OTHER' for c in values):
        values.discard('COMMERCIAL_OTHER')
    if 'LAND_SERVICED' in values:
        values.discard('LAND')
    for form in ('DUPLEX', 'BUNGALOW'):
        if any(c.endswith('_' + form) for c in values):
            values.discard(form)
    return values


def classify(raw_type=None, title=None, description=None, raw_source='PORTAL_TYPE'):
    """Return a bounded, traceable decision. Previous stored types are not inputs.

    Description fallback deliberately favors precision over coverage. Portal
    labels and titles can refine each other; incompatible asset evidence remains
    ambiguous. This function never infers from bedrooms, price or location.
    """
    raw_type = raw_type[:1000] if raw_type else None
    title = (title or '')[:2000]
    raw_source = raw_source if raw_source in ('PORTAL_TYPE', 'BREADCRUMB') else 'PORTAL_TYPE'
    result = Classification(property_type_raw=raw_type,
                            property_type_raw_source=raw_source if raw_type else None,
                            property_type_classified_at=datetime.now(timezone.utc))
    candidates, evidence = [], []
    fields = [(raw_source, raw_type or ''), ('TITLE', title)]
    for source, value in fields:
        found, matches = _scan(value, source)
        candidates.extend(found)
        evidence.extend(matches)
    # A description cannot override a specific primary label/title. It can
    # recover an asset from generic/missing primary information.
    if not candidates or (set(candidates) <= {'HOUSE', 'COMMERCIAL_OTHER', 'FLAT_APARTMENT'} and not title.strip()):
        for segment in _description_identity(description):
            found, matches = _scan(segment, 'DESCRIPTION')
            candidates.extend(found)
            evidence.extend(matches)
            if found:
                fields.append(('DESCRIPTION', segment))
    values = _reduce(candidates)
    combined = ' '.join(_text(value) for _, value in fields)
    # Attachment is independent of form. Limit it to primary evidence, unless
    # only a description supplied the identity. Span handling excludes the
    # 'detached' suffix inside 'semi-detached'.
    attachments, used = set(), []
    for source, value in fields:
        normalized = _text(value)
        for attachment, pattern in ATTACHMENTS:
            for match in pattern.finditer(normalized):
                if _contextual(normalized, match.start()) or any(match.start() < end and match.end() > start for start, end in used):
                    continue
                if attachment == 'TERRACED' and match.group().lower() in ('terrace', 'terraces'):
                    # A patio/roof terrace is not evidence of a row of houses.
                    bare_label = source == 'PORTAL_TYPE' and normalized.strip().lower() == match.group().lower()
                    modifies_form = re.match(r'(?:\s+(?:of|\d+|bedrooms?|beds?)){0,6}\s+(?:duplex|bungalow|house|townhouse)', normalized[match.end():], re.I)
                    if not bare_label and not modifies_form:
                        continue
                attachments.add(attachment)
                used.append(match.span())
                evidence.append(dict(source=source, text=value[match.start():match.end()],
                                     rule='attachment:' + attachment.lower(), attachment=attachment))
        used.clear()
    # A broad land-use label is not evidence of a building's form.
    raw_key = _text(raw_type).strip().lower()
    category_only = {'residential': 'RESIDENTIAL', 'commercial': 'COMMERCIAL',
                     'industrial': 'COMMERCIAL', 'mixed use': 'MIXED_USE'}
    category = category_only.get(raw_key)
    if category:
        evidence.append(dict(source=raw_source, text=raw_type, rule='category_label', category=category))
    if len(values) == 1 and 'UNSUPPORTED' not in values:
        code = next(iter(values))
        definition = TYPES[code]
        if category and category != definition.category and definition.category != 'LAND':
            values.add('CATEGORY_CONFLICT')
            evidence.append(dict(source=raw_source, text=raw_type, rule='category_conflict', category=category))
        else:
            if definition.attachment and len(attachments) > 1:
                code = definition.family
                definition = TYPES[code]
            if code in ('DUPLEX', 'BUNGALOW') and len(attachments) == 1:
                code = next(iter(attachments)) + '_' + code
                definition = TYPES[code]
            result.property_type = code
            result.property_category = definition.category
            result.property_type_family = definition.family
            result.property_asset_scope = definition.scope
            if len(attachments) == 1 and definition.family in ('HOUSE', 'DUPLEX', 'BUNGALOW'):
                result.property_attachment = next(iter(attachments))
            if definition.attachment:
                result.property_attachment = definition.attachment
            if definition.category == 'LAND':
                uses = set()
                for source, value in fields:
                    normalized = _text(value)
                    for name, pattern in LAND_USES.items():
                        for match in pattern.finditer(normalized):
                            if not _contextual(normalized, match.start()):
                                uses.add(name)
                                evidence.append(dict(source=source, text=value[match.start():match.end()],
                                                     rule='land_use:' + name.lower(), land_use=name))
                if len(uses) == 1:
                    result.property_land_use = next(iter(uses))
            if definition.scope not in ('WHOLE_BUILDING', 'LAND_PARCEL'):
                for source, value in fields:
                    match = re.search(r'\b(?:[2-9]\d*|1\d+|two|three|four|five|six|seven|eight|nine|ten|several|multiple)\s+units?\s+of\b', _text(value), re.I)
                    if match and not _contextual(_text(value), match.start()):
                        result.property_asset_scope = 'MULTIPLE_UNITS'
                        evidence.append(dict(source=source, text=value[match.start():match.end()],
                                             rule='multiple_units', asset_scope='MULTIPLE_UNITS'))
            result.property_type_status = 'CLASSIFIED'
    if result.property_type is None:
        result.property_category = category
        result.property_type_status = ('AMBIGUOUS' if len(values) > 1 else
                                       'UNSUPPORTED' if 'UNSUPPORTED' in values else
                                       'UNSUPPORTED' if raw_type and raw_source == 'PORTAL_TYPE' and raw_key not in category_only
                                       and not attachments and not re.fullmatch(r'(?i)(?:property|properties|n/?a|unknown|other)', raw_key) else
                                       'INSUFFICIENT_EVIDENCE')
        if not evidence and raw_type:
            evidence.append(dict(source=raw_source, text=raw_type, rule='unmapped_portal_label'))
    result.property_type_evidence = {'matches': evidence[:40], 'candidates': sorted(values),
                                     'reason': ('attachment_conflict' if len(attachments) > 1 else result.property_type_status.lower())}
    return result


def metadata(value):
    """Stable storage/audit shape, including honest defaults for old objects."""
    data = value if isinstance(value, dict) else vars(value)
    defaults = asdict(Classification())
    defaults.update(property_type_status='LEGACY_UNREVIEWED', property_type_version=None)
    return {key: data.get(key, defaults.get(key)) for key in FIELDS}


def decision_key(value):
    """Classifying the same evidence again does not change its decision time."""
    return {k: v for k, v in metadata(value).items() if k != 'property_type_classified_at'}
