"""Preview or apply unified property assessments. Writes require --apply."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import UUID
from scraper.classification_artifact import ReviewError
from scraper.property_unification import preview,load_preview,apply_batch,reverse_batch


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('preview');p.add_argument('--output',required=True,type=Path)
    p=sub.add_parser('apply');p.add_argument('--report',required=True,type=Path)
    p.add_argument('--run-id',required=True,type=UUID)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--max-records',type=int,default=100)
    p.add_argument('--ids',type=str,help='Comma-separated listing IDs, for a canary selection')
    p=sub.add_parser('reverse');p.add_argument('--original-run-id',required=True,type=UUID)
    p.add_argument('--run-id',required=True,type=UUID);p.add_argument('--apply',action='store_true')
    p.add_argument('--max-records',type=int,default=100)
    args=parser.parse_args(argv)
    if args.command!='preview' and not 1<=args.max_records<=500:parser.error('--max-records must be between 1 and 500')
    ids=()
    if args.command=='apply' and args.ids:
        try:
            ids=tuple(sorted(set(int(i) for i in args.ids.split(','))))
            if any(i<1 for i in ids):raise ValueError
        except ValueError:parser.error('--ids must contain positive integer listing IDs')
    from dotenv import load_dotenv
    import psycopg2
    load_dotenv();conn=None
    try:
        artifact=load_preview(args.report) if args.command=='apply' else None
        url=os.environ.get('DATABASE_URL')
        if not url:raise ReviewError('DATABASE_URL is required')
        conn=psycopg2.connect(url,connect_timeout=15,application_name='property_unification',
            keepalives=1,keepalives_idle=15,keepalives_interval=5,keepalives_count=3,tcp_user_timeout=30000)
        if args.command=='preview':result=preview(conn,args.output)
        elif args.command=='reverse':result=reverse_batch(conn,args.original_run_id,args.run_id,write=args.apply,max_records=args.max_records)
        else:result=apply_batch(conn,*artifact,args.run_id,write=args.apply,max_records=args.max_records,ids=ids)
        print(json.dumps(result,indent=2,sort_keys=True));return 0
    except (ReviewError,ValueError,OSError,json.JSONDecodeError) as error:
        # Do not print arbitrary file contents or database connection parameters.
        print('Unification input or artifact validation failed. Check the report, rules, target and arguments.',file=sys.stderr);return 1
    except psycopg2.Error:
        print('Database operation failed; connection details suppressed. Retry the same run ID and report.',file=sys.stderr);return 1
    finally:
        if conn is not None:conn.close()


if __name__=='__main__':raise SystemExit(main())
