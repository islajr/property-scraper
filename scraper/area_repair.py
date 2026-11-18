"""Frozen, bounded advertised-area previews, application and guarded reversal."""
from collections import Counter
import hashlib,json,tempfile
from pathlib import Path
from uuid import UUID
from psycopg2.extras import Json,execute_values
from scraper import area_measurements,area_store
from scraper.classification_artifact import ReviewError,database_fingerprint


def fingerprint():
    return hashlib.sha256(area_measurements.extractor_hash().encode()+Path(area_store.__file__).read_bytes()+Path(__file__).read_bytes()).hexdigest()


def _before(row):return {k:row.get(k) for k in area_store.FIELDS}


def preview(conn,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=None
    conn.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
    counts=Counter();states=Counter();digest=hashlib.sha256()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT transaction_timestamp(),current_setting('transaction_read_only')")
            snapshot,mode=cur.fetchone()
            cur.execute("SELECT to_regclass('raw_data.current_property_areas') IS NOT NULL")
            compatible=cur.fetchone()[0]
            if mode!='on':raise ReviewError('Read-only preview required')
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,delete=False) as file:
            temporary=Path(file.name)
            with conn.cursor(name='area_preview') as cur:
                cur.itersize=500;cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s ORDER BY id')
                for row,version in cur:
                    after=area_store.proposal(row)
                    record=dict(id=row['id'],source=row['source'],external_id=row['external_id'],
                        row_version=version,source_hash=area_measurements.source_hash(row),before=_before(row),after=after)
                    line=json.dumps(record,sort_keys=True,ensure_ascii=False)+'\n';file.write(line);digest.update(line.encode())
                    counts['scanned']+=1
                    counts['claims']+=len(after['area_data']['claims'])
                    for field in ('floor_area_sqm','land_area_sqm'):
                        old=row.get(field);new=after[field]
                        changed=not area_store.equal_fields(row,{field:new})
                        counts[field+'_filled']+=old is None and new is not None
                        counts[field+'_existing_changed']+=old is not None and changed
                        states[field+':'+after['area_data'][field]['status']]+=1
        conn.rollback();temporary.replace(path);temporary=None
        summary=dict(report_kind='property_area_repair',read_only=True,apply_compatible=compatible,
            snapshot_at=str(snapshot),code_sha256=fingerprint(),report_sha256=digest.hexdigest(),
            database_fingerprint=database_fingerprint(conn),counts=dict(counts),states=dict(states))
        path.with_suffix('.summary.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
        return summary
    finally:
        conn.rollback()
        if temporary:temporary.unlink(missing_ok=True)


def load_preview(path):
    path=Path(path);data=path.read_bytes();summary=json.loads(path.with_suffix('.summary.json').read_text())
    if summary.get('report_kind')!='property_area_repair' or summary.get('read_only') is not True or summary.get('apply_compatible') is not True:
        raise ReviewError('Use a read-only area-measurement preview')
    if hashlib.sha256(data).hexdigest()!=summary.get('report_sha256') or fingerprint()!=summary.get('code_sha256'):
        raise ReviewError('Preview bytes or rules changed; regenerate the preview')
    records=[json.loads(line) for line in data.splitlines()];ids=[r['id'] for r in records]
    if ids!=sorted(set(ids)) or any(type(i)is not int or i<1 for i in ids) or len(ids)!=summary['counts']['scanned']:
        raise ReviewError('Preview identities or row count invalid')
    return summary,records


def apply_batch(conn,summary,records,run_id,*,write=False,max_records=100,ids=()):
    if not 1<=max_records<=500:raise ValueError('Batch must be between 1 and 500')
    run_id=str(UUID(str(run_id)))
    if fingerprint()!=summary['code_sha256'] or database_fingerprint(conn)!=summary['database_fingerprint']:
        raise ReviewError('Database or rule fingerprint differs')
    digest=hashlib.sha256(''.join(json.dumps(r,sort_keys=True,ensure_ascii=False)+'\n' for r in records).encode()).hexdigest()
    if digest!=summary['report_sha256']:raise ReviewError('Artifact records changed after validation')
    manifest=dict(kind='AREA_MEASUREMENTS_APPLY',**{k:summary[k] for k in ('code_sha256','report_sha256','database_fingerprint')},ids=sorted(set(ids)))
    conn.set_session(readonly=not write,isolation_level='READ COMMITTED',autocommit=False)
    outcomes=Counter()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='3s'");cur.execute("SET LOCAL statement_timeout='45s'")
            if write:cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('area-measurement-repair:'+run_id,))
            cur.execute('SELECT manifest FROM raw_data.property_unification_runs WHERE run_id=%s',(run_id,));existing=cur.fetchone()
            if existing and existing[0]!=manifest:raise ReviewError('Run ID belongs to another artifact or selection')
            cur.execute("SELECT 1 FROM raw_data.property_unification_runs WHERE manifest->>'original_run_id'=%s LIMIT 1",(run_id,))
            if cur.fetchone():raise ReviewError('Cannot resume a reversed repair')
            if write and not existing:cur.execute('INSERT INTO raw_data.property_unification_runs(run_id,manifest) VALUES(%s,%s)',(run_id,Json(manifest)))
            cur.execute('SELECT listing_id FROM raw_data.property_unification_receipts WHERE run_id=%s',(run_id,));done={r[0] for r in cur.fetchall()}
            pending=[r for r in records if r['id'] not in done and (not ids or r['id'] in ids)];batch=pending[:max_records]
            eligible=[];receipts=[]
            if batch:
                cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=ANY(%s) ORDER BY id'+(' FOR UPDATE' if write else ''),([r['id'] for r in batch],))
                rows={r['id']:(r,v) for r,v in cur.fetchall()}
                for record in batch:
                    found=rows.get(record['id']);outcome='MISSING'
                    if found:
                        row,version=found
                        same=version==record['row_version'] and row['source']==record['source'] and row['external_id']==record['external_id']
                        same=same and _before(row)==record['before'] and area_measurements.source_hash(row)==record['source_hash']
                        if same and area_store.proposal(row)!=record['after']:raise ReviewError('Recomputed area proposal differs')
                        outcome='APPLIED' if same else 'CONCURRENT_CHANGE'
                        if same:eligible.append(found)
                    receipts.append((run_id,record['id'],outcome));outcomes[outcome if write else 'ELIGIBLE' if outcome=='APPLIED' else outcome]+=1
            if write and eligible:area_store.persist_many(cur,eligible,run_id=run_id)
            if write and receipts:execute_values(cur,'INSERT INTO raw_data.property_unification_receipts(run_id,listing_id,outcome) VALUES %s',receipts)
            if write:conn.commit()
            else:conn.rollback()
            return dict(run_id=run_id,write=write,outcomes=dict(outcomes),attempted=len(batch),remaining=len(pending)-len(batch))
    except Exception:
        conn.rollback();raise


def reverse_batch(conn,original_run_id,run_id,*,write=False,max_records=100):
    original_run_id,run_id=str(UUID(str(original_run_id))),str(UUID(str(run_id)))
    if original_run_id==run_id or not 1<=max_records<=500:raise ValueError('Use a new reversal ID and bounded batch')
    conn.set_session(readonly=not write,autocommit=False);outcomes=Counter()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='3s'");cur.execute("SET LOCAL statement_timeout='45s'")
            if write:cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('area-measurement-repair:'+original_run_id,))
            cur.execute('SELECT manifest FROM raw_data.property_unification_runs WHERE run_id=%s',(original_run_id,));original=cur.fetchone()
            if not original or original[0].get('kind')!='AREA_MEASUREMENTS_APPLY' or original[0]['database_fingerprint']!=database_fingerprint(conn):
                raise ReviewError('Original area run/target differs')
            manifest=dict(kind='AREA_MEASUREMENTS_REVERSE',original_run_id=original_run_id,database_fingerprint=database_fingerprint(conn))
            cur.execute('SELECT manifest FROM raw_data.property_unification_runs WHERE run_id=%s',(run_id,));existing=cur.fetchone()
            if existing and existing[0]!=manifest:raise ReviewError('Reversal ID already belongs to another operation')
            if write and not existing:cur.execute('INSERT INTO raw_data.property_unification_runs(run_id,manifest) VALUES(%s,%s)',(run_id,Json(manifest)))
            cur.execute('''SELECT r.listing_id FROM raw_data.property_unification_receipts r WHERE r.run_id=%s AND r.outcome='APPLIED'
                AND NOT EXISTS(SELECT 1 FROM raw_data.property_unification_receipts d WHERE d.run_id=%s AND d.listing_id=r.listing_id)
                ORDER BY r.listing_id LIMIT %s''',(original_run_id,run_id,max_records));batch=[r[0] for r in cur.fetchall()]
            for lid in batch:
                cur.execute('SELECT id FROM raw_data.property_fact_assessments WHERE listing_id=%s AND run_id=%s AND rule_version=%s ORDER BY id DESC LIMIT 1',
                    (lid,original_run_id,area_measurements.VERSION));audit=cur.fetchone()
                if not audit:outcome='CONCURRENT_CHANGE'
                elif write:outcome=area_store.reverse(cur,audit[0],expected_run_id=original_run_id,run_id=run_id)
                else:
                    cur.execute('''SELECT s.xmin::text,a.facts->>'applied_row_version',row_to_json(s),a.facts->'after'
                        FROM raw_data.scraped_listings s JOIN raw_data.property_fact_assessments a ON a.listing_id=s.id WHERE a.id=%s''',(audit[0],))
                    found=cur.fetchone();outcome='ELIGIBLE' if found and found[0]==found[1] and area_store.equal_fields(found[2],found[3]) else 'CONCURRENT_CHANGE'
                outcomes[outcome]+=1
                if write:cur.execute('INSERT INTO raw_data.property_unification_receipts(run_id,listing_id,outcome) VALUES(%s,%s,%s)',(run_id,lid,outcome))
            if write:conn.commit()
            else:conn.rollback()
            return dict(run_id=run_id,write=write,outcomes=dict(outcomes),attempted=len(batch))
    except Exception:
        conn.rollback();raise
