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
    import csv,hashlib
    worklist=Path(summary['worklist']['path'])
    assert hashlib.sha256(worklist.read_bytes()).hexdigest()==summary['worklist']['sha256']
    review=next(r for r in csv.DictReader(worklist.open()) if int(r['listing_id'])==before['id'])
    assert review['priority']=='0' and 'ROOM_COUNT_100_PLUS' in review['flags']
    assert review['bedrooms']=='1234' and review['bathrooms']=='123'
    assert apply_batch(db.conn,*artifact,run,ids=ids)['outcomes']=={'ELIGIBLE':1}
    assert get_row(db,item.external_id)==before;db.conn.rollback()
    assert apply_batch(db.conn,*artifact,run,write=True,ids=ids)['outcomes']=={'APPLIED':1}
    after=get_row(db,item.external_id);db.conn.rollback()
    assert after['bedrooms']==1234 and after['bathrooms']==123
    assert after['room_count_data']['bedrooms']['status']=='UNVERIFIED'
    assert after['room_count_data']['bedrooms']['value']==3
    assert after['room_count_data']['bathrooms']['status']=='UNVERIFIED'
    assert after['room_count_legacy']==dict(bedrooms=1234,bathrooms=123)
    with db.conn.cursor() as c:
        c.execute('SELECT room_review_flags,next_action FROM raw_data.property_review_queue WHERE listing_id=%s',(before['id'],))
        flags,action=c.fetchone()
        assert any(f['code']=='ROOM_COUNT_100_PLUS' for f in flags) and 'flagged room' in action
    db.conn.rollback()
    assert {k:v for k,v in before.items() if k not in FIELDS}=={k:v for k,v in after.items() if k not in FIELDS}
    assert apply_batch(db.conn,*artifact,run,write=True,ids=ids)['attempted']==0
    with pytest.raises(ReviewError):apply_batch(db.conn,*artifact,run,write=True)


def test_preserved_numbers_are_exposed_separately_from_supported_research_counts(pricing_writer,tmp_path):
    db=pricing_writer;item,before=historical(db);db.conn.rollback();path=tmp_path/'preserve.jsonl'
    summary=preview(db.conn,path)
    assert summary['counts']['bedrooms_existing_changed']==0
    assert summary['counts']['bathrooms_existing_changed']==0
    apply_batch(db.conn,*load_preview(path),uuid4(),write=True,ids=(before['id'],))
    with db.conn.cursor() as c:
        c.execute('''SELECT bedrooms_as_advertised,bathrooms_as_advertised,bedrooms_per_dwelling,
            bathrooms_per_dwelling,bedrooms_status,bathrooms_status,room_counts_current
            FROM raw_data.property_research_current WHERE listing_id=%s''',(before['id'],))
        assert c.fetchone()==(1234,123,None,None,'UNVERIFIED','UNVERIFIED',True)


def test_fresh_primary_metrics_correct_preserved_numbers_but_missing_fields_do_not(pricing_writer):
    db=pricing_writer;item,before=historical(db)
    # A new observation with no room metrics leaves the existing counts intact.
    absent=listing(title='3 bedroom flat',raw_bedrooms=None,raw_bathrooms=None)
    absent.external_id=item.external_id;db.upsert([absent],{})
    row=get_row(db,item.external_id)
    assert (row['bedrooms'],row['bathrooms'])==(1234,123)
    # A labelled primary observation supplies evidence for both corrections.
    observed=listing(title='3 bedroom flat',raw_bedrooms='3 Bedrooms',raw_bathrooms='2 Bathrooms')
    observed.external_id=item.external_id;db.upsert([observed],{})
    row=get_row(db,item.external_id)
    assert (row['bedrooms'],row['bathrooms'])==(3,2)
    assert row['room_count_legacy']==dict(bedrooms=1234,bathrooms=123)
    # A later omitted bathroom does not erase the supported number either.
    db.upsert([absent],{})
    row=get_row(db,item.external_id)
    assert (row['bedrooms'],row['bathrooms'])==(3,2)
    assert row['room_count_data']['bathrooms']['status']=='UNVERIFIED'


def test_recovery_targets_missing_bedrooms_even_when_bathrooms_are_supported(pricing_writer,tmp_path,monkeypatch):
    import json,os
    from contextlib import nullcontext
    from types import SimpleNamespace
    from scripts import refresh_room_counts as refresh
    db=pricing_writer;source='room-test-'+uuid4().hex
    item=listing(source=source,title='Flat for rent',description='A flat.',raw_bedrooms=None,raw_bathrooms='2 Bathrooms')
    db.upsert([item],{});before=get_row(db,item.external_id);db.conn.rollback()
    assert before['bedrooms'] is None and before['room_count_data']['bathrooms']['status']=='KNOWN'
    observed=listing(source=source,title='Flat for rent',description='A flat.',raw_bedrooms='3 Bedrooms',raw_bathrooms='2 Bathrooms')
    parser=SimpleNamespace(base_url='https://example.com',session=SimpleNamespace(get=lambda *a,**k:SimpleNamespace(status_code=404)))
    monkeypatch.setattr(refresh,'PARSERS',{source:lambda *a,**k:parser})
    monkeypatch.setattr(refresh,'recovery_traffic',nullcontext)
    monkeypatch.setattr(refresh.time,'sleep',lambda *a:None)
    monkeypatch.setattr(refresh,'primary_observation',lambda *a:(observed,'OBSERVED'))
    monkeypatch.setenv('DATABASE_URL',os.environ['TEST_DATABASE_URL'])
    output=tmp_path/'recovery.json'
    assert refresh.main(['--source',source,'--limit','1','--output',str(output)])==0
    report=json.loads(output.read_text())
    assert report['rows'][0]['listing_id']==before['id']
    assert report['summary']['bedrooms_newly_supported']==1
    assert report['summary']['bedrooms_proposed_fills']==1
    assert get_row(db,item.external_id)==before  # Default recovery is observation-only.


def test_batched_primary_observations_keep_actual_before_evidence_and_retry_cleanly(pricing_writer):
    from scraper.room_count_store import persist_many
    db=pricing_writer;item,before=historical(db)
    observed=listing(title='3 bedroom flat',raw_bedrooms='3 Bedrooms',raw_bathrooms='2 Bathrooms')
    observed.external_id=item.external_id;run=uuid4()
    with db.conn.cursor() as c:
        c.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=%s FOR UPDATE',(before['id'],));row,version=c.fetchone()
        result=persist_many(c,[(row,version)],run_id=run,observations={row['id']:observed})
        assert result[row['id']]['outcome']=='APPLIED'
        c.execute('SELECT facts FROM raw_data.property_fact_assessments WHERE id=%s',(result[row['id']]['assessment_id'],));facts=c.fetchone()[0]
        assert facts['before']['raw_bathrooms'] is None and facts['after']['raw_bathrooms']=='2 Bathrooms'
    db.conn.commit();after=get_row(db,item.external_id)
    assert (after['bedrooms'],after['bathrooms'])==(3,2)
    assert after['room_count_legacy']==dict(bedrooms=1234,bathrooms=123)
    with db.conn.cursor() as c:
        c.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=%s FOR UPDATE',(before['id'],));row,version=c.fetchone()
        result=persist_many(c,[(row,version)],run_id=uuid4(),observations={row['id']:observed})
        assert result[row['id']]['outcome']=='UNCHANGED'


def test_batched_observations_reject_mismatched_portal_identity(pricing_writer):
    from scraper.room_count_store import persist_many
    db=pricing_writer;item,before=historical(db)
    wrong=listing()
    with db.conn.cursor() as c:
        c.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE id=%s FOR UPDATE',(before['id'],));row,version=c.fetchone()
        with pytest.raises(ValueError):persist_many(c,[(row,version)],run_id=uuid4(),observations={row['id']:wrong})
    assert get_row(db,item.external_id)==before


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
