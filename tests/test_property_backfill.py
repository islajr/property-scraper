"""Use only an explicitly configured disposable TEST_DATABASE_URL."""
import json
import hashlib
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
import psycopg2
import pytest

from scraper.classification_artifact import reviewed_preview, ReviewError
from scraper.property_backfill import apply_preview, reverse_run, Selection
from scraper.property_types import FIELDS, metadata, classify
from scripts.preview_property_classification import preview
from tests.test_pricing_database import pricing_writer


def seed(db, tmp_path, titles=('Semi-detached duplex','Mini flat','4 bedrooms')):
    source = 'backfill-' + uuid4().hex
    ids = []
    with db.conn.cursor() as cur:
        for title in titles:
            cur.execute('''INSERT INTO raw_data.scraped_listings
                (source,external_id,url,title,property_type,price_kobo,price_type)
                VALUES (%s,%s,'https://test',%s,'OLD_LABEL',123400,'FOR_SALE') RETURNING id''',
                (source,uuid4().hex,title))
            ids.append(cur.fetchone()[0])
    db.conn.commit()
    path = tmp_path/'preview.jsonl'
    preview(db.conn,path,source=source)
    return path,ids


def snapshot(db, ids):
    with db.conn.cursor() as cur:
        cur.execute('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE id=ANY(%s) ORDER BY id',(ids,))
        rows = cur.fetchall()
    db.conn.rollback()
    return rows


def counts(db, run_id):
    with db.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM raw_data.property_classification_receipts WHERE run_id=%s',(run_id,))
        receipts = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM raw_data.property_classification_history WHERE run_id=%s',(run_id,))
        history = cur.fetchone()[0]
    db.conn.rollback()
    return receipts,history


def apply(db,path,run_id,**kwargs):
    with reviewed_preview(path) as artifact:
        return apply_preview(db.conn,artifact,run_id,**kwargs)


def test_dry_run_is_server_readonly_and_has_no_receipts(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path)
    before=snapshot(db,ids);run_id=str(uuid4())
    def check(lid,outcome):
        with db.conn.cursor() as cur:
            cur.execute('SHOW transaction_read_only');assert cur.fetchone()[0]=='on'
    result=apply(db,path,run_id,on_result=check)
    assert result['counts']['ELIGIBLE']==3
    assert counts(db,run_id)==(0,0)
    assert snapshot(db,ids)==before


def test_bounded_resume_and_idempotence_preserve_unrelated_fields(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path)
    before=snapshot(db,ids);run_id=str(uuid4())
    for remaining in (2,1,0):
        result=apply(db,path,run_id,write=True,max_records=1)
        assert result['counts']['APPLIED']==1 and result['remaining']==remaining
    after=snapshot(db,ids)
    assert [row[0]['property_type'] for row in after]==['SEMI_DETACHED_DUPLEX','MINI_FLAT',None]
    assert after[-1][0]['property_type_status']=='INSUFFICIENT_EVIDENCE'
    for (old,_),(new,_) in zip(before,after):
        assert {k:v for k,v in old.items() if k not in FIELDS}=={k:v for k,v in new.items() if k not in FIELDS}
    assert counts(db,run_id)==(3,3)
    result=apply(db,path,run_id,write=True)
    assert result['counts']['already_completed']==3 and result['remaining']==0
    assert counts(db,run_id)==(3,3)
    with db.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM raw_data.listing_history WHERE listing_id=ANY(%s)',(ids,))
        assert cur.fetchone()[0]==0


def test_commit_before_local_report_failure_resumes_without_duplicate_write(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);run_id=str(uuid4())
    def crash(*args): raise RuntimeError('local process stopped after commit')
    with pytest.raises(RuntimeError):apply(db,path,run_id,write=True,on_result=crash)
    assert counts(db,run_id)==(1,1)
    result=apply(db,path,run_id,write=True)
    assert result['counts']['already_completed']==1 and result['counts']['APPLIED']==2
    assert counts(db,run_id)==(3,3)


def test_receipt_failure_rolls_back_row_and_audit_and_can_resume(pricing_writer,tmp_path,monkeypatch):
    import scraper.property_backfill as module
    db=pricing_writer;path,ids=seed(db,tmp_path);before=snapshot(db,ids);run_id=str(uuid4())
    original=module._receipt
    def fail(*args):raise RuntimeError('receipt failed')
    monkeypatch.setattr(module,'_receipt',fail)
    with pytest.raises(RuntimeError):apply(db,path,run_id,write=True)
    assert snapshot(db,ids)==before and counts(db,run_id)==(0,0)
    monkeypatch.setattr(module,'_receipt',original)
    assert apply(db,path,run_id,write=True)['counts']['APPLIED']==3


@pytest.mark.parametrize('field,value',[('title','Changed title'),('price_kobo',9999),('listing_status','REMOVED')])
def test_concurrent_changes_are_terminal_skips_not_overwritten(pricing_writer,tmp_path,field,value):
    db=pricing_writer;path,ids=seed(db,tmp_path);run_id=str(uuid4())
    db.conn.set_session(readonly=False)
    with db.conn.cursor() as cur:cur.execute(f'UPDATE raw_data.scraped_listings SET {field}=%s WHERE id=%s',(value,ids[0]))
    db.conn.commit();before=snapshot(db,ids)
    result=apply(db,path,run_id,write=True)
    assert result['counts']['CONCURRENT_CHANGE']==1
    assert snapshot(db,ids)[0]==before[0]
    assert apply(db,path,run_id,write=True)['counts']['already_completed']==3
    assert counts(db,run_id)==(3,2)


def test_target_and_selection_cannot_change_on_resume(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);run_id=str(uuid4())
    with reviewed_preview(path) as artifact:
        artifact.summary['database_fingerprint']='wrong-target'
        with pytest.raises(ReviewError,match='fingerprint'):apply_preview(db.conn,artifact,run_id,write=True)
    assert counts(db,run_id)==(0,0)
    apply(db,path,run_id,write=True,max_records=1)
    with pytest.raises(ReviewError,match='selection'):
        apply(db,path,run_id,write=True,selection=Selection(ids=(ids[0],)))
    assert counts(db,run_id)==(1,1)


def test_proposed_decision_must_match_recomputed_current_evidence(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);before=snapshot(db,ids);run_id=str(uuid4())
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['proposed']=asdict(classify(title='Land'))
    path.write_text(''.join(json.dumps(row,default=str)+'\n' for row in rows))
    summary=json.loads(path.with_suffix('.summary.json').read_text())
    summary['report_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.summary.json').write_text(json.dumps(summary))
    result=apply(db,path,run_id,write=True,max_records=1)
    assert result['counts']['PROPOSAL_MISMATCH']==1
    assert snapshot(db,ids)==before and counts(db,run_id)==(1,0)


def test_reversal_is_readonly_by_default_then_restores_exact_metadata(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);before=snapshot(db,ids)
    forward,reverse=str(uuid4()),str(uuid4())
    apply(db,path,forward,write=True)
    applied=snapshot(db,ids)
    assert reverse_run(db.conn,forward,reverse)['counts']['ELIGIBLE']==3
    assert counts(db,reverse)==(0,0) and snapshot(db,ids)==applied
    result=reverse_run(db.conn,forward,reverse,write=True,max_records=2)
    assert result['counts']['REVERSED']==2 and result['remaining']==1
    assert reverse_run(db.conn,forward,reverse,write=True)['remaining']==0
    after=snapshot(db,ids)
    assert [row[0] for row in after]==[row[0] for row in before]
    assert counts(db,forward)==(3,3) and counts(db,reverse)==(3,3)
    assert reverse_run(db.conn,forward,reverse,write=True)['counts']['already_completed']==3
    assert reverse_run(db.conn,forward,str(uuid4()),write=True)['counts']['ALREADY_REVERSED']==3
    with db.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM raw_data.property_classification_history WHERE listing_id=ANY(%s) AND reverses_id IS NOT NULL',(ids,))
        assert cur.fetchone()[0]==3


def test_reversal_skips_any_later_observation(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);forward=str(uuid4())
    apply(db,path,forward,write=True)
    with db.conn.cursor() as cur:cur.execute('UPDATE raw_data.scraped_listings SET price_kobo=5555 WHERE id=%s',(ids[0],))
    db.conn.commit();before=snapshot(db,ids)
    result=reverse_run(db.conn,forward,str(uuid4()),write=True)
    assert result['counts']['SUBSEQUENT_CHANGE']==1 and result['counts']['REVERSED']==2
    assert snapshot(db,ids)[0]==before[0]


def test_reversal_audit_and_receipt_failures_roll_back_and_resume(pricing_writer,tmp_path,monkeypatch):
    import scraper.property_backfill as module
    db=pricing_writer;path,ids=seed(db,tmp_path);forward,reverse=str(uuid4()),str(uuid4())
    apply(db,path,forward,write=True);before=snapshot(db,ids)
    original=module._receipt
    def fail(*args):raise RuntimeError('reversal receipt failed')
    monkeypatch.setattr(module,'_receipt',fail)
    with pytest.raises(RuntimeError):reverse_run(db.conn,forward,reverse,write=True)
    assert snapshot(db,ids)==before and counts(db,reverse)==(0,0)
    monkeypatch.setattr(module,'_receipt',original)
    assert reverse_run(db.conn,forward,reverse,write=True)['counts']['REVERSED']==3


def test_already_supported_decisions_are_unchanged_without_new_audit(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);forward=str(uuid4())
    apply(db,path,forward,write=True)
    source=snapshot(db,ids)[0][0]['source']
    preview(db.conn,path,source=source)
    before=snapshot(db,ids);second=str(uuid4())
    result=apply(db,path,second,write=True)
    assert result['counts']['UNCHANGED']==3 and snapshot(db,ids)==before
    assert counts(db,second)==(3,0)


def test_starting_reversal_prevents_further_apply_resume(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);forward=str(uuid4())
    apply(db,path,forward,write=True,max_records=1)
    reverse_run(db.conn,forward,str(uuid4()),write=True)
    with pytest.raises(ReviewError,match='reversal'):apply(db,path,forward)
    with pytest.raises(ReviewError,match='reversal'):apply(db,path,forward,write=True)
    assert snapshot(db,ids)[1][0]['property_type']=='OLD_LABEL'


def test_locked_rows_remain_retryable_and_resume_later(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);run_id=str(uuid4())
    blocker=psycopg2.connect(db.database_url)
    try:
        with blocker.cursor() as cur:cur.execute('SELECT id FROM raw_data.scraped_listings WHERE id=%s FOR UPDATE',(ids[0],))
        result=apply(db,path,run_id,write=True)
        assert result['counts']['RETRYABLE_LOCK']==1 and result['remaining']==1
        assert counts(db,run_id)==(2,2)
    finally:blocker.rollback();blocker.close()
    result=apply(db,path,run_id,write=True)
    assert result['counts']['APPLIED']==1 and result['remaining']==0


def test_apply_and_reversal_cannot_run_concurrently(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);forward=str(uuid4())
    other=psycopg2.connect(db.database_url)
    try:
        def reverse_during_apply(*args):
            with pytest.raises(ReviewError,match='Another process'):
                reverse_run(other,forward,str(uuid4()),write=True)
        apply(db,path,forward,write=True,on_result=reverse_during_apply)
    finally:other.close()
    assert counts(db,forward)==(3,3)


def test_operation_receipts_and_history_are_immutable_and_migration_reruns(pricing_writer,tmp_path):
    db=pricing_writer;path,ids=seed(db,tmp_path);run_id=str(uuid4())
    apply(db,path,run_id,write=True)
    with db.conn.cursor() as cur:cur.execute(Path('schema/007_property_classification_operations.sql').read_text())
    for table in ('property_classification_operations','property_classification_receipts','property_classification_history'):
        for action in ('UPDATE','DELETE'):
            with pytest.raises(psycopg2.Error):
                with db.conn.cursor() as cur:
                    sql=f'UPDATE raw_data.{table} SET run_id=run_id' if action=='UPDATE' else f'DELETE FROM raw_data.{table}'
                    cur.execute(sql+' WHERE run_id=%s',(run_id,))
            db.conn.rollback()
    assert counts(db,run_id)==(3,3)
