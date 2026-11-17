"""Explicit disposable TEST_DATABASE_URL only; never use production as a fixture."""
import hashlib
import json
from uuid import uuid4
import pytest
import psycopg2
from scraper.normaliser import normalise
from scripts.profile_property_counts import profile
from tests.conftest import make_raw
from tests.test_pricing_database import pricing_writer,get_row


def test_profile_uses_read_only_snapshot_preserves_rows_and_binds_report(pricing_writer,tmp_path):
    db=pricing_writer
    listing=normalise(make_raw(external_id=uuid4().hex,title='Four three-bedroom flats',
                               description='One block containing four flats'))
    listing.bedrooms=1234  # A legacy numeric column must never supply count candidates.
    db.upsert([listing],{})
    before=get_row(db,listing.external_id)
    db.conn.rollback()
    out=tmp_path/'counts.jsonl'
    summary=profile(db.conn,out,batch_size=2)
    assert summary['read_only'] and not summary['apply_compatible']
    assert summary['report_sha256']==hashlib.sha256(out.read_bytes()).hexdigest()
    records=[json.loads(line) for line in out.read_text().splitlines()]
    assert summary['counts']['scanned']==len(records)
    assert sum(summary['states'].values())==len(records)
    record=next(r for r in records if r['id']==before['id'])
    assert record['profile']['candidates']
    assert all(c['quantity']['minimum']!=1234 for c in record['profile']['candidates'])
    with db.conn.cursor() as cur:
        cur.execute('SHOW transaction_read_only')
        assert cur.fetchone()[0]=='on'
        with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
            cur.execute('UPDATE raw_data.scraped_listings SET title=title WHERE id=%s',(before['id'],))
    db.conn.rollback()
    db.conn.set_session(readonly=False)
    assert get_row(db,listing.external_id)==before
