from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from uuid import uuid4
import pytest
from scraper import property_reviews
from scraper.classification_artifact import ReviewError
from scraper.property_types import classify
from scraper.property_counts import assess_counts,source_hash
from scraper.property_facts import assess_facts
from scraper.property_unification import preview,load_preview,apply_batch
from scraper.property_unification import reverse_batch
from tests.test_pricing_database import pricing_writer,get_row,listing


def test_review_is_bound_to_portal_identity_and_exact_saved_evidence(monkeypatch):
    values=[None,'Maisonette Duplex',None]
    digest=hashlib.sha256(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    review=dict(case_id='test',evidence_sha256=digest,classification={'property_type':'MAISONETTE'},
                note='Reviewed asset identity',reviewed_at='2026-11-18',questions=[],counts=[])
    monkeypatch.setitem(property_reviews._REVIEWS,('test','1'),review)
    result=classify(title=values[1],source='test',external_id='1')
    assert result.property_type=='MAISONETTE'
    assert result.property_type_evidence['human_review']['case_id']=='test'
    for kwargs in ({'source':'elsewhere','external_id':'1'},{'source':'test','external_id':'2'},
                   {'source':'test','external_id':'1','description':'New evidence'}):
        assert 'human_review' not in classify(title=values[1],**kwargs).property_type_evidence


def test_amenity_negation_location_and_unknown_are_preserved():
    facts=assess_facts('3 bedroom flat','Features:\nNo swimming pool. Shared gym. Private cinema. Near a gym.')
    by_key={f['feature']:f for f in facts['features']}
    assert by_key['SWIMMING_POOL']['claimed'] is False
    assert by_key['GYM']['scope']=='SHARED'
    assert by_key['CINEMA']['scope']=='PRIVATE'
    assert len([f for f in facts['features'] if f['feature']=='GYM'])==1
    assert assess_facts('House',None)['features']==[]
    assert any(f['feature']=='HOME_OFFICE' for f in assess_facts('4 bedroom duplex','Dedicated office space.')['features'])
    assert not assess_facts('Dedicated office space for rent',None)['features']
    assert not assess_counts('House with private cinema and home office')['observations']


def prepared(db,tmp_path):
    item=listing(title='One block containing four flats',property_type_raw=None)
    db.upsert([item],{});row=get_row(db,item.external_id);db.conn.rollback()
    path=tmp_path/'unification.jsonl';preview(db.conn,path);db.conn.set_session(readonly=False)
    return item,row,load_preview(path)


def test_frozen_preview_apply_retry_and_selection_binding(pricing_writer,tmp_path):
    db=pricing_writer;item,before,artifact=prepared(db,tmp_path);run=uuid4()
    dry=apply_batch(db.conn,*artifact,run,ids=(before['id'],))
    assert dry['outcomes']=={'ELIGIBLE':1}
    assert get_row(db,item.external_id)==before;db.conn.rollback()
    first=apply_batch(db.conn,*artifact,run,write=True,ids=(before['id'],))
    assert first['outcomes']=={'APPLIED':1}
    assert apply_batch(db.conn,*artifact,run,write=True,ids=(before['id'],))['attempted']==0
    with pytest.raises(ReviewError):apply_batch(db.conn,*artifact,run,write=True)
    with db.conn.cursor() as c:
        c.execute('SELECT contract_current,counts,bedrooms_per_dwelling FROM raw_data.property_research_current WHERE listing_id=%s',(before['id'],))
        current,counts,bedrooms=c.fetchone()
        assert current and bedrooms is None
        assert {(r['entity'],r['relationship'],r['minimum']) for r in counts}=={('BUILDING','OFFERED_ASSET',1),('DWELLING_UNIT','CONTAINED_UNIT',4)}


def test_concurrent_changes_and_mutated_artifact_cannot_be_applied(pricing_writer,tmp_path):
    db=pricing_writer;item,before,(summary,records)=prepared(db,tmp_path)
    with db.conn.cursor() as c:c.execute('UPDATE raw_data.scraped_listings SET title=%s WHERE id=%s',('New title',before['id']))
    db.conn.commit()
    result=apply_batch(db.conn,summary,records,uuid4(),write=True,ids=(before['id'],))
    assert result['outcomes']=={'CONCURRENT_CHANGE':1}
    records[0]['source']='changed'
    with pytest.raises(ReviewError):apply_batch(db.conn,summary,records,uuid4(),write=True)


def test_raw_label_changes_invalidate_counts_and_features(pricing_writer):
    db=pricing_writer;item=listing(title='3 bedroom flat',property_type_raw='Flat')
    db.upsert([item],{});row=get_row(db,item.external_id)
    with db.conn.cursor() as c:
        c.execute('SELECT count(*) FROM raw_data.current_property_counts WHERE listing_id=%s',(row['id'],));assert c.fetchone()[0]==1
        c.execute('UPDATE raw_data.scraped_listings SET property_type_raw=%s WHERE id=%s',('Room',row['id']))
        for view in ('current_property_counts','current_property_facts'):
            c.execute('SELECT count(*) FROM raw_data.'+view+' WHERE listing_id=%s',(row['id'],));assert c.fetchone()[0]==0
        c.execute('SELECT raw_data.property_evidence_hash(%s,%s,%s)',('₦三','😀','Flat'))
        assert c.fetchone()[0]==source_hash('₦三','😀','Flat')


def test_mixed_layout_review_retains_separate_parents():
    title='5 Flat Of 2no Of 2 Bedrm & 3no Of 1 Bedrm'
    result=assess_counts(title,'House for sale Anfani Off Ring Road Challenge Aso Ibadan Anfani Ibadan Oyo',source='propertypro',external_id='9PKBW')
    accepted=[o for o in result['observations'] if o['decision']=='ACCEPT']
    assert {(o['parent_key'],o['quantity']['minimum']) for o in accepted if o['relationship']=='BEDROOMS_PER_DWELLING'}=={('layout_2bed',2),('layout_1bed',1)}
    assert not any(o['relationship']=='OFFERED_ASSET' for o in accepted)


def test_uncertain_plural_assets_are_excluded_from_single_unit_price_candidates(pricing_writer):
    db=pricing_writer
    one=listing(title='3 bedroom flat',property_type_raw=None)
    several=listing(title='Four three-bedroom flats',property_type_raw=None)
    db.upsert([one,several],{})
    with db.conn.cursor() as c:
        c.execute('SELECT external_id,single_unit_price_candidate FROM raw_data.property_research_current WHERE external_id=ANY(%s)',([one.external_id,several.external_id],))
        assert dict(c.fetchall())=={one.external_id:True,several.external_id:False}


def test_old_checkpoint_classification_is_recomputed_on_observation(pricing_writer):
    db=pricing_writer;old=listing(title='3 bedroom flat',property_type_raw=None)
    old.property_type_version='property-types-v1';old.property_type='WAREHOUSE'
    db.upsert([old],{})
    saved=get_row(db,old.external_id)
    assert saved['property_type']=='FLAT_APARTMENT'
    assert saved['property_type_version']=='property-types-v3'


def test_bulk_apply_retains_all_observations_across_insert_pages(pricing_writer,tmp_path):
    from psycopg2.extras import execute_values
    db=pricing_writer
    with db.conn.cursor() as c:
        ids=execute_values(c,'''INSERT INTO raw_data.scraped_listings(source,external_id,url,title)
            VALUES %s RETURNING id''',
            [('test',uuid4().hex,'https://test','Three bedroom flat') for _ in range(120)],fetch=True)
    db.conn.commit();ids=tuple(r[0] for r in ids)
    path=tmp_path/'bulk.jsonl';preview(db.conn,path);artifact=load_preview(path)
    run=uuid4();result=apply_batch(db.conn,*artifact,run,write=True,ids=ids,max_records=120)
    assert result['outcomes']=={'APPLIED':120}
    with db.conn.cursor() as c:
        c.execute('SELECT count(*),count(*) FILTER(WHERE contract_current AND bedrooms_per_dwelling=3) FROM raw_data.property_research_current WHERE listing_id=ANY(%s)',(list(ids),))
        assert c.fetchone()==(120,120)
        c.execute('SELECT count(*) FROM raw_data.property_classification_history WHERE run_id=%s',(str(run),));assert c.fetchone()[0]==120


def test_batch_failure_rolls_back_classification_counts_audit_and_receipts(pricing_writer,tmp_path):
    db=pricing_writer;item,before,artifact=prepared(db,tmp_path)
    # Make a new source snapshot so the assessment insert is not a duplicate.
    with db.conn.cursor() as c:
        c.execute('UPDATE raw_data.scraped_listings SET title=%s WHERE id=%s',('Four three-bedroom flats sold together',before['id']))
    db.conn.commit();preview(db.conn,tmp_path/'failure.jsonl');artifact=load_preview(tmp_path/'failure.jsonl')
    db.conn.set_session(readonly=False)
    before=get_row(db,item.external_id);db.conn.rollback();run=uuid4()
    with db.conn.cursor() as c:
        c.execute("CREATE OR REPLACE FUNCTION raw_data.test_reject_facts() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test failure'; END $$")
        c.execute('CREATE TRIGGER test_reject_facts BEFORE INSERT ON raw_data.property_fact_assessments FOR EACH ROW EXECUTE FUNCTION raw_data.test_reject_facts()')
    db.conn.commit()
    try:
        import psycopg2
        with pytest.raises(psycopg2.Error):apply_batch(db.conn,*artifact,run,write=True,ids=(before['id'],))
        assert get_row(db,item.external_id)==before
        with db.conn.cursor() as c:
            for table in ('property_unification_runs','property_unification_receipts','property_count_assessments','property_fact_assessments','property_classification_history'):
                c.execute('SELECT count(*) FROM raw_data.'+table+' WHERE run_id=%s',(str(run),));assert c.fetchone()[0]==0
    finally:
        db.conn.rollback()
        with db.conn.cursor() as c:c.execute('DROP TRIGGER test_reject_facts ON raw_data.property_fact_assessments')
        db.conn.commit()


@pytest.mark.parametrize('intervening_price_edit',[False,True])
def test_safe_reversal_preserves_later_edits_and_prevents_resurrection(pricing_writer,tmp_path,intervening_price_edit):
    db=pricing_writer;item=listing(title='House available',property_type_raw=None)
    db.upsert([item],{});row=get_row(db,item.external_id)
    with db.conn.cursor() as c:
        c.execute("UPDATE raw_data.scraped_listings SET title='Four three-bedroom flats sold together',property_type_version='property-types-v1' WHERE id=%s",(row['id'],))
    db.conn.commit();before=get_row(db,item.external_id);db.conn.rollback()
    path=tmp_path/'reverse.jsonl';preview(db.conn,path);artifact=load_preview(path)
    run,reverse=uuid4(),uuid4()
    apply_batch(db.conn,*artifact,run,write=True,ids=(row['id'],))
    if intervening_price_edit:
        with db.conn.cursor() as c:c.execute('UPDATE raw_data.scraped_listings SET price_kobo=price_kobo+1 WHERE id=%s',(row['id'],))
        db.conn.commit()
    dry=reverse_batch(db.conn,run,reverse)
    assert dry['outcomes']==({'CONCURRENT_CHANGE':1} if intervening_price_edit else {'ELIGIBLE':1})
    result=reverse_batch(db.conn,run,reverse,write=True)
    assert result['outcomes']==({'CONCURRENT_CHANGE':1} if intervening_price_edit else {'REVERSED':1})
    if not intervening_price_edit:
        from scraper.property_types import metadata
        assert metadata(get_row(db,item.external_id))==metadata(before)
        with db.conn.cursor() as c:
            for view in ('current_property_counts','current_property_facts'):
                c.execute('SELECT count(*) FROM raw_data.'+view+' WHERE listing_id=%s',(row['id'],));assert c.fetchone()[0]==0
        db.conn.rollback()
    with pytest.raises(ReviewError):apply_batch(db.conn,*artifact,run,write=True,ids=(row['id'],))
    assert reverse_batch(db.conn,run,reverse,write=True)['attempted']==0
