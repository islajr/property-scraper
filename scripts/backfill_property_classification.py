"""Apply or reverse a reviewed property classification backfill.

Both subcommands default to a server-enforced read-only dry run. Writes require
--apply and migration 007. There are no portal requests or automatic migrations.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import UUID

from scraper.classification_artifact import ReviewError, reviewed_preview
from scraper.property_backfill import Selection, apply_preview, reverse_run
from scraper.property_types import TYPES, STATUSES


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def run_uuid(value):
    try:
        return str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError('must be a UUID') from None


def listing_ids(value):
    try:
        values = tuple(sorted({int(item) for item in value.split(',')}))
        if not values or any(item < 1 for item in values):
            raise ValueError
        return values
    except ValueError:
        raise argparse.ArgumentTypeError('must be comma-separated positive listing IDs') from None


def _write_report(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            json.dump(result, file, indent=2, sort_keys=True)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    for name in ('apply', 'reverse'):
        command = subparsers.add_parser(name)
        command.add_argument('--run-id', type=run_uuid, required=True)
        command.add_argument('--apply', action='store_true', help='Enable writes; omitted means read-only dry run')
        command.add_argument('--max-records', type=positive, default=100,
                             help='Maximum pending rows attempted this invocation (default 100)')
        command.add_argument('--source', choices=['propertypro', 'privateproperty', 'nigeriapropertycentre', 'jiji'])
        command.add_argument('--status', choices=['ACTIVE','REMOVED'])
        command.add_argument('--decision-status', choices=[s for s in STATUSES if s != 'LEGACY_UNREVIEWED'])
        command.add_argument('--type', choices=sorted(TYPES), dest='property_type')
        command.add_argument('--after-id', type=int, default=0)
        command.add_argument('--through-id', type=positive)
        command.add_argument('--ids', type=listing_ids, default=())
        command.add_argument('--output', type=Path)
        if name == 'apply':
            command.add_argument('--report', type=Path, required=True)
        else:
            command.add_argument('--original-run-id', type=run_uuid, required=True)
    args = parser.parse_args(argv)
    if args.after_id < 0 or (args.through_id is not None and args.through_id <= args.after_id):
        parser.error('ID bounds must be nonnegative and increasing')
    path = args.output or Path('.local/property-types')/f'{args.command}-{args.run_id}.json'
    if args.command == 'apply' and path.resolve() in (args.report.resolve(), args.report.with_suffix('.summary.json').resolve()):
        parser.error('--output must not overwrite the reviewed preview or its summary')
    selection = Selection(args.source, args.status, args.decision_status, args.property_type,
                          args.after_id, args.through_id, args.ids)
    from dotenv import load_dotenv
    import psycopg2
    load_dotenv()
    conn = None
    def connect():
        url = os.environ.get('DATABASE_URL')
        if not url:
            raise ReviewError('DATABASE_URL is required')
        return psycopg2.connect(url, connect_timeout=15,
                                application_name='property_classification_backfill')
    try:
        if args.command == 'apply':
            # Preflight the entire file before establishing a write connection.
            with reviewed_preview(args.report) as artifact:
                conn = connect()
                result = apply_preview(conn, artifact, args.run_id, selection=selection,
                                       write=args.apply, max_records=args.max_records)
        else:
            conn = connect()
            result = reverse_run(conn, args.original_run_id, args.run_id, selection=selection,
                                 write=args.apply, max_records=args.max_records)
        _write_report(path, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ReviewError as error:
        print(str(error), file=sys.stderr)
        return 1
    except psycopg2.Error:
        print('Database operation failed; connection details suppressed. Resume with the same run ID.', file=sys.stderr)
        return 1
    except OSError:
        print('Cannot save the local report. Committed receipts remain in PostgreSQL; resume with the same run ID.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Resume with the same run ID to reconcile committed receipts.', file=sys.stderr)
        return 130
    finally:
        if conn is not None:
            conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
