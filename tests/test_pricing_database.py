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
