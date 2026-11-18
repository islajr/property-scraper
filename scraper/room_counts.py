"""Bedroom and bathroom claims with explicit confidence, context and source basis.

Legacy numeric columns are never supporting evidence. Toilets and ensuite wording
never manufacture bathroom quantities. Values describe adverts, not inspections.
"""
import hashlib
import json
from pathlib import Path
import re
from scraper import property_counts,property_count_profile,property_reviews

VERSION='property-rooms-v1'
_WORDS={'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,
        'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,'seventeen':17,
        'eighteen':18,'nineteen':19,'twenty':20}
_NUMBER=r'(?:\d+|'+'|'.join(_WORDS)+r')'
_NOUN={'bedrooms':r'bed[ -]*rooms?|beds?', 'bathrooms':r'bath[ -]*rooms?|baths?'}
_PRIMARY={'PRIMARY_LABEL','PRIMARY_ICON','PRIMARY_SCHEMA_PROPERTY'}


def extractor_hash():
    from scraper.parsers import room_metrics
    return hashlib.sha256(Path(__file__).read_bytes()+Path(room_metrics.__file__).read_bytes()+
        Path(property_counts.__file__).read_bytes()+Path(property_count_profile.__file__).read_bytes()+
        property_reviews.review_fingerprint()).hexdigest()


def source_hash(row):
    sources=row.get('room_metric_sources') or {}
    values=[row.get(k) for k in ('source','external_id','title','description','property_type_raw',
        'raw_bedrooms','raw_bathrooms','property_type','property_asset_scope')]+[sources.get(k) for k in ('bedrooms','bathrooms')]
    payload=''.join('-1:' if v is None else f'{len(v)}:{v}' for v in values)
    return hashlib.sha256(payload.encode()).hexdigest()


def _number(value):
    return int(value) if value.isdigit() else _WORDS[value.lower()]


def _basis(row,context=''):
    if re.search(r'\b(?:per\s+(?:unit|flat|apartment|dwelling)|each\s+(?:flat|apartment|dwelling|unit))\b',context,re.I):
        return 'PER_DWELLING'
    if row.get('property_type')=='ROOM' or re.search(r'\b(?:shared\s+(?:flat|apartment)|room\s+in\s+a)\b',row.get('title') or '',re.I):
        return 'HOST_OR_ROOM_UNRESOLVED'
    if row.get('_room_multi_asset') or row.get('property_asset_scope') in {'MULTIPLE_UNITS','WHOLE_BUILDING'}:
        return 'ASSET_OR_UNIT_UNRESOLVED'
    if row.get('property_category')=='RESIDENTIAL' and row.get('property_type_family') in {'HOUSE','DUPLEX','BUNGALOW','APARTMENT','ROOM'}:
        return 'PER_DWELLING'
    if row.get('property_category')=='RESIDENTIAL':return 'AS_ADVERTISED'
    return 'ASSET_OR_UNIT_UNRESOLVED'


def _raw_claim(row,field):
    raw=row.get('raw_'+field)
    if raw is None or not raw.strip():return None
    text=raw.strip();noun=_NOUN[field]
    match=re.fullmatch(rf'({_NUMBER})(?:\s*(?:{noun}))?',text,re.I)
    reverse=re.fullmatch(rf'(?:{noun})\s*[:\-]?\s*({_NUMBER})',text,re.I)
    evidence=dict(source='PORTAL_FIELD',text=raw,field='raw_'+field,method=(row.get('room_metric_sources') or {}).get(field))
    if not match and not reverse:return dict(value=None,basis=_basis(row),evidence=evidence,usable=False,reason='malformed_or_multiple_field_values')
    m=match or reverse;value=_number(m.group(1))
    trusted=evidence['method'] in _PRIMARY or bool(re.search(rf'\b(?:{noun})\b',text,re.I))
    usable=trusted and 0<=value<=20
    reason='labelled_primary_metric' if usable else 'unverified_numeric_field' if not trusted else 'unusual_quantity_requires_review'
    if value==0 and not (field=='bedrooms' and row.get('property_type')=='STUDIO'):
        usable=False;reason='zero_may_be_a_portal_placeholder'
    return dict(value=value,basis=_basis(row),evidence=evidence,usable=usable,reason=reason)


def _bathroom_text(row):
    claims=[]
    pattern=re.compile(rf'(?<![\w.\d/+\-])(?P<n>{_NUMBER})[ -]*(?P<label>{_NOUN["bathrooms"]})\b',re.I)
    for source,original,limit in [('TITLE',row.get('title') or '',2000),('DESCRIPTION',row.get('description') or '',20000)]:
        text=original[:limit]
        inventory=re.search(r'\b(?:other\s+properties|also\s+available|contact\s+(?:us|me)|call\s+(?:us|me))\b',text,re.I)
        if inventory:text=text[:inventory.start()]
        for m in pattern.finditer(text):
            before=text[max(0,m.start()-100):m.start()];after=text[m.end():m.end()+100]
            if re.search(r'\b(?:near|opposite|beside|suitable\s+for|ideal\s+for|not|without|no)\b[^.;\n]*$',before,re.I):continue
            value=_number(m['n']);flags=[]
            if re.search(r'\b(?:to|or|and|between|at\s+least|more\s+than|less\s+than|about|approximately)\s*$|\d+\s+$',before,re.I):flags.append('range_or_combined_quantity')
            if re.search(r'\b(?:bq|boys?[’\x27]?\s+quarters?|guest\s+house|staff\s+quarters?)\b[^.;\n:]*$',before,re.I):flags.append('ancillary_asset')
            if re.match(r'\s+(?:in|for)\s+(?:the\s+)?(?:bq|staff\s+quarters)',after,re.I):flags.append('ancillary_asset')
            if not 1<=value<=20:flags.append('unusual_quantity_requires_review')
            if len(original)>limit:flags.append('truncated_source')
            # A numbered list marker is not the bathroom quantity.
            if re.search(r'(?:^|\n)\s*\d+[.)]\s*$',before):flags.append('possible_list_number')
            claims.append(dict(value=value,basis=_basis(row,before+' '+after),usable=not flags,
                reason='explicit_bathroom_wording' if not flags else ','.join(flags),
                evidence=dict(source=source,start=m.start(),end=m.end(),text=m.group(),context=before+m.group()+after)))
    return claims


def assess(row):
    row=dict(row)
    profile=property_count_profile.profile_text(row.get('title'),row.get('description'))
    row['_room_multi_asset']=any(c['source']=='TITLE' and not c['review_flags'] and (c['entity']=='BUILDING' or c['entity'] in {'DWELLING_UNIT','UNSPECIFIED_UNIT'} and c['quantity']['minimum']>1) for c in profile['candidates'])
    claims={'bedrooms':[],'bathrooms':_bathroom_text(row)}
    for field in claims:
        raw=_raw_claim(row,field)
        if raw:claims[field].append(raw)
    assessment=property_counts.assess_counts(row.get('title'),row.get('description'),source=row.get('source'),
        external_id=row.get('external_id'),raw_type=row.get('property_type_raw'))
    for o in assessment['observations']:
        if o['entity']=='BEDROOM' and o['relationship']=='BEDROOMS_PER_DWELLING':
            exact=o['quantity']['kind']=='EXACT'
            claims['bedrooms'].append(dict(value=o['quantity']['minimum'],basis='PER_DWELLING',
                parent_key=o['parent_key'],usable=o['decision']=='ACCEPT' and exact,reason=o['rule'],evidence=o['evidence']))
    result={}
    alternatives=profile['offer_alternative_hint']
    review=property_reviews.matching_review(row.get('source'),row.get('external_id'),row.get('property_type_raw'),row.get('title'),row.get('description'))
    alternatives=alternatives or bool(review and review.get('multiple_offers'))
    for field,items in claims.items():
        accepted=[c for c in items if c['usable'] and c['basis'] in {'PER_DWELLING','AS_ADVERTISED'}]
        values={c['value'] for c in accepted}
        parents={c.get('parent_key') for c in accepted if c.get('parent_key')}
        warnings=sorted({c['reason'] for c in items if not c['usable']})
        status='KNOWN' if len(values)==1 else 'AMBIGUOUS' if len(values)>1 else 'REVIEW_REQUIRED' if items else 'UNKNOWN'
        value=next(iter(values)) if status=='KNOWN' else None
        if len(values)>1 and len(parents)>1:status='MIXED_LAYOUT'
        if row.get('property_category')=='LAND':status='NOT_APPLICABLE';value=None
        elif row.get('property_type')=='ROOM':status='REVIEW_REQUIRED' if items else 'UNKNOWN';value=None
        elif alternatives:status='REVIEW_REQUIRED';value=None;warnings.append('offer_basis_unresolved')
        # Unknown multi-unit/raw totals cannot contradict a proven per-unit
        # layout, but must remain visible as unresolved source claims.
        result[field]=dict(value=value,status=status,basis=('PER_DWELLING' if any(c['basis']=='PER_DWELLING' for c in accepted) else 'AS_ADVERTISED') if value is not None else 'UNRESOLVED',
            claims=items,warnings=warnings,next_action=None if status in {'KNOWN','NOT_APPLICABLE'} else
            'Inspect a labelled primary detail metric or explicit per-unit wording; keep toilets, BQ, host accommodation and separate offers distinct.')
    return dict(rule_version=VERSION,source_hash=source_hash(row),extractor_sha256=extractor_hash(),**result)
