"""Preserve stored areas and audit every source-bound interpretation atomically."""
import hashlib
import json
from decimal import Decimal
from uuid import UUID
from psycopg2.extras import Json,execute_values
from scraper import area_measurements

FIELDS=('floor_area_sqm','floor_area_source','land_area_sqm','raw_floor_area','raw_area_fields','area_data','area_legacy')


def proposal(before,*,listing=None,previous=None):
    row=dict(before)
    if listing is not None:
        row.update(raw_floor_area=getattr(listing,'raw_floor_area',None),
                   raw_area_fields=getattr(listing,'raw_area_fields',[]) or [])
    assessment=area_measurements.assess(row);after={}
    for name in ('floor_area_sqm','land_area_sqm'):
        decision=assessment[name];old=before.get(name);candidate=decision['value']
        value=candidate if old is None else old
        decision.update(evidence_status=decision['status'],stored_value=None if value is None else str(value),
                        storage_action='FILLED_FROM_EVIDENCE' if old is None and candidate is not None else 'PRESERVED')
        # Existing values survive absent, changed or conflicting adverts. No
        # automatic correction is authorized by merely rerunning a text parser.
        if value is not None and (candidate is None or abs(Decimal(str(value))-Decimal(candidate))>Decimal('.10')):
            decision['status']='UNVERIFIED'
        after[name]=None if value is None else str(value)
    prior=before.get('area_data') or {}
    if prior.get('source_hash')==assessment['source_hash'] and prior.get('extractor_sha256')==assessment['extractor_sha256']:
        for name in ('floor_area_sqm','land_area_sqm'):
            old=prior.get(name) or {};new=assessment[name]
            if {k:v for k,v in old.items() if k!='storage_action'}=={k:v for k,v in new.items() if k!='storage_action'}:
                new['storage_action']=old.get('storage_action','PRESERVED')
    legacy=before.get('area_legacy')
    if legacy is None:
        origin=previous if previous is not None else before if listing is None else {}
        legacy={k:origin.get(k) for k in ('floor_area_sqm','floor_area_source','land_area_sqm')}
    after.update(floor_area_source=before.get('floor_area_source') or 'NONE',
                 raw_floor_area=row.get('raw_floor_area'),raw_area_fields=row.get('raw_area_fields') or [],
                 area_data=assessment,area_legacy=legacy)
    if before.get('floor_area_sqm') is None and after['floor_area_sqm'] is not None:after['floor_area_source']='PORTAL'
    return after


def persist_many(cur,rows,*,run_id,observations=None,previous=None):
    run_id=str(UUID(str(run_id)));changes=[];results={}
    for before,version in rows:
        observed=(observations or {}).get(before['id'])
        if observed is not None and (observed.source,observed.external_id)!=(before['source'],before['external_id']):
            raise ValueError('Area observation identity differs from the saved listing')
        after=proposal(before,listing=observed,previous=(previous or {}).get(before['id']))
        comparable={**before,**{k:None if before.get(k) is None else str(before[k]) for k in ('floor_area_sqm','land_area_sqm')}}
        if all(comparable.get(k)==v for k,v in after.items()):results[before['id']]=dict(outcome='UNCHANGED');continue
        changes.append((before,version,after))
    if not changes:return results
    fields=','.join(FIELDS)
    versions=dict(execute_values(cur,'UPDATE raw_data.scraped_listings s SET ('+fields+
        ')=(SELECT '+fields+' FROM jsonb_populate_record(NULL::raw_data.scraped_listings,v.data::jsonb)) '
        'FROM (VALUES %s) v(id,data) WHERE s.id=v.id RETURNING s.id,s.xmin::text',
        [(before['id'],Json(after)) for before,_,after in changes],fetch=True))
    audits=[]
    for before,version,after in changes:
        a=after['area_data'];facts=dict(kind='AREA_MEASUREMENTS',assessment=a,
            before={k:before.get(k) for k in FIELDS},after=after,source_row_version=version,
            applied_row_version=versions[before['id']])
        audit_hash=hashlib.sha256((a['extractor_sha256']+json.dumps(facts,sort_keys=True,default=str)).encode()).hexdigest()
        audits.append((before['id'],a['source_hash'],audit_hash,area_measurements.VERSION,run_id,Json(facts)))
    created=execute_values(cur,'''INSERT INTO raw_data.property_fact_assessments
        (listing_id,source_hash,extractor_sha256,rule_version,run_id,facts) VALUES %s RETURNING id,listing_id''',audits,fetch=True)
    for aid,lid in created:results[lid]=dict(outcome='APPLIED',assessment_id=aid,applied_row_version=versions[lid])
    return results


def persist(cur,listing_id,*,run_id,listing=None,previous=None):
    cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=%s FOR UPDATE',(listing_id,))
    found=cur.fetchone()
    if found is None:return dict(outcome='MISSING')
    return persist_many(cur,[found],run_id=run_id,observations={listing_id:listing} if listing is not None else None,
                        previous={listing_id:previous} if previous is not None else None)[listing_id]


def equal_fields(row,values):
    for key,value in values.items():
        saved=row.get(key)
        if key in {'floor_area_sqm','land_area_sqm'} and saved is not None and value is not None:
            if Decimal(str(saved))!=Decimal(str(value)):return False
        elif saved!=value:return False
    return True


def reverse(cur,assessment_id,*,expected_run_id,run_id):
    cur.execute('SELECT listing_id,run_id::text,facts FROM raw_data.property_fact_assessments WHERE id=%s AND rule_version=%s',
                (assessment_id,area_measurements.VERSION));saved=cur.fetchone()
    if not saved or saved[1]!=str(expected_run_id):return 'MISSING'
    lid,_,facts=saved
    cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=%s FOR UPDATE',(lid,))
    found=cur.fetchone()
    if not found:return 'MISSING'
    row,version=found
    if version!=facts['applied_row_version'] or not equal_fields(row,facts['after']):return 'CONCURRENT_CHANGE'
    cur.execute('SELECT id FROM raw_data.property_fact_assessments WHERE listing_id=%s AND rule_version=%s ORDER BY id DESC LIMIT 1',
                (lid,area_measurements.VERSION))
    if cur.fetchone()[0]!=assessment_id:return 'CONCURRENT_CHANGE'
    fields=','.join(FIELDS)
    cur.execute('UPDATE raw_data.scraped_listings SET ('+fields+')=(SELECT '+fields+
        ' FROM jsonb_populate_record(NULL::raw_data.scraped_listings,%s::jsonb)) WHERE id=%s',(Json(facts['before']),lid))
    cur.execute('INSERT INTO raw_data.property_fact_revocations(assessment_id,run_id,reason) VALUES(%s,%s,%s)',
                (assessment_id,str(run_id),'Reverse unchanged advertised-area assessment'))
    return 'REVERSED'
