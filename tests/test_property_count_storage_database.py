import json
from pathlib import Path
from uuid import uuid4
import psycopg2
import pytest
from scraper.normaliser import normalise
from scraper.property_counts import source_hash,extractor_hash
from scraper.property_count_store import persist_assessment,revoke_assessment
from scripts.preview_property_counts import preview
from tests.conftest import make_raw
from tests.test_pricing_database import pricing_writer,get_row


def add(db,title='One block containing four flats'):
    item=normalise(make_raw(external_id=uuid4().hex,title=title,description=None))
    db.upsert([item],{});row=get_row(db,item.external_id)
    with db.conn.cursor() as cur:
        cur.execute('SELECT xmin::text FROM raw_data.scraped_listings WHERE id=%s',(row['id'],));version=cur.fetchone()[0]
    db.conn.commit()
    return item,row,version


def store(db,row,version,run):
    return persist_assessment(db.conn,row['id'],expected_row_version=version,
                              expected_source_hash=source_hash(row['title'],row['description']),
                              expected_extractor_hash=extractor_hash(),run_id=run)


def test_additive_rerun_idempotent_persistence_and_source_preservation(pricing_writer):
    db=pricing_writer;item,before,version=add(db);run=uuid4()
    with db.conn.cursor() as cur:
        cur.execute(Path('schema/009_property_counts.sql').read_text())
        cur.execute(Path('schema/009_property_counts.sql').read_text())
    result=store(db,before,version,run);db.conn.commit()
    assert result['outcome']=='STORED'
    assert store(db,before,version,run)['outcome']=='ALREADY_ASSESSED'
    assert get_row(db,item.external_id)==before
    with db.conn.cursor() as cur:
        cur.execute('SELECT counted_entity,relationship,quantity_min FROM raw_data.current_property_counts WHERE listing_id=%s ORDER BY counted_entity',(before['id'],))
        assert cur.fetchall()==[('BUILDING','OFFERED_ASSET',1),('DWELLING_UNIT','CONTAINED_UNIT',4)]


def test_stale_guard_and_freshness_view(pricing_writer):
    db=pricing_writer;_,row,version=add(db)
    assert persist_assessment(db.conn,row['id'],expected_row_version=version,
        expected_source_hash=source_hash(row['title'],row['description']),
        expected_extractor_hash='0'*64,run_id=uuid4())['outcome']=='STALE_RULES'
    assert store(db,row,'0',uuid4())['outcome']=='STALE_SOURCE'
    assert store(db,row,version,uuid4())['outcome']=='STORED';db.conn.commit()
    with db.conn.cursor() as cur:
        cur.execute('UPDATE raw_data.scraped_listings SET title=%s WHERE id=%s',('Another property',row['id']))
        cur.execute('SELECT count(*) FROM raw_data.current_property_counts WHERE listing_id=%s',(row['id'],));assert cur.fetchone()[0]==0


def test_append_only_reversal_and_retry_do_not_resurrect_counts(pricing_writer):
    db=pricing_writer;_,row,version=add(db);run=uuid4()
    result=store(db,row,version,run);db.conn.commit()
    aid=result['assessment_id']
    assert revoke_assessment(db.conn,aid,expected_run_id=uuid4(),run_id=uuid4(),reason='Wrong owner')==0
    reverse=uuid4()
    assert revoke_assessment(db.conn,aid,expected_run_id=run,run_id=reverse,reason='Reviewed reversal')==2
    db.conn.commit()
    assert store(db,row,version,run)['outcome']=='ALREADY_ASSESSED'
    with db.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM raw_data.current_property_counts WHERE listing_id=%s',(row['id'],));assert cur.fetchone()[0]==0
        with pytest.raises(psycopg2.Error):
            cur.execute('DELETE FROM raw_data.property_count_assessments WHERE id=%s',(aid,))
    db.conn.rollback()


def test_sql_and_python_source_hash_and_price_independence(pricing_writer):
    db=pricing_writer
    with db.conn.cursor() as cur:
        for title,description in [(None,None),('₦三','😀'),('a','bc'),('ab','c')]:
            cur.execute('SELECT raw_data.property_count_source_hash(%s,%s)',(title,description))
            assert cur.fetchone()[0]==source_hash(title,description)
    db.conn.commit()
    _,row,version=add(db);store(db,row,version,uuid4());db.conn.commit()
    with db.conn.cursor() as cur:
        cur.execute('UPDATE raw_data.scraped_listings SET price_kobo=price_kobo+1 WHERE id=%s',(row['id'],))
        cur.execute('SELECT count(*) FROM raw_data.current_property_counts WHERE listing_id=%s',(row['id'],));assert cur.fetchone()[0]==2


def test_preview_is_readonly_and_persists_no_assessments(pricing_writer,tmp_path):
    db=pricing_writer;_,row,_=add(db)
    with db.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM raw_data.property_count_assessments');before=cur.fetchone()[0]
    db.conn.rollback()
    result=preview(db.conn,tmp_path/'preview.jsonl')
    assert result['read_only'] and not result['apply_compatible']
    assert any(r['id']==row['id'] for r in map(json.loads,(tmp_path/'preview.jsonl').read_text().splitlines()))
    with db.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM raw_data.property_count_assessments');assert cur.fetchone()[0]==before
        with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
            cur.execute('UPDATE raw_data.scraped_listings SET title=title WHERE id=%s',(row['id'],))
    db.conn.rollback()


def test_storage_rolls_back_as_one_transaction(pricing_writer):
    db=pricing_writer;item,row,version=add(db)
    result=store(db,row,version,uuid4());db.conn.rollback()
    with db.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM raw_data.property_count_assessments WHERE id=%s',(result['assessment_id'],))
        assert cur.fetchone()[0]==0
    assert get_row(db,item.external_id)==row


def test_older_run_reversal_preserves_a_newer_review_decision(pricing_writer):
    db=pricing_writer;_,row,version=add(db);run=uuid4()
    result=store(db,row,version,run);db.conn.commit()
    with db.conn.cursor() as cur:
        cur.execute("SELECT id FROM raw_data.property_count_observations WHERE assessment_id=%s AND counted_entity='BUILDING'",(result['assessment_id'],))
        oid=cur.fetchone()[0]
        cur.execute("INSERT INTO raw_data.property_count_decisions(observation_id,decision,reason,run_id) VALUES (%s,'ACCEPT','Newer explicit review',%s)",(oid,str(uuid4())))
    db.conn.commit()
    assert revoke_assessment(db.conn,result['assessment_id'],expected_run_id=run,run_id=uuid4(),reason='Reverse old decisions')==1
    with db.conn.cursor() as cur:
        cur.execute('SELECT counted_entity FROM raw_data.current_property_counts WHERE listing_id=%s',(row['id'],))
        assert cur.fetchall()==[('BUILDING',)]


def test_sql_rejects_acceptance_of_unresolved_entities(pricing_writer):
    db=pricing_writer;_,row,version=add(db,'Two beds in a room')
    result=store(db,row,version,uuid4());db.conn.commit()
    with db.conn.cursor() as cur:
        cur.execute('SELECT id FROM raw_data.property_count_observations WHERE assessment_id=%s',(result['assessment_id'],))
        oid=cur.fetchone()[0]
        with pytest.raises(psycopg2.Error):
            cur.execute("INSERT INTO raw_data.property_count_decisions(observation_id,decision,reason,run_id) VALUES (%s,'ACCEPT','Cannot bypass entity validation',%s)",(oid,str(uuid4())))
    db.conn.rollback()


def test_oversized_claim_is_retained_as_held_evidence(pricing_writer):
    db=pricing_writer;_,row,version=add(db,'99999999999999999999999 duplexes sold together')
    result=store(db,row,version,uuid4());db.conn.commit()
    with db.conn.cursor() as cur:
        cur.execute('SELECT quantity_min FROM raw_data.property_count_observations WHERE assessment_id=%s',(result['assessment_id'],))
        assert cur.fetchone()[0]==99999999999999999999999
        cur.execute('SELECT count(*) FROM raw_data.current_property_counts WHERE listing_id=%s',(row['id'],))
        assert cur.fetchone()[0]==0


def test_autocommit_connections_are_rejected_before_persistence(pricing_writer):
    db=pricing_writer;_,row,version=add(db)
    db.conn.autocommit=True
    try:
        with pytest.raises(ValueError,match='explicit transaction'):
            store(db,row,version,uuid4())
        with pytest.raises(ValueError,match='explicit transaction'):
            revoke_assessment(db.conn,1,expected_run_id=uuid4(),run_id=uuid4(),reason='Test')
    finally:db.conn.autocommit=False


def test_decision_order_is_allocated_after_serialization(pricing_writer):
    db=pricing_writer;_,row,version=add(db)
    result=store(db,row,version,uuid4());db.conn.commit()
    with db.conn.cursor() as cur:
        cur.execute('SELECT id FROM raw_data.property_count_observations WHERE assessment_id=%s ORDER BY id LIMIT 1',(result['assessment_id'],))
        oid=cur.fetchone()[0]
        cur.execute("INSERT INTO raw_data.property_count_decisions(id,observation_id,decision,reason,run_id) VALUES (0,%s,'HOLD','Later review must become latest',%s) RETURNING id",(oid,str(uuid4())))
        assert cur.fetchone()[0]>0
        cur.execute('SELECT count(*) FROM raw_data.current_property_counts WHERE observation_id=%s',(oid,))
        assert cur.fetchone()[0]==0
