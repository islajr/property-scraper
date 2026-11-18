"""Advertised area claims, with roles, units and scope kept separate.

A square-metre quantity is not automatically a dwelling's floor area. Original
spans remain available even when a rate, range or unclear role prevents use.
"""
import hashlib
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re

VERSION = 'property-areas-v1'
SOURCE_FIELDS = ('source','external_id','title','description','property_type_raw',
                 'property_type','property_category','property_type_family','property_asset_scope','raw_floor_area')
FIELD_KEYS = ('role','label','value','source')
_AMOUNT = r'(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
_UNIT = r'(?:sq\.?\s*(?:m(?:et(?:er|re)s?)?|f(?:t|eet))\.?|square\s+(?:met(?:er|re)s?|feet|foot)|m[²2]|hectares?|ha|acres?)'
_AREA = re.compile(r'(?<![\w.,])(?P<number>'+_AMOUNT+r')\s*(?P<unit>'+_UNIT+r')(?-i:(?![a-z]))',re.I)
_LAND = re.compile(r'\b(?:land|plot|site)(?:\s+(?:area|size))?\s*[:=\-]?\s*$',re.I)
_FLOOR = re.compile(r'\b(?:floor|built[ -]?up|internal|living|covered|lettable)(?:\s+(?:area|size|space))?\s*[:=\-]?\s*$',re.I)


def source_hash(row):
    fields = row.get('raw_area_fields') or []
    values = [row.get(k) for k in SOURCE_FIELDS]
    values += [f.get(k) for f in fields for k in FIELD_KEYS]
    payload = ''.join('-1:' if v is None else f'{len(str(v))}:{v}' for v in values)
    return hashlib.sha256(payload.encode()).hexdigest()


def extractor_hash():
    from scraper.parsers import area_metrics
    return hashlib.sha256(Path(__file__).read_bytes()+Path(area_metrics.__file__).read_bytes()).hexdigest()


def _factor(unit):
    unit = re.sub(r'[.\s]','',unit.lower())
    if unit in {'ha','hectare','hectares'}:return Decimal('10000')
    if unit in {'acre','acres'}:return Decimal('4046.8564224')
    if 'feet' in unit or 'foot' in unit or unit in {'sqft','sqf'}:return Decimal('0.09290304')
    return Decimal(1)


def _claims(text, origin, row, role=None, trusted=True):
    result=[]
    for match in _AREA.finditer(text or ''):
        start,end=match.span();before=text[max(0,start-100):start];after=text[end:end+85]
        # Resolve labels within a sentence/line, using the nearest explicit label.
        local=re.split(r'[;\n!?]',before)[-1]
        role_context=re.sub(r'\b(?:about|approx(?:imately)?\.?|circa|over|under|above|below|between|from|at least|at most)\s*$','',local,flags=re.I)
        amount=Decimal(match['number'].replace(',',''));sqm=amount*_factor(match['unit'])
        basis='ADVERTISED_ASSET';resolved=role or 'UNSPECIFIED';reasons=[]
        if _FLOOR.search(role_context):resolved='FLOOR'
        elif _LAND.search(role_context) or re.search(r'\b(?:on|sitting on)\s+(?:a\s+)?$',local,re.I):
            resolved='LAND';basis='SITE'
        elif re.match(r'\s*(?:of\s+)?(?:land|plot|site)\b',after,re.I):resolved='LAND'
        elif re.match(r'\s*(?:floor\s+(?:area|space)|of\s+floor\s+space)\b',after,re.I):resolved='FLOOR'
        elif resolved=='UNSPECIFIED' and row.get('property_category')=='LAND':resolved='LAND'
        if re.search(r'\b(?:available\s+(?:spaces|plots|units)|payment\s+plans|residential\s+plot.*commercial\s+plot)\b',text,re.I):reasons.append('multiple_offers_or_sizes_need_scope_review')
        if re.search(r'\b(?:per|each)\s+(?:unit|plot|flat|apartment)\b',local+' '+after,re.I) or re.match(r'\s*(?:each|per\s+(?:unit|plot|flat|apartment))\b',after,re.I):
            basis='PER_UNIT'
        elif resolved=='FLOOR' and row.get('property_asset_scope') in {'MULTIPLE_UNITS','WHOLE_BUILDING'}:
            basis='ASSET_OR_UNIT_UNRESOLVED';reasons.append('multiple_units_floor_basis_unclear')
        if resolved=='LAND' and row.get('property_category')=='RESIDENTIAL' and row.get('property_type_family') in {'APARTMENT','ROOM'}:
            basis='SHARED_SITE_OR_ASSET_UNRESOLVED';reasons.append('site_is_not_dwelling_area')
        # The matched quantity may be the trailing half of a range, bad number,
        # negative quantity or price rate. Keep it as evidence, never silently use.
        if re.search(r'(?:[\d,.]\s*[-–—/]\s*|\b(?:to|between|from|minimum|maximum|upto|up to|over|under|above|below|at least|at most)\s*)$',before,re.I) or re.match(r'\s*(?:[-–—]|to\b)\s*\d',after,re.I):
            reasons.append('range_or_bound')
        if re.search(r'[-\d,.]$',before):reasons.append('negative_or_malformed_number')
        if re.search(r'(?:₦|NGN|USD|\$|price\s*[:=]?)\s*$',before,re.I) or re.match(r'\s*(?:/|per\b)',after,re.I):reasons.append('price_rate_not_asset_area')
        if re.search(r'(?:/|per\s*)$',before,re.I):reasons.append('price_rate_not_asset_area')
        if re.search(r'\b(?:other properties|also available|we (?:also )?have|various locations|our (?:listings|properties)|nearby|neighbouring)\b',local,re.I):reasons.append('other_offer_or_location')
        if re.search(r'\b(?:pool|cinema|home office|balcony|garage|bq|boys.? quarters?|terrace garden)\s*(?:area|size)?\s*[:=]?\s*$',local,re.I):reasons.append('ancillary_feature_area')
        if re.search(r'\b(?:not|no|formerly|previously|was|hypothetical|example)\b',local,re.I):reasons.append('negated_historical_or_example_area')
        if not trusted:reasons.append('source_scope_unverified')
        if sqm<=0 or sqm>Decimal('1000000000000'):reasons.append('nonpositive_or_exceptional_area')
        if resolved=='UNSPECIFIED':reasons.append('area_role_unspecified')
        if basis=='PER_UNIT' and row.get('property_asset_scope')!='UNIT':reasons.append('per_unit_not_total_asset_area')
        if resolved=='FLOOR' and sqm>Decimal('999999.99'):reasons.append('floor_area_exceeds_storage_range')
        precision='APPROXIMATE' if re.search(r'\b(?:about|approx(?:imately)?\.?|circa)\s*$',before,re.I) or before.endswith('~') else 'AS_STATED'
        result.append(dict(role=resolved,basis=basis,original_amount=str(amount),original_unit=match['unit'],
            sqm=str(sqm.normalize()),rounded_sqm=str(sqm.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if abs(sqm)<=Decimal('1000000000000') else None,
            precision=precision,usable=not reasons,reasons=sorted(set(reasons)),
            evidence=dict(source=origin,text=text[max(0,start-100):end+85],span=[start,end],literal=match[0])))
    return result


def assess(row):
    claims=[]
    for key in ('title','description'):
        claims.extend(_claims(row.get(key) or '',key.upper(),row))
    if row.get('raw_floor_area'):
        claims.extend(_claims(row['raw_floor_area'],'EXPLICIT_FLOOR_FIELD',row,role='FLOOR'))
    for item in row.get('raw_area_fields') or []:
        # Unknown/legacy field scope is retained but does not certify a role.
        trusted=item.get('source') in {'PRIMARY_LABEL','PRIMARY_SCHEMA_PROPERTY'}
        label=item.get('label') or '';value=item.get('value') or ''
        claims.extend(_claims(label+': '+value,item.get('source') or 'UNKNOWN_FIELD',row,
            role=item.get('role') if item.get('role') in {'LAND','FLOOR'} else None,trusted=trusted))
    answer=dict(version=VERSION,source_hash=source_hash(row),extractor_sha256=extractor_hash(),claims=claims)
    for name,role in (('floor_area_sqm','FLOOR'),('land_area_sqm','LAND')):
        relevant=[c for c in claims if c['role']==role];usable=[c for c in relevant if c['usable']]
        values={c['rounded_sqm'] for c in usable}
        conflict=len(values)>1 or bool(relevant and any(not c['usable'] for c in relevant))
        status='AMBIGUOUS' if conflict else 'KNOWN' if len(values)==1 else 'UNKNOWN'
        answer[name]=dict(status=status,value=next(iter(values)) if status=='KNOWN' else None,
            basis=sorted({c['basis'] for c in usable}),next_action=None if status=='KNOWN' else
            'Check the primary listing for one explicit area, its land/floor role and asset or per-unit basis.')
    return answer
