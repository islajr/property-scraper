from pathlib import Path
from uuid import uuid4
import pytest
import psycopg2
from tests.test_pricing_database import pricing_writer,get_row,listing
from scraper.room_count_repair import preview,load_preview,apply_batch,reverse_batch
from scraper.room_counts import source_hash
from scraper.room_count_store import FIELDS
from scraper.classification_artifact import ReviewError
from tests.conftest import make_normalised


def test_oversized_legacy_checkpoint_is_revalidated_before_insert(pricing_writer):
    db=pricing_writer
    item=make_normalised(external_id=uuid4().hex,bedrooms=123456789,bathrooms=987654321)
    db.upsert([item],{})
    row=get_row(db,item.external_id)
    assert row['bedrooms']==3 and row['bathrooms'] is None


def test_observations_refresh_both_room_fields_and_keep_legacy_snapshot(pricing_writer):
    db=pricing_writer;old=listing(title='3 bedroom flat',raw_bedrooms='3 Bedrooms',raw_bathrooms='2 Bathrooms')
    db.upsert([old],{});before=get_row(db,old.external_id)
    changed=listing(title='4 bedroom flat',description='Four bedroom flat.',raw_bedrooms='4 Bedrooms',raw_bathrooms='5 Bathrooms')
    changed.external_id=old.external_id
    db.upsert([changed],{})
    after=get_row(db,old.external_id)
    assert (after['bedrooms'],after['bathrooms'])==(4,5)
    assert after['room_count_legacy']=={'bedrooms':None,'bathrooms':None}
    with db.conn.cursor() as c:
        c.execute('SELECT bedrooms_per_dwelling,bathrooms_per_dwelling,room_counts_current FROM raw_data.property_research_current WHERE listing_id=%s',(after['id'],))
        assert c.fetchone()==(4,5,True)
    db.conn.rollback()
    changed.raw_bathrooms='6 Bathrooms'
    db.confirm_listing_active(after['id'],None,observed_quote=changed)
    assert get_row(db,old.external_id)['bathrooms']==6


def test_raw_metric_changes_invalidate_rooms_without_invalidating_other_source_claims(pricing_writer):
    db=pricing_writer;item=listing();db.upsert([item],{});r=get_row(db,item.external_id)
    with db.conn.cursor() as c:
        c.execute("UPDATE raw_data.scraped_listings SET raw_bathrooms='9 Bathrooms' WHERE id=%s",(r['id'],))
        c.execute('SELECT room_counts_current,contract_current,bathrooms_per_dwelling,bathrooms_status FROM raw_data.property_research_current WHERE listing_id=%s',(r['id'],))
        assert c.fetchone()==(False,False,None,'PENDING')
        c.execute('SELECT count(*) FROM raw_data.current_property_facts WHERE listing_id=%s',(r['id'],));assert c.fetchone()[0]==1


def test_sql_source_hash_matches_python_with_unicode_and_nulls(pricing_writer):
    db=pricing_writer
    with db.conn.cursor() as c:
        for raw in (None,'','2 Bathrooms'):
            row=dict(source='t',external_id='三',title='😀',description='',property_type_raw=None,raw_bedrooms=None,
                raw_bathrooms=raw,property_type='HOUSE',property_asset_scope=None,room_metric_sources={'bathrooms':'PRIMARY_LABEL'})
            c.execute('SELECT raw_data.property_room_source_hash(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)',
                tuple(row[k] for k in ('source','external_id','title','description','property_type_raw','raw_bedrooms','raw_bathrooms','property_type','property_asset_scope'))+('{"bathrooms":"PRIMARY_LABEL"}',))
            assert c.fetchone()[0]==source_hash(row)


def historical(db):
    item=listing(title='3 bedroom flat',raw_bedrooms='3 Bedrooms',raw_bathrooms='2 Bathrooms')
    db.upsert([item],{})
    with db.conn.cursor() as c:
        c.execute("UPDATE raw_data.scraped_listings SET bedrooms=1234,bathrooms=123,raw_bedrooms=NULL,raw_bathrooms=NULL,room_count_data='{}',room_metric_sources='{}',room_count_legacy=NULL WHERE external_id=%s",(item.external_id,))
    db.conn.commit();return item,get_row(db,item.external_id)


def test_repair_is_reviewed_bounded_idempotent_and_preserves_unrelated_data(pricing_writer,tmp_path):
    db=pricing_writer;item,before=historical(db);db.conn.rollback();path=tmp_path/'repair.jsonl'
    summary=preview(db.conn,path);artifact=load_preview(path);run=uuid4();ids=(before['id'],)
    assert summary['read_only']
    assert apply_batch(db.conn,*artifact,run,ids=ids)['outcomes']=={'ELIGIBLE':1}
    assert get_row(db,item.external_id)==before;db.conn.rollback()
    assert apply_batch(db.conn,*artifact,run,write=True,ids=ids)['outcomes']=={'APPLIED':1}
    after=get_row(db,item.external_id);db.conn.rollback()
    assert after['bedrooms']==3 and after['bathrooms'] is None
    assert after['room_count_legacy']==dict(bedrooms=1234,bathrooms=123)
    assert {k:v for k,v in before.items() if k not in FIELDS}=={k:v for k,v in after.items() if k not in FIELDS}
    assert apply_batch(db.conn,*artifact,run,write=True,ids=ids)['attempted']==0
    with pytest.raises(ReviewError):apply_batch(db.conn,*artifact,run,write=True)


@pytest.mark.parametrize('later_edit',[False,True])
def test_reversal_respects_later_edits_and_prevents_resurrection(pricing_writer,tmp_path,later_edit):
    db=pricing_writer;item,before=historical(db);db.conn.rollback();path=tmp_path/'reverse.jsonl';preview(db.conn,path)
    artifact=load_preview(path);run,reverse=uuid4(),uuid4();apply_batch(db.conn,*artifact,run,write=True,ids=(before['id'],))
    if later_edit:
        with db.conn.cursor() as c:c.execute('UPDATE raw_data.scraped_listings SET price_kobo=price_kobo+1 WHERE id=%s',(before['id'],))
        db.conn.commit()
    dry=reverse_batch(db.conn,run,reverse)
    assert dry['outcomes']==({'CONCURRENT_CHANGE':1} if later_edit else {'ELIGIBLE':1})
    result=reverse_batch(db.conn,run,reverse,write=True)
    assert result['outcomes']==({'CONCURRENT_CHANGE':1} if later_edit else {'REVERSED':1})
    if not later_edit:assert get_row(db,item.external_id)==before
    db.conn.rollback()
    with pytest.raises(ReviewError):apply_batch(db.conn,*artifact,run,write=True,ids=(before['id'],))
    assert reverse_batch(db.conn,run,reverse,write=True)['attempted']==0


def test_changed_source_and_modified_preview_are_not_applied(pricing_writer,tmp_path):
    db=pricing_writer;item,r=historical(db);db.conn.rollback();path=tmp_path/'stale.jsonl';preview(db.conn,path);summary,records=load_preview(path)
    db.conn.set_session(readonly=False)
    with db.conn.cursor() as c:c.execute("UPDATE raw_data.scraped_listings SET title='4 bedroom flat' WHERE id=%s",(r['id'],))
    db.conn.commit()
    assert apply_batch(db.conn,summary,records,uuid4(),write=True,ids=(r['id'],))['outcomes']=={'CONCURRENT_CHANGE':1}
    records[0]['after']['bathrooms']=8
    with pytest.raises(ReviewError):apply_batch(db.conn,summary,records,uuid4(),write=True)


def test_preview_before_room_migration_is_informational_only(pricing_writer,tmp_path):
    db=pricing_writer
    with db.conn.cursor() as c:c.execute('DROP VIEW raw_data.current_property_rooms CASCADE')
    db.conn.commit();path=tmp_path/'before-migration.jsonl'
    result=preview(db.conn,path)
    assert result['read_only'] and not result['apply_compatible']
    with pytest.raises(ReviewError):load_preview(path)


def test_room_audit_failure_rolls_back_numeric_fields_and_receipts(pricing_writer,tmp_path):
    db=pricing_writer;item,before=historical(db);db.conn.rollback();path=tmp_path/'failure.jsonl';preview(db.conn,path);artifact=load_preview(path)
    db.conn.set_session(readonly=False);run=uuid4()
    with db.conn.cursor() as c:
        c.execute("CREATE OR REPLACE FUNCTION raw_data.test_room_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.rule_version='property-rooms-v1' THEN RAISE EXCEPTION 'test room audit failure'; END IF; RETURN NEW; END $$")
        c.execute('CREATE TRIGGER test_room_failure BEFORE INSERT ON raw_data.property_fact_assessments FOR EACH ROW EXECUTE FUNCTION raw_data.test_room_failure()')
    db.conn.commit()
    try:
        with pytest.raises(psycopg2.Error):apply_batch(db.conn,*artifact,run,write=True,ids=(before['id'],))
        assert get_row(db,item.external_id)==before
        with db.conn.cursor() as c:
            c.execute('SELECT count(*) FROM raw_data.property_unification_receipts WHERE run_id=%s',(str(run),));assert c.fetchone()[0]==0
    finally:
        db.conn.rollback()
        with db.conn.cursor() as c:c.execute('DROP TRIGGER test_room_failure ON raw_data.property_fact_assessments')
        db.conn.commit()
