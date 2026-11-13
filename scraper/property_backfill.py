"""Bounded, auditable classification repair. Production writes are opt-in.

PostgreSQL receipts are the resume authority. A local report may be lost after a
commit without losing progress or applying the same decision twice.
"""
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID

import psycopg2
from psycopg2.extras import Json

from scraper.classification_artifact import ReviewError, database_fingerprint, classifier_fingerprint
from scraper.property_types import FIELDS, VERSION, classify, metadata, decision_key


@dataclass(frozen=True)
class Selection:
    source: str | None = None
    listing_status: str | None = None
    decision_status: str | None = None
    property_type: str | None = None
    after_id: int = 0
    through_id: int | None = None
    ids: tuple[int, ...] = ()

    def matches(self, record):
        proposed = record['proposed']
        return (record['id'] > self.after_id
                and (self.through_id is None or record['id'] <= self.through_id)
                and (not self.ids or record['id'] in self.ids)
                and (self.source is None or record['source'] == self.source)
                and (self.listing_status is None or record['listing_status'] == self.listing_status)
                and (self.decision_status is None or proposed['property_type_status'] == self.decision_status)
                and (self.property_type is None or proposed['property_type'] == self.property_type))

    def manifest(self):
        return {**asdict(self), 'ids': sorted(set(self.ids))}


def _normalized(value):
    result = metadata(value)
    date = result['property_type_classified_at']
    if date is not None:
        if isinstance(date, str):
            date = datetime.fromisoformat(date)
        result['property_type_classified_at'] = date.astimezone(timezone.utc).isoformat()
    return result


def _json(value):
    return Json(value, dumps=lambda item: json.dumps(item, default=str))


def _schema_available(cur):
    cur.execute("""SELECT to_regclass('raw_data.property_classification_operations') IS NOT NULL
        AND to_regclass('raw_data.property_classification_receipts') IS NOT NULL
        AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='raw_data'
                    AND table_name='property_classification_history' AND column_name='applied_row_version')""")
    return cur.fetchone()[0]


def _operation(cur, run_id):
    cur.execute('SELECT kind,database_fingerprint,manifest,reverse_of::text FROM raw_data.property_classification_operations WHERE run_id=%s', (run_id,))
    return cur.fetchone()


def _register(cur, run_id, kind, target, manifest, reverse_of):
    if kind == 'APPLY':
        cur.execute('SELECT 1 FROM raw_data.property_classification_operations WHERE reverse_of=%s LIMIT 1', (run_id,))
        if cur.fetchone():
            raise ReviewError('This apply run has a reversal; use a new preview and run ID for further repairs')
    cur.execute('''INSERT INTO raw_data.property_classification_operations
        (run_id,kind,database_fingerprint,manifest,reverse_of) VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (run_id) DO NOTHING''', (run_id, kind, target, _json(manifest), reverse_of))
    _check_operation(_operation(cur, run_id), kind, target, manifest, reverse_of)


def _check_operation(found, kind, target, manifest, reverse_of):
    if found and (found[0] != kind or found[1] != target or found[2] != manifest or found[3] != reverse_of):
        raise ReviewError('Run ID is already bound to another artifact, target, or selection')


def _write_decision(cur, lid, before, after, run_id, origin, reverses_id=None):
    """Only classification columns change; audit and receipt share this transaction."""
    cur.execute('UPDATE raw_data.scraped_listings SET ' +
                ', '.join(f'{key}=%({key})s' for key in FIELDS) + ' WHERE id=%(id)s',
                {**after, 'id': lid, 'property_type_evidence': _json(after['property_type_evidence'])})
    cur.execute('SELECT xmin::text FROM raw_data.scraped_listings WHERE id=%s', (lid,))
    version = cur.fetchone()[0]
    cur.execute('''INSERT INTO raw_data.property_classification_history
        (listing_id,run_id,origin,old_classification,new_classification,reverses_id,applied_row_version)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
        (lid, run_id, origin, _json(before), _json(after), reverses_id, version))
    return cur.fetchone()[0]


def _receipt(cur, run_id, record, outcome, history_id):
    cur.execute('''INSERT INTO raw_data.property_classification_receipts
        (run_id,listing_id,source,listing_status,outcome,history_id) VALUES (%s,%s,%s,%s,%s,%s)''',
        (run_id, record['id'], record['source'], record['listing_status'], outcome, history_id))


def _apply_one(cur, record, run_id, write):
    cur.execute('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE id=%s'
                + (' FOR UPDATE' if write else ''), (record['id'],))
    found = cur.fetchone()
    if not found:
        return 'MISSING', None
    row, version = found
    if (version != record['row_version'] or row['source'] != record['source']
            or row['listing_status'] != record['listing_status']
            or ('external_id' in record and row['external_id'] != record['external_id'])
            or _normalized(row) != _normalized(record['previous'])):
        return 'CONCURRENT_CHANGE', None
    new = asdict(classify(row.get('property_type_raw'), row.get('title'), row.get('description'),
                          row.get('property_type_raw_source')))
    if decision_key(new) != decision_key(record['proposed']):
        return 'PROPOSAL_MISMATCH', None
    if decision_key(row) == decision_key(new):
        return 'UNCHANGED', None
    if not write:
        return 'ELIGIBLE', None
    return 'APPLIED', _write_decision(cur, row['id'], metadata(row), new, run_id, 'BACKFILL')


def _reverse_one(cur, record, run_id, write):
    cur.execute('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE id=%s'
                + (' FOR UPDATE' if write else ''), (record['id'],))
    found = cur.fetchone()
    if not found:
        return 'MISSING', None
    row, version = found
    cur.execute('SELECT old_classification,new_classification,applied_row_version FROM raw_data.property_classification_history WHERE id=%s', (record['history_id'],))
    before, after, applied_version = cur.fetchone()
    cur.execute('SELECT 1 FROM raw_data.property_classification_history WHERE reverses_id=%s', (record['history_id'],))
    if cur.fetchone():
        return 'ALREADY_REVERSED', None
    cur.execute('SELECT id FROM raw_data.property_classification_history WHERE listing_id=%s ORDER BY id DESC LIMIT 1', (record['id'],))
    latest = cur.fetchone()[0]
    if (version != applied_version or latest != record['history_id']
            or _normalized(row) != _normalized(after)):
        return 'SUBSEQUENT_CHANGE', None
    if not write:
        return 'ELIGIBLE', None
    audit_id = _write_decision(cur, row['id'], metadata(row), before, run_id, 'REVERSAL', record['history_id'])
    return 'REVERSED', audit_id


def _process_one(conn, record, run_id, kind, write):
    try:
        with conn.cursor() as cur:
            if write:
                cur.execute("SET LOCAL lock_timeout='2s'")
                cur.execute("SET LOCAL statement_timeout='30s'")
            outcome, audit_id = (_apply_one if kind == 'APPLY' else _reverse_one)(cur, record, run_id, write)
            if write:
                _receipt(cur, run_id, record, outcome, audit_id)
        if write:
            conn.commit()
        return outcome
    except psycopg2.errors.LockNotAvailable:
        conn.rollback()
        return 'RETRYABLE_LOCK'
    except Exception:
        conn.rollback()
        raise


def _execute(conn, records, run_id, kind, target, manifest, selection, *,
             write=False, max_records=100, reverse_of=None, on_result=None):
    run_id = str(UUID(run_id))
    if max_records < 1:
        raise ReviewError('max_records must be positive')
    if target != database_fingerprint(conn):
        raise ReviewError('Database fingerprint differs from the reviewed target')
    result = dict(run_id=run_id, kind=kind, apply=write, read_only=not write,
                  max_records=max_records, outcomes=[], counts={},
                  database_fingerprint=target)
    counts, locked = Counter(), False
    # Apply and all reversals of that apply share one session lock. This also
    # freezes the set of applied receipts before a reversal manifest is bound.
    lock_owner = reverse_of or run_id
    lock_key = int.from_bytes(hashlib.sha256(('property-classification:' + lock_owner).encode()).digest()[:8], 'big', signed=True)
    try:
        conn.set_session(readonly=not write,
                         isolation_level='READ COMMITTED' if write else 'REPEATABLE READ', autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='30s'")
            available = _schema_available(cur)
            if write:
                if not available:
                    raise ReviewError('Apply migration 007 before enabling backfill writes')
                cur.execute('SELECT pg_try_advisory_lock(%s)', (lock_key,))
                locked = cur.fetchone()[0]
                if not locked:
                    raise ReviewError('Another process is already executing this run ID')
            selected = sum(selection.matches(row) for row in records())
            manifest = {**manifest, 'selection': selection.manifest(), 'selected': selected}
            result['selected'] = selected
            result['manifest'] = manifest
            if write:
                if kind == 'REVERSE' and selected == 0:
                    raise ReviewError('No applied listings match the reversal selection')
                _register(cur, run_id, kind, target, manifest, reverse_of)
            elif available:
                _check_operation(_operation(cur, run_id), kind, target, manifest, reverse_of)
            completed = set()
            if available:
                cur.execute('SELECT listing_id FROM raw_data.property_classification_receipts WHERE run_id=%s', (run_id,))
                completed = {row[0] for row in cur.fetchall()}
        if write:
            conn.commit()
        counts['already_completed'] = len(completed)
        for record in records():
            if not selection.matches(record) or record['id'] in completed:
                continue
            if counts['attempted'] >= max_records:
                break
            counts['attempted'] += 1
            outcome = _process_one(conn, record, run_id, kind, write)
            counts[outcome] += 1
            result['outcomes'].append(dict(id=record['id'], source=record['source'], outcome=outcome))
            if write and outcome != 'RETRYABLE_LOCK':
                completed.add(record['id'])
            if on_result:
                on_result(record['id'], outcome)
        result['counts'] = dict(counts)
        result['remaining'] = selected - len(completed)
        result['complete'] = write and result['remaining'] == 0
        return result
    finally:
        conn.rollback()
        if locked:
            with conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))
            conn.rollback()


def apply_preview(conn, artifact, run_id, *, selection=None, write=False, max_records=100, on_result=None):
    summary = artifact.summary
    manifest = dict(report_sha256=summary['report_sha256'], rule_version=summary['rule_version'],
                    execution_classifier_sha256=classifier_fingerprint())
    return _execute(conn, artifact.records, run_id, 'APPLY', summary['database_fingerprint'],
                    manifest, selection or Selection(), write=write, max_records=max_records, on_result=on_result)


def reverse_run(conn, original_run_id, run_id, *, selection=None, write=False, max_records=100, on_result=None):
    original_run_id, run_id = str(UUID(original_run_id)), str(UUID(run_id))
    if original_run_id == run_id:
        raise ReviewError('A reversal requires its own run ID')
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ', autocommit=False)
        with conn.cursor() as cur:
            if not _schema_available(cur):
                raise ReviewError('Migration 007 and an applied backfill are required for reversal')
            original = _operation(cur, original_run_id)
            if not original or original[0] != 'APPLY':
                raise ReviewError('Original run ID does not identify a backfill apply operation')
    finally:
        conn.rollback()
    rows = None
    def records():
        nonlocal rows
        if rows is None:
            with conn.cursor() as cur:
                cur.execute('''SELECT r.listing_id,r.source,r.listing_status,h.id,
                    h.new_classification->>'property_type_status',h.new_classification->>'property_type'
                    FROM raw_data.property_classification_receipts r
                    JOIN raw_data.property_classification_history h ON h.id=r.history_id
                    WHERE r.run_id=%s AND r.outcome='APPLIED' AND h.origin='BACKFILL'
                    ORDER BY r.listing_id''', (original_run_id,))
                rows = [dict(id=lid, source=source, listing_status=status, history_id=hid,
                             proposed=dict(property_type_status=state, property_type=code))
                        for lid, source, status, hid, state, code in cur.fetchall()]
        return iter(rows)
    manifest = dict(original_run_id=original_run_id, original_manifest=original[2])
    return _execute(conn, records, run_id, 'REVERSE', original[1], manifest,
                    selection or Selection(), write=write, max_records=max_records,
                    reverse_of=original_run_id, on_result=on_result)
