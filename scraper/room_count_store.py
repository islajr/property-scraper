"""Room-count updates and their immutable before/after fact assessment, atomically."""
from uuid import UUID
from psycopg2.extras import Json,execute_values
from scraper import room_counts

FIELDS=('bedrooms','bathrooms','raw_bedrooms','raw_bathrooms','room_metric_sources','room_count_data','room_count_legacy')


def proposal(before,*,listing=None,previous=None):
    row=dict(before)
    if listing is not None:
        row.update(raw_bedrooms=getattr(listing,'raw_bedrooms',None),raw_bathrooms=getattr(listing,'raw_bathrooms',None),
            room_metric_sources=getattr(listing,'room_metric_sources',{}) or {})
    assessment=room_counts.assess(row)
    stored={}
    for field in ('bedrooms','bathrooms'):
        decision=assessment[field]
        existing=before.get(field)
        candidate=decision['value']
        # Historic parser output is neither proof of correctness nor proof of
        # error. Only a fresh, unambiguous labelled metric may replace a number.
        primary=[c for c in decision['claims'] if c['reason'] in
                 {'labelled_primary_metric','consistent_primary_widgets'} and c['usable']]
        fresh_metric=listing is not None and decision['status']=='KNOWN' and any(
            c['value']==candidate for c in primary)
        stored[field]=candidate if existing is None or fresh_metric else existing
        decision['evidence_status']=decision['status']
        decision['stored_value']=stored[field]
        decision['storage_action']=('FILLED_FROM_EVIDENCE' if existing is None and candidate is not None else
            'CORRECTED_FROM_PRIMARY_METRIC' if stored[field]!=existing else 'PRESERVED')
        if stored[field] is not None and (decision['status']!='KNOWN' or stored[field]!=candidate):
            decision['status']='UNVERIFIED'
            decision['next_action']='Preserve the stored number; obtain a labelled primary metric and reconcile conflicting source claims before correcting it.'
            decision['warnings']=sorted(set(decision['warnings']+[
                'stored_number_differs_from_supported_claim' if candidate is not None and stored[field]!=candidate
                else 'stored_number_lacks_unambiguous_support']))
    legacy=before.get('room_count_legacy')
    if legacy is None:
        origin=previous if previous is not None else before if listing is None else {}
        legacy={k:origin.get(k) for k in ('bedrooms','bathrooms')}
    return dict(**stored,
        raw_bedrooms=row.get('raw_bedrooms'),raw_bathrooms=row.get('raw_bathrooms'),
        room_metric_sources=row.get('room_metric_sources') or {},room_count_data=assessment,room_count_legacy=legacy)


def persist_many(cur,rows,*,run_id):
    """Bulk historical repairs from already locked (row, xmin) pairs."""
    import hashlib,json
    run_id=str(UUID(str(run_id)));changes=[];results={}
    for before,version in rows:
        after=proposal(before)
        if all(before.get(k)==v for k,v in after.items()):results[before['id']]=dict(outcome='UNCHANGED');continue
        changes.append((before,version,after))
    if not changes:return results
    fields=','.join(FIELDS)
    applied=execute_values(cur,'UPDATE raw_data.scraped_listings s SET ('+fields+
        ')=(SELECT '+fields+' FROM jsonb_populate_record(NULL::raw_data.scraped_listings,v.data::jsonb)) '
        'FROM (VALUES %s) v(id,data) WHERE s.id=v.id RETURNING s.id,s.xmin::text',
        [(before['id'],Json(after)) for before,_,after in changes],fetch=True)
    versions=dict(applied);audits=[]
    for before,source_version,after in changes:
        a=after['room_count_data']
        facts=dict(kind='ROOM_COUNTS',assessment=a,before={k:before.get(k) for k in FIELDS},after=after,
            source_row_version=source_version,applied_row_version=versions[before['id']])
        audit_hash=hashlib.sha256((a['extractor_sha256']+json.dumps(facts,sort_keys=True)).encode()).hexdigest()
        audits.append((before['id'],a['source_hash'],audit_hash,room_counts.VERSION,run_id,Json(facts)))
    created=execute_values(cur,'''INSERT INTO raw_data.property_fact_assessments
        (listing_id,source_hash,extractor_sha256,rule_version,run_id,facts) VALUES %s RETURNING id,listing_id''',audits,fetch=True)
    for aid,lid in created:results[lid]=dict(outcome='APPLIED',assessment_id=aid,applied_row_version=versions[lid])
    return results


def persist(cur,listing_id,*,run_id,listing=None,previous=None):
    """Read the locked saved source. The caller owns commit/rollback.

    With an observed listing, preserve its corrected primary metric evidence;
    without one, recover only from the fields already stored in this row.
    """
    run_id=str(UUID(str(run_id)))
    cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=%s FOR UPDATE',(listing_id,))
    found=cur.fetchone()
    if found is None:return dict(outcome='MISSING')
    before,source_version=found
    after=proposal(before,listing=listing,previous=previous)
    assessment=after['room_count_data'];legacy=after['room_count_legacy']
    if all(before.get(k)==v for k,v in after.items()):return dict(outcome='UNCHANGED')
    cur.execute('''UPDATE raw_data.scraped_listings SET bedrooms=%s,bathrooms=%s,raw_bedrooms=%s,raw_bathrooms=%s,
        room_metric_sources=%s,room_count_data=%s,room_count_legacy=%s WHERE id=%s RETURNING xmin::text''',
        (after['bedrooms'],after['bathrooms'],after['raw_bedrooms'],after['raw_bathrooms'],Json(after['room_metric_sources']),
         Json(assessment),Json(legacy),listing_id))
    applied_version=cur.fetchone()[0]
    facts=dict(kind='ROOM_COUNTS',assessment=assessment,before={k:before.get(k) for k in FIELDS},after=after,
        source_row_version=source_version,applied_row_version=applied_version)
    # Include before/after in the immutable evidence key: a later correction of
    # a changed numeric column must not reuse an old repair's audit record.
    import hashlib,json
    audit_hash=hashlib.sha256((assessment['extractor_sha256']+json.dumps(facts,sort_keys=True)).encode()).hexdigest()
    cur.execute('''INSERT INTO raw_data.property_fact_assessments
        (listing_id,source_hash,extractor_sha256,rule_version,run_id,facts) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id''',
        (listing_id,assessment['source_hash'],audit_hash,room_counts.VERSION,run_id,Json(facts)))
    return dict(outcome='APPLIED',assessment_id=cur.fetchone()[0],after=after,applied_row_version=applied_version)


def reverse(cur,assessment_id,*,expected_run_id,run_id):
    """Restore only the exact latest source/decision; never overwrite later work."""
    cur.execute('SELECT listing_id,run_id::text,facts FROM raw_data.property_fact_assessments WHERE id=%s AND rule_version=%s',
        (assessment_id,room_counts.VERSION))
    saved=cur.fetchone()
    if not saved or saved[1]!=str(expected_run_id):return 'MISSING'
    lid,_,facts=saved
    cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=%s FOR UPDATE',(lid,))
    row,version=cur.fetchone()
    if version!=facts['applied_row_version'] or any(row.get(k)!=v for k,v in facts['after'].items()):return 'CONCURRENT_CHANGE'
    cur.execute('SELECT id FROM raw_data.property_fact_assessments WHERE listing_id=%s AND rule_version=%s ORDER BY id DESC LIMIT 1',
        (lid,room_counts.VERSION))
    if cur.fetchone()[0]!=assessment_id:return 'CONCURRENT_CHANGE'
    before=facts['before']
    cur.execute('UPDATE raw_data.scraped_listings SET '+','.join(f'{k}=%({k})s' for k in FIELDS)+' WHERE id=%(id)s',
        {**before,'id':lid,**{k:Json(before[k]) if before[k] is not None else None for k in ('room_metric_sources','room_count_data','room_count_legacy')}})
    cur.execute('INSERT INTO raw_data.property_fact_revocations(assessment_id,run_id,reason) VALUES(%s,%s,%s)',
        (assessment_id,str(run_id),'Reverse unchanged room-count repair'))
    return 'REVERSED'
