"""Evidence-bearing count assessments; no I/O and no modification of listing fields."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from scraper import property_count_profile

VERSION = 'property-counts-v2'
_DWELLING = r'(?:mini[ -]*flats?|flats?|apartments?|houses?|duplex(?:es)?|bungalows?|maisonettes?)'


def source_hash(title, description, raw_type=None):
    title, description = title or '', description or ''
    payload=f'{len(title)}:{title}{len(description)}:{description}'
    if raw_type is not None:payload+=f'{len(raw_type)}:{raw_type}'
    return hashlib.sha256(payload.encode()).hexdigest()


def extractor_hash():
    from scraper.property_reviews import review_fingerprint
    return hashlib.sha256(Path(__file__).read_bytes()+Path(property_count_profile.__file__).read_bytes()+review_fingerprint()).hexdigest()


def _interpret(candidate, original):
    c = candidate
    entity, q = c['entity'], c['quantity']
    before, after = original[:c['start']], original[c['end']:]
    if c['review_flags']:
        return entity, 'UNRESOLVED', None, 'flagged_source_context'
    if q['minimum'] < 1 or (entity == 'BEDROOM' and q['minimum'] > 20) or q['minimum'] > 10000:
        return entity, 'UNRESOLVED', None, 'quantity_requires_review'
    # Description recovery only uses early identity text, not agent inventories.
    if c['source']=='DESCRIPTION' and (c['start'] > 500 or re.search(
            r'\b(?:features?|amenities|facilities|contact|other\s+properties|price)\s*:', before, re.I)):
        return entity, 'UNRESOLVED', None, 'description_identity_not_established'
    if entity == 'BEDROOM':
        if re.match(rf'[ -]+{_DWELLING}\b|\s*(?:each|per\s+(?:unit|flat|dwelling))\b', after, re.I):
            return entity, 'BEDROOMS_PER_DWELLING', 'dwelling', 'explicit_bedroom_layout'
    if entity == 'UNSPECIFIED_UNIT' and re.match(rf'\s+of\s+(?:(?:a|\d+)\s+)?(?:\d+[ -]*bedrooms?[ -]+)?{_DWELLING}\b', after, re.I):
        entity = 'DWELLING_UNIT'
    if entity in {'DWELLING_UNIT','UNSPECIFIED_UNIT'} and re.search(r'\bblock\s+of\s*$', before, re.I):
        if entity == 'DWELLING_UNIT':
            return entity, 'CONTAINED_UNIT', 'primary_building', 'explicit_block_contents'
    if entity == 'DWELLING_UNIT' and re.search(r'\b(?:one|a|whole|entire)\s+(?:block|building)\s+(?:containing|comprising)\s*$', before, re.I):
        return entity, 'CONTAINED_UNIT', 'primary_building', 'explicit_building_contents'
    if entity in {'DWELLING_UNIT','BUILDING','ROOM'}:
        if entity=='ROOM' and not re.match(r'\s+in\s+(?:a\s+)?(?:shared\s+(?:flat|apartment|house)|(?:one|two|three|\d+)\s+bed(?:rooms?)?)\b',after,re.I):
            return entity,'UNRESOLVED',None,'room_or_dwelling_basis_needs_review'
        if re.search(r'\b(?:sold|rented|leased|taken)\s+together\b|\bat\s+once\b', after[:100], re.I):
            return entity, 'OFFERED_ASSET', None, 'explicit_bundle'
        if 'AVAILABILITY' in c['relation_hints'] and re.search(r'\b(?:development|stock|remaining)\b', c['context'], re.I):
            return entity, 'DEVELOPMENT_AVAILABILITY', 'development', 'explicit_availability'
        if (c['source']=='TITLE' and q==dict(kind='EXACT',minimum=1,maximum=1)
                and c['start'] < 40 and not re.search(r'\b(?:with|and|plus|containing|includes?|bq)\b', before, re.I)
                and not re.search(rf'\b(?:{_DWELLING}|rooms?|buildings?|blocks?)\b|&',before,re.I)
                and 'AVAILABILITY' not in c['relation_hints']):
            return entity, 'OFFERED_ASSET', None, 'explicit_single_primary_asset'
    return entity, 'UNRESOLVED', None, 'entity_or_relationship_needs_review'


def assess_counts(title=None, description=None, *, source=None, external_id=None, raw_type=None):
    profile = property_count_profile.profile_text(title,description)
    observations = []
    for c in profile['candidates']:
        original = (title or '') if c['source']=='TITLE' else (description or '')
        entity,relationship,parent,rule = _interpret(c,original)
        accepted = relationship != 'UNRESOLVED' and not profile['offer_alternative_hint'] and not profile['truncated']
        start,end=max(0,c['start']-100),min(len(original),c['end']+120)
        observations.append(dict(entity=entity,quantity=c['quantity'],relationship=relationship,
                                 parent_key=parent,offer_key='primary' if accepted and relationship!='DEVELOPMENT_AVAILABILITY' else None,
                                 decision='ACCEPT' if accepted else 'HOLD',rule=rule,
                                 evidence=[dict(source=c['source'],start=start,end=end,text=original[start:end],
                                                count_start=c['start'],count_end=c['end'],count_text=c['text'])],
                                 review_flags=c['review_flags']))
    # Until layout/offer parents are established, differing values are not one
    # verified per-dwelling fact. Keep all claims rather than choosing a source.
    groups = defaultdict(set)
    for o in observations:
        if o['relationship']!='UNRESOLVED':
            groups[(o['entity'],o['relationship'],o['parent_key'])].add(json.dumps(o['quantity'],sort_keys=True))
    for o in observations:
        if len(groups.get((o['entity'],o['relationship'],o['parent_key']),())) > 1:
            o.update(decision='HOLD',rule='conflicting_or_mixed_quantities')
    dwelling_counts={json.dumps(c['quantity'],sort_keys=True) for c in profile['candidates']
                     if c['entity']=='DWELLING_UNIT'}
    dwelling_forms={('flat' if 'flat' in c['noun'].lower() or 'apartment' in c['noun'].lower()
                      else c['noun'].lower().rstrip('s')) for c in profile['candidates']
                     if c['entity']=='DWELLING_UNIT'}
    if len(dwelling_counts)>1 or len(dwelling_forms)>1:
        for o in observations:
            if o['relationship']=='BEDROOMS_PER_DWELLING':
                o.update(decision='HOLD',rule='layout_parent_needs_review')
            if o['relationship']=='OFFERED_ASSET' and o['entity']=='DWELLING_UNIT':
                o.update(decision='HOLD',rule='portfolio_components_need_offer_parents')
    for o in observations:
        if o['decision']=='ACCEPT' and o['relationship']=='OFFERED_ASSET' and o['entity']=='DWELLING_UNIT':
            source=o['evidence'][0]['source']
            text=(title or '') if source=='TITLE' else (description or '')[:500]
            forms={('flat' if m.group().lower().startswith(('flat','apartment')) else m.group().lower().rstrip('s'))
                   for m in re.finditer(rf'\b{_DWELLING}\b',text,re.I)}
            if len(forms)>1:o.update(decision='HOLD',rule='multiple_forms_need_offer_parents')
    title_assets=[o for o in observations if o['evidence'][0]['source']=='TITLE'
                  and o['entity'] in {'BUILDING','DWELLING_UNIT','UNSPECIFIED_UNIT'}
                  and o['relationship'] not in {'CONTAINED_UNIT','DEVELOPMENT_AVAILABILITY'}]
    if len(title_assets)>1:
        for o in title_assets:
            if o['rule']=='explicit_single_primary_asset':
                o.update(decision='HOLD',rule='multiple_assets_need_offer_parents')
    # Compatible repeated claims become one observation with multiple sources.
    dedup = {}
    for o in observations:
        key = json.dumps({k:v for k,v in o.items() if k not in ('evidence','review_flags')},sort_keys=True)
        if key in dedup:
            dedup[key]['evidence'].extend(o['evidence'])
            dedup[key]['review_flags']=sorted(set(dedup[key]['review_flags']+o['review_flags']))
        else:
            dedup[key]=o
    observations=list(dedup.values())
    from scraper.property_reviews import matching_review
    review=matching_review(source,external_id,raw_type,title,description)
    if review:
        # Review decisions replace only the same relationship in this exact snapshot.
        # Mixed layout claims must not retain the generic unqualified bedroom parent.
        roles={c['relationship'] for c in review['counts']}
        if review['case_id']=='R21':roles.add('BEDROOMS_PER_DWELLING')
        for o in observations:
            if o['relationship'] in roles:
                o.update(decision='HOLD',rule='superseded_by_source_bound_review')
        for c in review['counts']:
            observations.append(dict(entity=c['entity'],quantity=dict(kind='EXACT',minimum=c['quantity'],maximum=c['quantity']),
                relationship=c['relationship'],parent_key=c['parent_key'],offer_key='primary' if c['relationship']!='UNRESOLVED' else None,decision='ACCEPT' if c['relationship']!='UNRESOLVED' else 'HOLD',
                rule='human_review:'+review['case_id'],review_flags=[],evidence=[dict(source='USER_REVIEW',
                text=review['note'],evidence_sha256=review['evidence_sha256'],case_id=review['case_id'])]))
    questions=[]
    if not any(o['decision']=='ACCEPT' and o['relationship']=='OFFERED_ASSET' for o in observations):
        questions.append(dict(reason='offered_quantity_unestablished',next_action='Establish what is offered and whether the quantity is explicit or not applicable.'))
    if any(o['decision']=='HOLD' for o in observations):
        questions.append(dict(reason='held_claims',next_action='Review source claims and assign entity, relationship, and parent/offer references.'))
    if any(o['decision']=='HOLD' and o['entity'] in {'BUILDING','DWELLING_UNIT','UNSPECIFIED_UNIT'} and o['quantity']['minimum']>1 for o in observations):
        questions.append(dict(reason='asset_quantity_relationship_unestablished',next_action='Establish whether listed assets are bundled, individually offered, contained units or development availability.'))
    if profile['offer_alternative_hint']:
        questions.append(dict(reason='offer_alternatives',next_action='Link individual and bundle counts to their respective offer and price evidence.'))
    if profile['truncated']:
        questions.append(dict(reason='truncated_evidence',next_action='Inspect full saved source text before accepting counts.'))
    if review:
        questions.extend(dict(reason='human_review_follow_up',next_action=q) for q in review['questions'])
    return dict(rule_version=VERSION,source_hash=source_hash(title,description,raw_type),
                state='NO_PATTERN_MATCH' if not observations else 'REVIEW_REQUIRED' if questions else 'COUNTS_FOUND',
                observations=observations,questions=questions,derived_totals=False)
