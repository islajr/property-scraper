import json
import csv
from uuid import uuid4
from tests.test_pricing_database import pricing_writer,listing,get_row
from scripts.export_room_review import export


def test_review_export_preserves_rows_reports_staleness_and_keeps_prior_annotations(pricing_writer,tmp_path):
    db=pricing_writer;item=listing(source='review-export-'+uuid4().hex);db.upsert([item],{})
    with db.conn.cursor() as q:q.execute('UPDATE raw_data.scraped_listings SET bedrooms=1234 WHERE external_id=%s',(item.external_id,))
    db.conn.commit();before=get_row(db,item.external_id);db.conn.rollback()
    report=export(db.conn,tmp_path)
    assert report['read_only'] and report['verification_logs'] is None
    path=report['files']['pending-room-review']['path']
    with open(path) as file:row=next(r for r in csv.DictReader(file) if r['external_id']==item.external_id)
    assert row['stored_bedrooms']=='1234' and row['room_counts_current']=='False'
    assert row['last_recorded_outcome']=='NO_IMPORTED_ATTEMPT' and row['action_code']=='REFRESH_STALE_SOURCE'
    assert get_row(db,item.external_id)==before;db.conn.rollback()
    with open(path,'a') as file:file.write('reviewer annotation retained\n')
    second=export(db.conn,tmp_path)
    assert second['files']['pending-room-review']['path']!=path
    with open(path) as file:assert file.read().endswith('reviewer annotation retained\n')


def test_incomplete_primary_visit_is_not_reported_as_no_successful_visit(pricing_writer,tmp_path):
    db=pricing_writer;item=listing(source='incomplete-body-'+uuid4().hex,raw_bathrooms=None);db.upsert([item],{})
    before=get_row(db,item.external_id);db.conn.rollback()
    logs=tmp_path/'logs';directory=logs/'verification-20261119T000000Z';directory.mkdir(parents=True)
    (directory/'outcomes.jsonl').write_text(json.dumps(dict(listing_id=before['id'],outcome='DESCRIPTION_MISSING_REVIEW_REQUIRED',observed_at='2026-11-19T00:00:00+00:00'))+'\n')
    report=export(db.conn,tmp_path/'review',verification_root=logs)
    with open(report['files']['pending-room-review']['path']) as file:
        row=next(r for r in csv.DictReader(file) if r['external_id']==item.external_id)
    assert row['room_counts_current']=='True' and row['bathrooms_status']=='UNKNOWN'
    assert row['last_recorded_outcome']=='DESCRIPTION_MISSING_REVIEW_REQUIRED'
    assert row['action_code']=='RECHECK_INCOMPLETE_PRIMARY_BODY'
    assert 'matching page was fetched' in row['next_action']
    assert 'No successful visit' not in row['next_action']
    assert get_row(db,item.external_id)==before
    db.conn.rollback()
