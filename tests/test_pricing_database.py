"""Integration tests require an explicitly selected disposable PostgreSQL database.
Run with TEST_DATABASE_URL; DATABASE_URL is deliberately never used here.
"""
import os
from pathlib import Path
from uuid import uuid4
import pytest
from scraper.db_writer import DatabaseWriter
from scraper.normaliser import normalise
from scraper.pricing import quote_dict
from tests.conftest import make_raw


@pytest.fixture
def pricing_writer():
    url=os.environ.get('TEST_DATABASE_URL')
    if not url: pytest.skip('Set TEST_DATABASE_URL to a disposable PostgreSQL database')
    import psycopg2
    conn=psycopg2.connect(url);conn.autocommit=True
    with conn.cursor() as cur:
        for path in sorted(Path('schema').glob('*.sql')): cur.execute(path.read_text())
        cur.execute(Path('schema/004_rental_pricing.sql').read_text())
    conn.close()
    writer=DatabaseWriter(url)
    yield writer
    writer.close()


def listing(text='₦300,000 per month', **kwargs):
    return normalise(make_raw(external_id=uuid4().hex,raw_price=text,raw_price_type='FOR_RENT',**kwargs))


def get_row(writer, key):
    with writer.conn.cursor() as cur:
        cur.execute('SELECT row_to_json(s) FROM raw_data.scraped_listings s WHERE external_id=%s',(key,))
        return cur.fetchone()[0]


def history(writer,key):
    with writer.conn.cursor() as cur:
        cur.execute('SELECT h.event_type,h.price_comparable,h.old_pricing,h.new_pricing FROM raw_data.listing_history h JOIN raw_data.scraped_listings s ON s.id=h.listing_id WHERE s.external_id=%s ORDER BY h.id',(key,))
        return cur.fetchall()


@pytest.mark.parametrize('new_text,event,comparable',[
 ('₦250,000 per month','PRICE_CHANGE',True),
 ('₦300,000 per year','PRICING_CONTEXT_CHANGE',False),
 ('₦250,000 per year','PRICING_CONTEXT_CHANGE',False),
 ('₦250,000','PRICING_CONTEXT_CHANGE',False),
])
def test_atomic_quote_and_history(pricing_writer,new_text,event,comparable):
    db=pricing_writer;old=listing();db.upsert([old],{})
    new=listing(new_text);new.external_id=old.external_id
    stats=db.upsert([new],{(old.source,old.external_id):old.price_kobo})
    row=get_row(db,old.external_id)
    assert row['price_kobo']==new.price_kobo and row['price_period']==new.price_period
    assert row['pricing_observed_at'] is not None
    events=history(db,old.external_id)
    assert events[-1][0:2]==(event,comparable)
    assert events[-1][2]['price_period']=='MONTH'
    assert events[-1][3]['price_period']==new.price_period
    assert stats['price_changes']==int(comparable)


def test_healthcheck_enriches_legacy_unknown_without_price_reduction(pricing_writer):
    db=pricing_writer;old=listing('₦300,000');db.upsert([old],{})
    row=get_row(db,old.external_id)
    new=listing('₦300,000 per month');new.external_id=old.external_id
    assert db.confirm_listing_active(row['id'],old.first_seen_at,observed_quote=new) is False
    assert history(db,old.external_id)[-1][0]=='PRICING_CONTEXT_CHANGE'
    assert get_row(db,old.external_id)['price_period']=='MONTH'


def test_rejected_quote_preserves_previous_quote_but_confirms_activity(pricing_writer):
    db=pricing_writer;old=listing();db.upsert([old],{})
    row=get_row(db,old.external_id)
    new=listing('USD 50 per night')
    db.confirm_listing_active(row['id'],None,observed_quote=new)
    after=get_row(db,old.external_id)
    assert quote_dict(after)==quote_dict(row)
    assert after['last_health_check_at'] is not None
    assert history(db,old.external_id)[-1][0]=='PRICING_OBSERVATION_REJECTED'


def test_relisting_updates_quote_without_duplicate_listed_event(pricing_writer):
    db=pricing_writer;old=listing();db.upsert([old],{})
    with db.conn.cursor() as cur:cur.execute("UPDATE raw_data.scraped_listings SET listing_status='REMOVED' WHERE external_id=%s",(old.external_id,))
    db.conn.commit()
    new=listing('₦90,000/night');new.external_id=old.external_id
    stats=db.upsert([new],{})
    assert get_row(db,old.external_id)['price_period']=='NIGHT'
    assert get_row(db,old.external_id)['listing_status']=='ACTIVE'
    assert [e[0] for e in history(db,old.external_id)].count('LISTED')==1
    assert 'RELISTED' in [e[0] for e in history(db,old.external_id)]
    assert stats['new']==0 and stats['updated']==1


def test_quote_update_rolls_back_when_history_write_fails(pricing_writer,monkeypatch):
    db=pricing_writer;old=listing();db.upsert([old],{})
    before=get_row(db,old.external_id)
    new=listing('₦20,000/day');new.external_id=old.external_id
    def fail(events):raise RuntimeError('history insert failed')
    monkeypatch.setattr(db,'_insert_history_events',fail)
    with pytest.raises(RuntimeError):db.upsert([new],{(old.source,old.external_id):old.price_kobo})
    assert quote_dict(get_row(db,old.external_id))==quote_dict(before)


def test_only_comparable_whole_property_ngn_rentals_enter_view(pricing_writer):
    db=pricing_writer
    records=[listing('₦20,000/day'),listing('₦20,000'),listing('₦20,000 per sqm/year'),listing('USD 20/day')]
    db.upsert(records,{})
    with db.conn.cursor() as cur:
        cur.execute('SELECT external_id FROM raw_data.comparable_rental_prices WHERE external_id=ANY(%s)',([r.external_id for r in records],))
        assert cur.fetchall()==[(records[0].external_id,)]


def recovery_row(db,external_id):
    with db.conn.cursor() as cur:
        cur.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE external_id=%s',(external_id,))
        row,version=cur.fetchone()
    db.conn.commit()
    return {**row,'_row_version':version}


def test_backfill_audit_idempotence_and_safe_reversal(pricing_writer):
    from scripts.backfill_rental_pricing import offline_proposal,apply_proposal,rollback_run
    db=pricing_writer
    old=listing('₦300,000');old.description='Rent: ₦300,000 per month'
    db.upsert([old],{})
    before=recovery_row(db,old.external_id)
    proposal=offline_proposal(before);assert proposal
    run_id=str(uuid4())
    assert apply_proposal(db.conn,before,proposal,run_id,'offline')
    after=recovery_row(db,old.external_id)
    assert offline_proposal(after) is None
    assert after['last_seen_at']==before['last_seen_at']
    assert after['last_health_check_at']==before['last_health_check_at']
    assert rollback_run(db.conn,run_id,False)['eligible']==1
    assert get_row(db,old.external_id)['price_period']=='MONTH'
    db.conn.commit()
    assert rollback_run(db.conn,run_id,True)['reversed']==1
    assert get_row(db,old.external_id)['price_period_status']=='UNKNOWN'
    assert rollback_run(db.conn,run_id,True)['reversed']==0


def test_backfill_and_reversal_skip_concurrent_changes(pricing_writer):
    from scripts.backfill_rental_pricing import offline_proposal,apply_proposal,rollback_run
    db=pricing_writer
    old=listing('₦300,000');old.description='₦300,000 per month'
    db.upsert([old],{})
    before=recovery_row(db,old.external_id)
    # Another transaction changed the row after the report was collected.
    with db.conn.cursor() as cur:cur.execute('UPDATE raw_data.scraped_listings SET title=%s WHERE id=%s',('new title',before['id']))
    db.conn.commit()
    run_id=str(uuid4())
    assert not apply_proposal(db.conn,before,offline_proposal(before),run_id,'offline')
    current=recovery_row(db,old.external_id)
    assert apply_proposal(db.conn,current,offline_proposal(current),run_id,'offline')
    new=listing('₦250,000/year');new.external_id=old.external_id
    db.upsert([new],{(old.source,old.external_id):old.price_kobo})
    assert rollback_run(db.conn,run_id,True)['changed_since_backfill']==1
    assert get_row(db,old.external_id)['price_period']=='YEAR'


def test_recovery_transaction_rolls_back_if_audit_insert_fails(pricing_writer):
    from scripts.backfill_rental_pricing import offline_proposal,apply_proposal
    db=pricing_writer;old=listing('₦300,000');old.description='₦300,000/month'
    db.upsert([old],{});before=recovery_row(db,old.external_id)
    with pytest.raises(Exception):apply_proposal(db.conn,before,offline_proposal(before),'not-a-uuid','offline')
    assert get_row(db,old.external_id)['price_period_status']=='UNKNOWN'


def test_rental_summary_separates_cadence_and_count(pricing_writer):
    db=pricing_writer
    records=[listing('₦300,000/month'),listing('₦3,000,000/year'),listing('₦300,000 per 2 months'),listing('₦300,000')]
    for item in records:item.neighbourhood=uuid4().hex
    shared_area=records[0].neighbourhood
    for item in records:item.neighbourhood=shared_area
    db.upsert(records,{})
    with db.conn.cursor() as cur:
        cur.execute('SELECT price_period,price_period_count,listing_count FROM raw_data.rental_price_summary WHERE neighbourhood=%s ORDER BY price_period,price_period_count',(shared_area,))
        assert cur.fetchall()==[('MONTH',1,1),('MONTH',2,1),('YEAR',1,1)]


def test_sale_legacy_migration_does_not_invent_rental_units_or_change_price(pricing_writer):
    db=pricing_writer;key=uuid4().hex
    with db.conn.cursor() as cur:
        cur.execute("INSERT INTO raw_data.scraped_listings(source,external_id,url,price_type,price_kobo) VALUES ('test',%s,'https://test','FOR_SALE',4500000000)",(key,))
    db.conn.commit()
    before=get_row(db,key)
    with db.conn.cursor() as cur:cur.execute(Path('schema/004_rental_pricing.sql').read_text())
    after=get_row(db,key)
    assert after['price_period_status']=='NOT_APPLICABLE'
    assert after['price_kobo']==before['price_kobo']
    assert after['pricing_observed_at'] is None
    assert after['first_seen_at']==before['first_seen_at']


def test_url_backfill_type_correction_has_no_assumed_cadence(pricing_writer):
    from scripts.backfill_rental_pricing import offline_proposal,apply_proposal
    db=pricing_writer;old=listing('₦300,000')
    old.url='https://test/for-rent/short-let/'+old.external_id
    db.upsert([old],{});before=recovery_row(db,old.external_id)
    assert apply_proposal(db.conn,before,offline_proposal(before),str(uuid4()),'offline')
    after=get_row(db,old.external_id)
    assert after['price_type']=='FOR_SHORT_LET' and after['price_period_source']=='URL'
    assert after['price_period_status']=='UNKNOWN'


def test_reversing_live_recovery_invalidates_its_reduction_comparability(pricing_writer):
    from scripts.backfill_rental_pricing import apply_proposal,rollback_run,metadata
    db=pricing_writer;old=listing();db.upsert([old],{})
    before=recovery_row(db,old.external_id)
    new={**metadata(before),'price_kobo':20000000}
    run_id=str(uuid4())
    assert apply_proposal(db.conn,before,new,run_id,'live')
    assert history(db,old.external_id)[-1][0:2]==('PRICE_CHANGE',True)
    assert rollback_run(db.conn,run_id,True)['reversed']==1
    events=history(db,old.external_id)
    assert next(e for e in events if e[0]=='PRICE_CHANGE')[1] is False
    assert get_row(db,old.external_id)['price_kobo']==old.price_kobo


def test_automated_recovery_preview_and_apply_use_real_audited_transaction(pricing_writer,tmp_path,monkeypatch):
    import config
    from scraper.recovery_runner import Runner,Postgres
    from scraper.recovery_state import RecoveryState
    from tests.test_recovery_runner import args,Fetchers
    monkeypatch.setattr(config,'DATABASE_URL',os.environ['TEST_DATABASE_URL'])
    db=pricing_writer;old=listing('₦3M');db.upsert([old],{})
    before=recovery_row(db,old.external_id)
    provider=Postgres(False)
    try:
        with provider.read().cursor() as cur:
            cur.execute('SHOW transaction_read_only');assert cur.fetchone()[0]=='on'
        with pytest.raises(RuntimeError,match='--apply'):provider.apply(before,{},str(uuid4()))
        state=RecoveryState(tmp_path,provider.target())
        state.seed([(before['id'],before['source'],before['price_type'])])
    finally:provider.close()
    fetchers=Fetchers()
    assert Runner(state,args(),fetcher_factory=fetchers.factory).run()==0
    assert get_row(db,old.external_id)['price_period_status']=='UNKNOWN'
    db.conn.commit()
    assert Runner(state,args(apply=True),fetcher_factory=fetchers.factory).run()==0
    after=recovery_row(db,old.external_id)
    assert after['price_period']=='YEAR'
    assert after['last_seen_at']==before['last_seen_at']
    assert after['last_health_check_at']==before['last_health_check_at']
    assert fetchers.calls==[before['id']]
    with db.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM raw_data.rental_pricing_backfills WHERE listing_id=%s',(before['id'],))
        assert cur.fetchone()[0]==1
    db.conn.commit()
    assert Runner(state,args(apply=True),fetcher_factory=fetchers.factory).run()==0
    assert fetchers.calls==[before['id']]
