"""Preview/apply/reverse advertised-area repairs. Writes require --apply."""
import argparse,json,os,sys
from pathlib import Path
from uuid import UUID
from scraper.classification_artifact import ReviewError
from scraper.area_repair import preview,load_preview,apply_batch,reverse_batch


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('preview');q.add_argument('--output',required=True,type=Path)
    for name in ('apply','reverse'):
        q=sub.add_parser(name);q.add_argument('--run-id',type=UUID,required=True);q.add_argument('--apply',action='store_true')
        q.add_argument('--max-records',type=int,default=100)
        if name=='apply':q.add_argument('--report',required=True,type=Path);q.add_argument('--ids',help='Comma-separated positive canary listing IDs')
        else:q.add_argument('--original-run-id',type=UUID,required=True)
    args=p.parse_args(argv)
    if args.command!='preview' and not 1<=args.max_records<=500:p.error('--max-records must be between 1 and 500')
    ids=()
    if args.command=='apply' and args.ids:
        try:
            ids=tuple(sorted(set(int(i) for i in args.ids.split(','))))
            if any(i<1 for i in ids):raise ValueError
        except ValueError:p.error('--ids must contain positive listing IDs')
    from dotenv import load_dotenv
    import psycopg2
    load_dotenv();conn=None
    try:
        artifact=load_preview(args.report) if args.command=='apply' else None
        url=os.environ.get('DATABASE_URL')
        if not url:raise ReviewError('DATABASE_URL required')
        conn=psycopg2.connect(url,connect_timeout=15,application_name='area_repair',keepalives=1,keepalives_idle=15,
            keepalives_interval=5,keepalives_count=3,tcp_user_timeout=30000)
        if args.command=='preview':result=preview(conn,args.output)
        elif args.command=='apply':result=apply_batch(conn,*artifact,args.run_id,write=args.apply,max_records=args.max_records,ids=ids)
        else:result=reverse_batch(conn,args.original_run_id,args.run_id,write=args.apply,max_records=args.max_records)
        print(json.dumps(result,indent=2,sort_keys=True));return 0
    except psycopg2.Error:
        print('Database operation failed; connection details suppressed. Resume the same run/report.',file=sys.stderr);return 1
    except (ReviewError,ValueError,OSError,KeyError):
        print('Area-measurement input, target or artifact validation failed.',file=sys.stderr);return 1
    finally:
        if conn is not None:conn.close()


if __name__=='__main__':raise SystemExit(main())
