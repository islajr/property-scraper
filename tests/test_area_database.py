from pathlib import Path
from uuid import uuid4
import pytest
from tests.test_pricing_database import pricing_writer,listing,get_row
from scraper.area_measurements import source_hash
from scraper.area_repair import preview,load_preview,apply_batch,reverse_batch
from scraper.area_store import FIELDS,persist
from scraper.classification_artifact import ReviewError
from psycopg2.extras import Json


def test_area_writer_and_reader_refresh_without_overwriting_existing_numbers(pricing_writer):
    db=pricing_writer;item=listing(raw_floor_area=None,title='House on 600sqm',description='Floor area: 250sqm')
    db.upsert([item],{});row=get_row(db,item.external_id)
    assert (row['floor_area_sqm'],row['land_area_sqm'])==(250,600)
    assert row['area_legacy']['floor_area_sqm'] is None
    with db.conn.cursor() as c:
        c.execute('SELECT supported_floor_area_sqm,supported_land_area_sqm,areas_current FROM research.properties WHERE listing_id=%s',(row['id'],))
        assert tuple(c.fetchone())==(250,600,True)
    new=listing(raw_floor_area=None,title='House on 650sqm',description='Floor area: 300sqm');new.external_id=item.external_id
    db.confirm_listing_active(row['id'],None,observed_quote=new)
    after=get_row(db,item.external_id)
    assert (after['floor_area_sqm'],after['land_area_sqm'])==(250,600)
    assert after['area_data']['floor_area_sqm']['status']=='UNVERIFIED'
    with db.conn.cursor() as c:
        c.execute('SELECT supported_floor_area_sqm,supported_land_area_sqm,areas_current FROM research.properties WHERE listing_id=%s',(row['id'],))
        assert c.fetchone()==(None,None,True)
        c.execute("UPDATE raw_data.scraped_listings SET title=title||' changed' WHERE id=%s",(row['id'],))
        c.execute('SELECT areas_current FROM research.properties WHERE listing_id=%s',(row['id'],));assert c.fetchone()==(False,)


def test_area_hash_sql_python_unicode_null_and_field_order(pricing_writer):
    data=dict(source='test',external_id='1',title='étage m² 🏠',description=None,
              raw_area_fields=[dict(role='LAND',label='Land size',value='500sqm',source='PRIMARY_LABEL'),
                               dict(role='UNSPECIFIED',label='Size',value='200sqm',source='LEGACY_UNSCOPED_FIELD')])
    with pricing_writer.conn.cursor() as c:
        c.execute('SELECT raw_data.property_area_source_hash(%s::jsonb)',(Json(data),))
        assert c.fetchone()[0]==source_hash(data)


def test_area_backfill_is_read_only_bounded_idempotent_and_reversible(pricing_writer,tmp_path):
    db=pricing_writer;item=listing(raw_floor_area=None,title='House on 600sqm',description='Floor area: 250sqm')
    db.upsert([item],{});r=get_row(db,item.external_id)
    with db.conn.cursor() as c:
        c.execute("UPDATE raw_data.scraped_listings SET floor_area_sqm=150,land_area_sqm=NULL,area_data='{}',area_legacy=NULL WHERE id=%s",(r['id'],))
    db.conn.commit();before=get_row(db,item.external_id);db.conn.rollback()
    path=tmp_path/'area.jsonl';summary=preview(db.conn,path);artifact=load_preview(path);run=uuid4()
    assert summary['counts']['floor_area_sqm_existing_changed']==0
    assert apply_batch(db.conn,*artifact,run,ids=(r['id'],))['outcomes']=={'ELIGIBLE':1}
    assert get_row(db,item.external_id)==before;db.conn.rollback()
    assert apply_batch(db.conn,*artifact,run,write=True,ids=(r['id'],))['outcomes']=={'APPLIED':1}
    after=get_row(db,item.external_id);db.conn.rollback()
    assert after['floor_area_sqm']==150 and after['land_area_sqm']==600
    assert {k:v for k,v in before.items() if k not in FIELDS}=={k:v for k,v in after.items() if k not in FIELDS}
    assert apply_batch(db.conn,*artifact,run,write=True,ids=(r['id'],))['attempted']==0
    assert reverse_batch(db.conn,run,uuid4())['outcomes']=={'ELIGIBLE':1}
    assert reverse_batch(db.conn,run,uuid4(),write=True)['outcomes']=={'REVERSED':1}
    assert get_row(db,item.external_id)==before


def test_area_unchanged_retry_has_no_duplicate_history(pricing_writer):
    db=pricing_writer;item=listing();db.upsert([item],{});r=get_row(db,item.external_id)
    with db.conn.cursor() as c:
        assert persist(c,r['id'],run_id=uuid4())['outcome']=='UNCHANGED'


def test_area_rollback_and_replay_preserve_consumer_extension(pricing_writer):
    db=pricing_writer
    with db.conn.cursor() as c:
        c.execute(Path('schema/014_research_entry_points.sql').read_text())
        c.execute(Path('schema/015_area_measurements.sql').read_text())
        c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='research' AND table_name='properties' AND column_name='areas_current'")
        assert c.fetchone()==('areas_current',)


def test_area_reversal_refuses_a_later_source_edit(pricing_writer,tmp_path):
    db=pricing_writer;item=listing();db.upsert([item],{});r=get_row(db,item.external_id)
    with db.conn.cursor() as c:
        c.execute("UPDATE raw_data.scraped_listings SET area_data='{}' WHERE id=%s",(r['id'],))
    db.conn.commit();path=tmp_path/'concurrent.jsonl';preview(db.conn,path);run=uuid4()
    apply_batch(db.conn,*load_preview(path),run,write=True,ids=(r['id'],))
    with db.conn.cursor() as c:c.execute("UPDATE raw_data.scraped_listings SET description='later source edit' WHERE id=%s",(r['id'],))
    db.conn.commit()
    assert reverse_batch(db.conn,run,uuid4(),write=True)['outcomes']=={'CONCURRENT_CHANGE':1}


def test_area_audit_is_rolled_back_with_transaction(pricing_writer):
    db=pricing_writer;item=listing();db.upsert([item],{});before=get_row(db,item.external_id);db.conn.rollback()
    run=uuid4()
    with db.conn.cursor() as c:
        c.execute("UPDATE raw_data.scraped_listings SET raw_floor_area='300sqm' WHERE id=%s",(before['id'],))
        assert persist(c,before['id'],run_id=run)['outcome']=='APPLIED'
    db.conn.rollback();assert get_row(db,item.external_id)==before
    with db.conn.cursor() as c:
        c.execute('SELECT count(*) FROM raw_data.property_fact_assessments WHERE run_id=%s',(str(run),));assert c.fetchone()==(0,)
