"""Read-only classification preview. No apply mode, migrations or portal visits.

Run: python -m scripts.preview_property_classification --output .local/property-types/preview.jsonl
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from scraper.property_types import VERSION, classify, metadata, decision_key
from scraper.classification_artifact import database_fingerprint, classifier_fingerprint


def proposal(row):
    """Recover from original evidence, never the previous canonical/garbled type."""
    return asdict(classify(row.get('property_type_raw'), row.get('title'),
                           row.get('description'), row.get('property_type_raw_source')))


def preview(conn, output, *, source=None, status=None, after_id=0, limit=None, batch_size=500):
    """Stream one consistent read-only snapshot to an atomic local JSONL report.

    The summary binds to the report with SHA256. No UPDATE, migration, or portal
    client exists in this path. The server enforces the transaction's read-only
    mode, even if the configured account also has write privileges.
    """
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    conditions, params = ['sl.id > %s'], [after_id]
    if source:
        conditions.append('sl.source=%s')
        params.append(source)
    if status:
        conditions.append('sl.listing_status=%s')
        params.append(status)
    sql = ('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE '
           + ' AND '.join(conditions) + ' ORDER BY id')
    if limit is not None:
        sql += ' LIMIT %s'
        params.append(limit)
    states, types, transitions, counts = Counter(), Counter(), Counter(), Counter()
    coverage = defaultdict(Counter)
    digest = hashlib.sha256()
    temporary = None
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ', autocommit=False)
        target = database_fingerprint(conn)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SELECT transaction_timestamp(),current_setting('transaction_read_only')")
            snapshot, mode = cur.fetchone()
            if mode != 'on':
                raise RuntimeError('Preview requires a read-only database transaction')
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                         prefix=output.name + '.', suffix='.tmp', delete=False) as report:
            temporary = Path(report.name)
            with conn.cursor(name='property_classification_preview') as cur:
                cur.itersize = batch_size
                cur.execute(sql, params)
                for row, row_version in cur:
                    new = proposal(row)
                    before = metadata(row)
                    counts['scanned'] += 1
                    counts['type_changed' if row.get('property_type') != new['property_type'] else 'type_unchanged'] += 1
                    counts['decision_changed' if decision_key(before) != decision_key(new) else 'decision_unchanged'] += 1
                    counts['raw_label_available' if row.get('property_type_raw') else 'raw_label_unavailable'] += 1
                    states[new['property_type_status']] += 1
                    types[new['property_type'] or '(unresolved)'] += 1
                    transitions[(row.get('property_type'), new['property_type'], new['property_type_status'])] += 1
                    coverage[(row['source'], row['listing_status'])][new['property_type_status']] += 1
                    record = dict(id=row['id'], source=row['source'], listing_status=row['listing_status'],
                                  external_id=row['external_id'],
                                  title=(row.get('title') or '')[:2000], row_version=row_version,
                                  raw_label_available=bool(row.get('property_type_raw')),
                                  previous=before, proposed=new)
                    line = json.dumps(record, default=str, ensure_ascii=False, sort_keys=True) + '\n'
                    report.write(line)
                    digest.update(line.encode('utf-8'))
        conn.rollback()
        temporary.replace(output)
        temporary = None
        summary = dict(rule_version=VERSION, snapshot_at=str(snapshot), read_only=True,
                       report_format_version=2, classifier_sha256=classifier_fingerprint(),
                       database_fingerprint=target,
                       complete_database_scan=not (source or status or after_id or limit is not None),
                       filters=dict(source=source, status=status, after_id=after_id, limit=limit),
                       counts=dict(counts), statuses=dict(sorted(states.items())),
                       types=dict(sorted(types.items())),
                       coverage=[dict(source=s, listing_status=l, statuses=dict(sorted(c.items())))
                                 for (s, l), c in sorted(coverage.items())],
                       largest_transitions=[dict(previous=a, proposed=b, status=s, count=n)
                                            for (a, b, s), n in transitions.most_common(30)],
                       report_sha256=digest.hexdigest())
        summary_path = output.with_suffix('.summary.json')
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                         prefix=summary_path.name + '.', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            file.write(json.dumps(summary, indent=2, sort_keys=True) + '\n')
        temporary.replace(summary_path)
        temporary = None
        return summary
    finally:
        conn.rollback()
        if temporary:
            temporary.unlink(missing_ok=True)


def positive(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', choices=['propertypro', 'privateproperty', 'nigeriapropertycentre', 'jiji'])
    parser.add_argument('--status', choices=['ACTIVE', 'REMOVED'])
    parser.add_argument('--after-id', type=int, default=0)
    parser.add_argument('--limit', type=positive)
    parser.add_argument('--batch-size', type=positive, default=500)
    args = parser.parse_args(argv)
    if args.after_id < 0:
        parser.error('--after-id must be nonnegative')
    import psycopg2
    from dotenv import load_dotenv
    import os
    load_dotenv()
    conn = None
    try:
        url = os.environ.get('DATABASE_URL')
        if not url:
            print('DATABASE_URL is required.', file=sys.stderr)
            return 1
        conn = psycopg2.connect(url, connect_timeout=15,
                                application_name='property_classification_readonly_preview')
        summary = preview(conn, args.output, source=args.source, status=args.status,
                          after_id=args.after_id, limit=args.limit, batch_size=args.batch_size)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except psycopg2.Error:
        # libpq error strings may contain credentials. Never print them or a DSN.
        print('Database preview failed; connection details suppressed.', file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
