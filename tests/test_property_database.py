"""Requires TEST_DATABASE_URL pointing at a disposable database, never production."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from uuid import uuid4
import psycopg2
import pytest
from psycopg2.extras import Json
from scraper.property_types import TYPES, VERSION, FIELDS, metadata
from scraper.normaliser import normalise
from tests.conftest import make_raw
from tests.test_pricing_database import pricing_writer, get_row, recovery_row


def item(**overrides):
    return normalise(make_raw(external_id=uuid4().hex, **overrides))


def audits(db, listing_id):
    with db.conn.cursor() as cur:
        cur.execute('SELECT origin,old_classification,new_classification FROM raw_data.property_classification_history WHERE listing_id=%s ORDER BY id', (listing_id,))
        return cur.fetchall()


def test_sql_vocabulary_matches_shared_definitions_and_migration_reruns(pricing_writer):
    db = pricing_writer
    with db.conn.cursor() as cur:
        cur.execute(Path('schema/006_property_classification.sql').read_text())
        cur.execute('SELECT code,category,family,attachment,asset_scope FROM raw_data.property_type_vocabulary WHERE version=%s ORDER BY code', (VERSION,))
        assert cur.fetchall() == [(code, d.category, d.family, d.attachment, d.scope) for code, d in sorted(TYPES.items())]


def test_legacy_migration_preserves_old_labels_prices_dates_and_no_fake_evidence(pricing_writer):
    db = pricing_writer
    with db.conn.cursor() as cur:
        cur.execute("INSERT INTO raw_data.scraped_listings(source,external_id,url,property_type,price_kobo) VALUES ('test',%s,'https://test','OLD_TITLE_FRAGMENT',123400) RETURNING id", (uuid4().hex,))
        row_id = cur.fetchone()[0]
        cur.execute('SELECT row_to_json(sl) FROM raw_data.scraped_listings sl WHERE id=%s', (row_id,))
        before = cur.fetchone()[0]
    db.conn.commit()
    with db.conn.cursor() as cur:
        cur.execute(Path('schema/006_property_classification.sql').read_text())
        cur.execute('SELECT row_to_json(sl) FROM raw_data.scraped_listings sl WHERE id=%s', (row_id,))
        assert cur.fetchone()[0] == before
    assert before['property_type_status'] == 'LEGACY_UNREVIEWED'
    assert before['property_type_raw'] is None
    assert audits(db, row_id) == []


def test_insert_update_idempotence_and_atomic_classification_history(pricing_writer):
    db = pricing_writer
    old = item(title='Detached duplex for sale', property_type_raw='Detached duplex')
    db.upsert([old], {})
    before = get_row(db, old.external_id)
    first_time = before['property_type_classified_at']
    assert before['property_type'] == 'DETACHED_DUPLEX'
    assert audits(db, before['id'])[0][1] is None
    db.upsert([old], {(old.source, old.external_id): old.price_kobo})
    assert len(audits(db, before['id'])) == 1
    assert get_row(db, old.external_id)['property_type_classified_at'] == first_time
    new = item(title='Semi-detached duplex for sale', property_type_raw='Semi-detached')
    new.external_id = old.external_id
    db.upsert([new], {(old.source, old.external_id): old.price_kobo})
    after = get_row(db, old.external_id)
    assert after['property_type'] == 'SEMI_DETACHED_DUPLEX'
    assert after['property_attachment'] == 'SEMI_DETACHED'
    events = audits(db, after['id'])
    assert len(events) == 2
    assert events[-1][1]['property_type'] == 'DETACHED_DUPLEX'
    assert events[-1][2]['property_type'] == 'SEMI_DETACHED_DUPLEX'
    assert after['price_kobo'] == before['price_kobo']
    assert after['first_seen_at'] == before['first_seen_at']


def test_relisting_conflict_path_persists_unresolved_classification(pricing_writer):
    db = pricing_writer
    old = item()
    db.upsert([old], {})
    before = get_row(db, old.external_id)
    with db.conn.cursor() as cur:
        cur.execute("UPDATE raw_data.scraped_listings SET listing_status='REMOVED' WHERE id=%s", (before['id'],))
    db.conn.commit()
    new = item(property_type_raw='Land', title='Luxury apartment')
    new.external_id = old.external_id
    db.upsert([new], {})
    after = get_row(db, old.external_id)
    assert after['listing_status'] == 'ACTIVE'
    assert after['property_type'] is None
    assert after['property_type_status'] == 'AMBIGUOUS'
    assert len(audits(db, after['id'])) == 2


def test_healthcheck_classification_is_independent_of_price_parse_failure(pricing_writer):
    db = pricing_writer
    old = item(title='Mini flat', property_type_raw=None)
    db.upsert([old], {})
    before = get_row(db, old.external_id)
    new = item(title='Studio apartment', property_type_raw='Studio', raw_price='USD 100')
    new.external_id = old.external_id
    db.confirm_listing_active(before['id'], None, observed_quote=new)
    after = get_row(db, old.external_id)
    assert after['price_kobo'] == before['price_kobo']
    assert after['property_type'] == 'STUDIO'
    assert after['title'] == 'Studio apartment'
    assert audits(db, after['id'])[-1][0] == 'HEALTH_CHECK'


def test_healthcheck_mismatched_identity_cannot_replace_classification(pricing_writer):
    db = pricing_writer
    old = item()
    db.upsert([old], {})
    before = get_row(db, old.external_id)
    db.confirm_listing_active(before['id'], None, observed_quote=item(title='Hotel', property_type_raw='Hotel'))
    assert get_row(db, old.external_id)['property_type'] == before['property_type']
    assert len(audits(db, before['id'])) == 1


def test_failed_audit_rolls_back_classification_price_and_current_evidence(pricing_writer, monkeypatch):
    import scraper.db_writer as module
    db = pricing_writer
    old = item()
    db.upsert([old], {})
    before = get_row(db, old.external_id)
    original = module.persist_classification
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('audit failure')
    monkeypatch.setattr(module, 'persist_classification', fail)
    new = item(title='Hotel', property_type_raw='Hotel', raw_price='₦20M')
    new.external_id = old.external_id
    with pytest.raises(RuntimeError):
        db.upsert([new], {(old.source, old.external_id): old.price_kobo})
    assert get_row(db, old.external_id) == before
    assert len(audits(db, before['id'])) == 1


@pytest.mark.parametrize('changes', [
    {'property_type': 'INVENTED_TYPE'}, {'property_category': 'LAND'},
    {'property_type_version': 'made-up-version'}, {'property_type_evidence': {}},
    {'property_type_status': 'INSUFFICIENT_EVIDENCE'}, {'property_attachment': 'DETACHED'},
    {'property_land_use': 'COMMERCIAL'},
])
def test_constraints_reject_incoherent_verified_results(pricing_writer, changes):
    db = pricing_writer
    old = item()
    db.upsert([old], {})
    before = get_row(db, old.external_id)
    with pytest.raises(psycopg2.Error):
        with db.conn.cursor() as cur:
            cur.execute('UPDATE raw_data.scraped_listings SET ' + ','.join(f'{key}=%s' for key in changes) + ' WHERE id=%s',
                        tuple(Json(v) if isinstance(v, dict) else v for v in changes.values()) + (before['id'],))
    db.conn.rollback()
    assert get_row(db, old.external_id) == before


def test_classification_history_is_append_only(pricing_writer):
    db = pricing_writer
    old = item()
    db.upsert([old], {})
    row = get_row(db, old.external_id)
    for operation in ('UPDATE raw_data.property_classification_history SET origin=origin',
                      'DELETE FROM raw_data.property_classification_history'):
        with pytest.raises(psycopg2.Error):
            with db.conn.cursor() as cur:
                cur.execute(operation + ' WHERE listing_id=%s', (row['id'],))
        db.conn.rollback()


def test_preview_reads_a_consistent_snapshot_and_cannot_apply(pricing_writer, tmp_path):
    from scripts.preview_property_classification import preview
    db = pricing_writer
    source = 'preview-' + uuid4().hex
    rows = [item(title='Mini flat', property_type_raw=None), item(title='4 bed', property_type_raw=None, description=None)]
    for row in rows:
        row.source = source
    db.upsert(rows, {})
    with db.conn.cursor() as cur:
        cur.execute("UPDATE raw_data.scraped_listings SET property_type_status='LEGACY_UNREVIEWED',property_type_version=NULL,property_type_classified_at=NULL,property_type='BAD_OLD_VALUE' WHERE source=%s", (source,))
    db.conn.commit()
    before = [recovery_row(db, row.external_id) for row in rows]
    output = tmp_path/'report.jsonl'
    summary = preview(db.conn, output, source=source, batch_size=1)
    assert summary['read_only'] is True
    assert summary['complete_database_scan'] is False
    assert summary['counts']['scanned'] == 2
    assert summary['statuses'] == {'CLASSIFIED': 1, 'INSUFFICIENT_EVIDENCE': 1}
    assert summary['report_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    decisions = [json.loads(line) for line in output.read_text().splitlines()]
    assert decisions[0]['previous']['property_type'] == 'BAD_OLD_VALUE'
    assert decisions[0]['proposed']['property_type'] == 'MINI_FLAT'
    assert decisions[1]['proposed']['property_type'] is None
    assert [recovery_row(db, row.external_id) for row in rows] == before
    db.conn.rollback()
    db.conn.set_session(readonly=False)


def test_preview_works_before_classification_migration(pricing_writer, tmp_path):
    # Proposal must not need the new columns to interpret old rows.
    from scripts.preview_property_classification import proposal
    result = proposal({'property_type': 'DETACHED_DUPLEX', 'title': 'A duplex', 'description': None})
    assert result['property_type'] == 'DUPLEX'
    assert result['property_type_raw'] is None


def test_initial_migration_preserves_preexisting_rows_and_preview_works_without_it(pricing_writer, tmp_path):
    from scripts.preview_property_classification import preview
    db = pricing_writer
    schema = 'property_test_' + uuid4().hex
    try:
        with db.conn.cursor() as cur:
            cur.execute(Path('schema/001_raw_data_schema.sql').read_text().replace('raw_data', schema))
            cur.execute(f"INSERT INTO {schema}.scraped_listings(source,external_id,url,title,property_type,price_kobo) VALUES ('test','old','https://test','A duplex','LEGACY_TITLE',1000)")
            cur.execute(f'SELECT row_to_json(sl) FROM {schema}.scraped_listings sl')
            before = cur.fetchone()[0]
        db.conn.commit()
        # The real preview SELECT relies only on row_to_json and original
        # columns. Use a connection adapter to point that same query at the
        # isolated pre-migration schema without dropping shared test tables.
        class Cursor:
            def __init__(self, cursor): self.cursor = cursor
            def __enter__(self): self.cursor.__enter__(); return self
            def __exit__(self, *args): return self.cursor.__exit__(*args)
            def execute(self, sql, params=None): return self.cursor.execute(sql.replace('raw_data.', schema + '.'), params)
            def __iter__(self): return iter(self.cursor)
            def __getattr__(self, key): return getattr(self.cursor, key)
        class Connection:
            def cursor(self, *args, **kwargs): return Cursor(db.conn.cursor(*args, **kwargs))
            def set_session(self, **kwargs): return db.conn.set_session(**kwargs)
            def rollback(self): return db.conn.rollback()
            def get_dsn_parameters(self): return db.conn.get_dsn_parameters()
        summary = preview(Connection(), tmp_path/'before.jsonl')
        assert summary['counts']['scanned'] == 1
        assert summary['types'] == {'DUPLEX': 1}
        db.conn.set_session(readonly=False)
        with db.conn.cursor() as cur:
            migration = Path('schema/006_property_classification.sql').read_text().replace('raw_data', schema)
            cur.execute(migration)
            cur.execute(migration)
            cur.execute(f'SELECT row_to_json(sl) FROM {schema}.scraped_listings sl')
            after = cur.fetchone()[0]
        assert all(after[key] == value for key, value in before.items())
        assert after['property_type_status'] == 'LEGACY_UNREVIEWED'
        assert after['property_type_raw'] is None
        assert after['property_type_classified_at'] is None
    finally:
        db.conn.rollback()
        db.conn.set_session(readonly=False)
        with db.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')
        db.conn.commit()
