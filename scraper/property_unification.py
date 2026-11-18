"""Frozen previews and bounded atomic batches for the unified research contract."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import UUID
from psycopg2.extras import Json, execute_values
from scraper import property_counts, property_facts, property_types, room_counts, room_count_store
from scraper.classification_artifact import database_fingerprint, classifier_fingerprint, ReviewError


def fingerprint():
    return hashlib.sha256((classifier_fingerprint()+property_counts.extractor_hash()+
        property_facts.extractor_hash()+room_counts.extractor_hash()).encode()+Path(__file__).read_bytes()+Path(room_count_store.__file__).read_bytes()).hexdigest()


def proposal(row):
    identity=dict(source=row['source'],external_id=row['external_id'])
    return dict(classification=asdict(property_types.classify(row.get('property_type_raw'),row.get('title'),
        row.get('description'),row.get('property_type_raw_source'),**identity)),
        counts=property_counts.assess_counts(row.get('title'),row.get('description'),raw_type=row.get('property_type_raw'),**identity),
        facts=property_facts.assess_facts(row.get('title'),row.get('description'),raw_type=row.get('property_type_raw'),**identity))


def preview(conn, output):
    """One read-only snapshot; report/summary are private and atomically replaced."""
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    conn.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
    counts=Counter();states=Counter();types=Counter();temporary=None
    digest=hashlib.sha256()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SELECT transaction_timestamp(),current_setting('transaction_read_only')")
            snapshot,mode=cur.fetchone()
            if mode!='on':raise ReviewError('Read-only snapshot required')
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=output.parent,delete=False) as report:
            temporary=Path(report.name)
            with conn.cursor(name='property_unification_preview') as cur:
                cur.itersize=500
                cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s ORDER BY id')
                for row,version in cur:
                    p=proposal(row)
                    record=dict(id=row['id'],source=row['source'],external_id=row['external_id'],
                        title=row.get('title'),url=row.get('url'),
                        row_version=version,previous=property_types.metadata(row),proposed=p)
                    line=json.dumps(record,sort_keys=True,ensure_ascii=False,default=str)+'\n'
                    report.write(line);digest.update(line.encode())
                    counts['scanned']+=1
                    counts['accepted_counts']+=any(o['decision']=='ACCEPT' for o in p['counts']['observations'])
                    counts['multiple_offers']+=p['facts']['multiple_offers']
                    counts['with_features']+=bool(p['facts']['features'])
                    counts['reviewed_listings']+=bool(p['facts']['review_case'])
                    states[p['classification']['property_type_status']]+=1
                    types[p['classification']['property_type'] or '(unresolved)']+=1
        temporary.replace(output);temporary=None
        summary=dict(report_kind='property_unification_preview',read_only=True,
            rule_version='property-research-v1',database_fingerprint=database_fingerprint(conn),
            code_sha256=fingerprint(),report_sha256=digest.hexdigest(),snapshot_at=str(snapshot),
            counts=dict(counts),statuses=dict(states),types=dict(types))
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=output.parent,delete=False) as report:
            temporary=Path(report.name);report.write(json.dumps(summary,indent=2,sort_keys=True)+'\n')
        temporary.replace(output.with_suffix('.summary.json'));temporary=None
        return summary
    finally:
        conn.rollback()
        if temporary:temporary.unlink(missing_ok=True)


def load_preview(path):
    """Read the exact bytes once. Apply never reopens a file after validation."""
    path=Path(path);data=path.read_bytes();summary=json.loads(path.with_suffix('.summary.json').read_text())
    if summary.get('report_kind')!='property_unification_preview' or summary.get('read_only') is not True:
        raise ReviewError('Use a unified read-only preview')
    if hashlib.sha256(data).hexdigest()!=summary.get('report_sha256') or fingerprint()!=summary.get('code_sha256'):
        raise ReviewError('Preview bytes or current rules differ; regenerate the preview')
    records=[json.loads(line) for line in data.splitlines()]
    ids=[r['id'] for r in records]
    if ids!=sorted(set(ids)) or any(type(i) is not int or i<1 for i in ids) or len(ids)!=summary['counts']['scanned']:
        raise ReviewError('Preview IDs or count are invalid')
    return summary,records


def _store_counts(cur, rows, run_id):
    if not rows:return
    values=[(r['id'],property_counts.VERSION,property_counts.extractor_hash(),p['counts']['source_hash'],
        r['row_version'],run_id,p['counts']['state'],Json(p['counts']['questions'])) for r,p in rows]
    created=execute_values(cur,'''INSERT INTO raw_data.property_count_assessments
        (listing_id,rule_version,extractor_sha256,source_hash,source_row_version,run_id,state,questions)
        VALUES %s ON CONFLICT DO NOTHING RETURNING id,listing_id''',values,fetch=True)
    by_id={r['id']:p for r,p in rows};observations=[];decisions={}
    for assessment_id,lid in created:
        for ordinal,o in enumerate(by_id[lid]['counts']['observations']):
            q=o['quantity']
            observations.append((assessment_id,ordinal,o['entity'],q['kind'],q['minimum'],q['maximum'],
                o['relationship'],o['parent_key'],o['offer_key'],Json(o['evidence']),Json(o['review_flags']),o['rule']))
            decisions[assessment_id,ordinal]=o
    if observations:
        created=execute_values(cur,'''INSERT INTO raw_data.property_count_observations
            (assessment_id,ordinal,counted_entity,quantity_kind,quantity_min,quantity_max,
             relationship,parent_key,offer_key,evidence,review_flags,rule) VALUES %s
            RETURNING id,assessment_id,ordinal''',observations,fetch=True)
        execute_values(cur,'''INSERT INTO raw_data.property_count_decisions
            (observation_id,decision,reason,run_id) VALUES %s''',
            [(oid,decisions[aid,ordinal]['decision'],decisions[aid,ordinal]['rule'],run_id) for oid,aid,ordinal in created])


def apply_batch(conn, summary, records, run_id, *, write=False, max_records=100, ids=()):
    """Guard identities, xmin, old decisions, recomputed proposals; commit one batch.

    Counts, features, classifications, audit and receipts share a transaction.
    A retry cannot recreate revoked count decisions. Changed rows need a new preview.
    """
    if not 1<=max_records<=500:raise ValueError('Batch size must be between 1 and 500')
    run_id=str(UUID(str(run_id)))
    if fingerprint()!=summary['code_sha256'] or database_fingerprint(conn)!=summary['database_fingerprint']:
        raise ReviewError('Database or rules differ from preview')
    # Rebind in-memory artifacts too: callers cannot substitute different records.
    digest=hashlib.sha256(''.join(json.dumps(r,sort_keys=True,ensure_ascii=False,default=str)+'\n' for r in records).encode()).hexdigest()
    if digest!=summary['report_sha256']:raise ReviewError('Preview records changed after validation')
    manifest={k:summary[k] for k in ('database_fingerprint','code_sha256','report_sha256')}
    manifest['ids']=sorted(set(ids))
    conn.set_session(readonly=not write,isolation_level='READ COMMITTED',autocommit=False)
    outcomes=Counter();eligible=[]
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='3s'")
            cur.execute("SET LOCAL statement_timeout='45s'")
            if write:
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('property-unification:'+run_id,))
                cur.execute('SELECT manifest FROM raw_data.property_unification_runs WHERE run_id=%s',(run_id,))
                old=cur.fetchone()
                if old and old[0]!=manifest:raise ReviewError('Run ID already belongs to another preview or selection')
                if not old:cur.execute('INSERT INTO raw_data.property_unification_runs(run_id,manifest) VALUES(%s,%s)',(run_id,Json(manifest)))
            cur.execute("SELECT 1 FROM raw_data.property_unification_runs WHERE manifest->>'original_run_id'=%s LIMIT 1",(run_id,))
            if cur.fetchone():raise ReviewError('Cannot resume an apply run after reversal has started')
            cur.execute('SELECT listing_id FROM raw_data.property_unification_receipts WHERE run_id=%s',(run_id,))
            completed={r[0] for r in cur.fetchall()}
            pending=[r for r in records if r['id'] not in completed and (not ids or r['id'] in ids)]
            batch=pending[:max_records]
            if batch:
                cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=ANY(%s) ORDER BY id'+(' FOR UPDATE' if write else ''),([r['id'] for r in batch],))
                current={row['id']:(row,version) for row,version in cur.fetchall()}
                receipts=[]
                for record in batch:
                    found=current.get(record['id']);outcome='MISSING'
                    if found:
                        row,version=found;new=proposal(row)
                        # Compare JSON-normalized datetimes, excluding the generated decision time.
                        norm=lambda v:json.loads(json.dumps(v,default=str))
                        same=(version==record['row_version'] and row['source']==record['source'] and row['external_id']==record['external_id']
                              and norm(property_types.metadata(row))==record['previous'])
                        reviewed=record['proposed']
                        if same and (norm(property_types.decision_key(new['classification']))!=property_types.decision_key(reviewed['classification'])
                                     or new['counts']!=reviewed['counts'] or new['facts']!=reviewed['facts']):
                            raise ReviewError('Recomputed proposal differs from reviewed preview')
                        outcome='APPLIED' if same else 'CONCURRENT_CHANGE'
                        if same:eligible.append((record,reviewed))
                    outcomes[outcome if write else 'ELIGIBLE' if outcome=='APPLIED' else outcome]+=1
                    receipts.append((run_id,record['id'],outcome))
                if write and eligible:
                    changed=[(r,p) for r,p in eligible if property_types.decision_key(r['previous'])!=property_types.decision_key(p['classification'])]
                    if changed:
                        fields=','.join(property_types.FIELDS)
                        updated=execute_values(cur,'UPDATE raw_data.scraped_listings s SET ('+fields+
                            ')=(SELECT '+fields+' FROM jsonb_populate_record(NULL::raw_data.scraped_listings,v.data::jsonb)) '
                            'FROM (VALUES %s) v(id,data) WHERE s.id=v.id RETURNING s.id,s.xmin::text',
                            [(r['id'],Json(p['classification'])) for r,p in changed],fetch=True)
                        versions=dict(updated)
                        execute_values(cur,'''INSERT INTO raw_data.property_classification_history
                            (listing_id,run_id,origin,old_classification,new_classification,applied_row_version) VALUES %s''',
                            [(r['id'],run_id,'BACKFILL',Json(r['previous']),Json(p['classification']),versions[r['id']]) for r,p in changed])
                    cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=ANY(%s) ORDER BY id',([r['id'] for r,_ in eligible],))
                    room_count_store.persist_many(cur,cur.fetchall(),run_id=run_id)
                    _store_counts(cur,eligible,run_id)
                    execute_values(cur,'''INSERT INTO raw_data.property_fact_assessments
                        (listing_id,source_hash,extractor_sha256,rule_version,run_id,facts) VALUES %s ON CONFLICT DO NOTHING''',
                        [(r['id'],p['counts']['source_hash'],property_facts.extractor_hash(),property_facts.VERSION,run_id,Json(p['facts'])) for r,p in eligible])
                if write and receipts:
                    execute_values(cur,'INSERT INTO raw_data.property_unification_receipts(run_id,listing_id,outcome) VALUES %s',receipts)
            if write:conn.commit()
            else:conn.rollback()
            return dict(run_id=run_id,write=write,outcomes=dict(outcomes),attempted=len(batch),remaining=len(pending)-len(batch))
    except Exception:
        conn.rollback();raise


def reverse_batch(conn, original_run_id, run_id, *, write=False, max_records=100):
    """Reverse only unchanged, latest decisions belonging to the specified run.

    A pricing/lifecycle/source edit after the backfill makes a row ineligible.
    Newer human count reviews and feature assessments also prevent reversal.
    """
    from scraper.property_count_store import revoke_assessment
    if not 1<=max_records<=500:raise ValueError('Batch size must be between 1 and 500')
    original_run_id,run_id=str(UUID(str(original_run_id))),str(UUID(str(run_id)))
    if run_id==original_run_id:raise ReviewError('Reversal needs a different run ID')
    conn.set_session(readonly=not write,autocommit=False)
    outcomes=Counter()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='3s'")
            cur.execute("SET LOCAL statement_timeout='45s'")
            if write:
                # Serialize apply and reversal of the original run on the same key.
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('property-unification:'+original_run_id,))
            cur.execute('SELECT manifest FROM raw_data.property_unification_runs WHERE run_id=%s',(original_run_id,))
            original=cur.fetchone()
            if not original or original[0].get('kind')=='REVERSE':raise ReviewError('Original apply run does not exist')
            if original[0]['database_fingerprint']!=database_fingerprint(conn):raise ReviewError('Run target differs')
            manifest=dict(kind='REVERSE',original_run_id=original_run_id,database_fingerprint=database_fingerprint(conn))
            cur.execute('SELECT manifest FROM raw_data.property_unification_runs WHERE run_id=%s',(run_id,))
            existing=cur.fetchone()
            if existing and existing[0]!=manifest:raise ReviewError('Reversal run ID already has another manifest')
            if write and not existing:cur.execute('INSERT INTO raw_data.property_unification_runs(run_id,manifest) VALUES(%s,%s)',(run_id,Json(manifest)))
            cur.execute('''SELECT r.listing_id FROM raw_data.property_unification_receipts r
                WHERE r.run_id=%s AND r.outcome='APPLIED' AND NOT EXISTS (
                SELECT 1 FROM raw_data.property_unification_receipts d WHERE d.run_id=%s AND d.listing_id=r.listing_id)
                ORDER BY r.listing_id LIMIT %s''',(original_run_id,run_id,max_records))
            pending=[r[0] for r in cur.fetchall()]
            for lid in pending:
                cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=%s'+(' FOR UPDATE' if write else ''),(lid,))
                found=cur.fetchone();outcome='MISSING'
                if found:
                    row,version=found
                    cur.execute('''SELECT id,run_id::text,old_classification,new_classification,applied_row_version
                        FROM raw_data.property_classification_history WHERE listing_id=%s ORDER BY id DESC LIMIT 1''',(lid,))
                    history=cur.fetchone()
                    cur.execute('SELECT id,run_id::text FROM raw_data.property_count_assessments WHERE listing_id=%s ORDER BY id DESC LIMIT 1'+(' FOR UPDATE' if write else ''),(lid,))
                    count=cur.fetchone()
                    cur.execute('SELECT id,run_id::text FROM raw_data.property_fact_assessments WHERE listing_id=%s ORDER BY id DESC LIMIT 1',(lid,))
                    facts=cur.fetchone()
                    safe=bool(history and history[1]==original_run_id and history[4]==version)
                    if count:
                        cur.execute('''SELECT count(*) FROM (
                            SELECT DISTINCT ON (d.observation_id) d.run_id FROM raw_data.property_count_decisions d
                            JOIN raw_data.property_count_observations o ON o.id=d.observation_id
                            WHERE o.assessment_id=%s ORDER BY d.observation_id,d.id DESC) d WHERE run_id<>%s''',(count[0],original_run_id))
                        safe=safe and count[1]==original_run_id and cur.fetchone()[0]==0
                    if facts:safe=safe and facts[1]==original_run_id
                    outcome='REVERSED' if safe else 'CONCURRENT_CHANGE'
                    if safe and write:
                        cur.execute('SELECT id FROM raw_data.property_fact_assessments WHERE listing_id=%s AND run_id=%s AND rule_version=%s ORDER BY id DESC LIMIT 1',(lid,original_run_id,room_counts.VERSION))
                        room_audit=cur.fetchone()
                        if room_audit and room_count_store.reverse(cur,room_audit[0],expected_run_id=original_run_id,run_id=run_id)!='REVERSED':
                            raise ReviewError('Room evidence changed after unified apply')
                        before=history[2]
                        values={**before,'id':lid,'property_type_evidence':Json(before['property_type_evidence'])}
                        cur.execute('UPDATE raw_data.scraped_listings SET '+','.join(f'{k}=%({k})s' for k in property_types.FIELDS)+' WHERE id=%(id)s',values)
                        cur.execute('SELECT xmin::text FROM raw_data.scraped_listings WHERE id=%s',(lid,));applied=cur.fetchone()[0]
                        cur.execute('''INSERT INTO raw_data.property_classification_history
                            (listing_id,run_id,origin,old_classification,new_classification,reverses_id,applied_row_version)
                            VALUES(%s,%s,'REVERSAL',%s,%s,%s,%s)''',
                            (lid,run_id,Json(property_types.metadata(row)),Json(before),history[0],applied))
                        if count:revoke_assessment(conn,count[0],expected_run_id=original_run_id,run_id=run_id,reason='Reverse unified backfill')
                        if facts:cur.execute('INSERT INTO raw_data.property_fact_revocations(assessment_id,run_id,reason) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(facts[0],run_id,'Reverse unified backfill'))
                outcomes[outcome if write else 'ELIGIBLE' if outcome=='REVERSED' else outcome]+=1
                if write:cur.execute('INSERT INTO raw_data.property_unification_receipts(run_id,listing_id,outcome) VALUES(%s,%s,%s)',(run_id,lid,outcome))
            if write:conn.commit()
            else:conn.rollback()
            return dict(run_id=run_id,write=write,outcomes=dict(outcomes),attempted=len(pending))
    except Exception:
        conn.rollback();raise
