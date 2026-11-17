"""Profile saved count wording with server-enforced read-only access; no apply mode."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from scraper.property_count_profile import VERSION,profile_text


def profile(conn, output, *, batch_size=500):
    if batch_size < 1:
        raise ValueError('batch_size must be positive')
    output = Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    counts,states,entities,flags = Counter(),Counter(),Counter(),Counter()
    coverage = defaultdict(Counter)
    temporary = None
    digest = hashlib.sha256()
    try:
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SELECT transaction_timestamp(),current_setting('transaction_read_only')")
            snapshot,mode = cur.fetchone()
            if mode != 'on':
                raise RuntimeError('Count profiling requires a read-only transaction')
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,
                                         prefix=output.name+'.',suffix='.tmp',delete=False) as file:
            temporary = Path(file.name)
            with conn.cursor(name='property_count_profile') as cur:
                cur.itersize = batch_size
                cur.execute('SELECT id,source,listing_status,title,description,last_seen_at,xmin::text '
                            'FROM raw_data.scraped_listings ORDER BY id')
                for lid,source,status,title,description,last_seen,version in cur:
                    result = profile_text(title,description)
                    counts['scanned'] += 1
                    counts['candidate_mentions'] += len(result['candidates'])
                    counts['listings_with_candidates'] += bool(result['candidates'])
                    counts['truncated_listings'] += bool(result['truncated'])
                    states[result['state']] += 1
                    coverage[(source,status)][result['state']] += 1
                    entities.update({c['entity'] for c in result['candidates']})
                    flags.update({flag for c in result['candidates'] for flag in c['review_flags']})
                    record = dict(id=lid,source=source,listing_status=status,row_version=version,
                                  last_seen_at=last_seen,title=(title or '')[:2000],profile=result)
                    line = json.dumps(record,ensure_ascii=False,sort_keys=True,default=str)+'\n'
                    file.write(line);digest.update(line.encode())
        conn.rollback()
        temporary.replace(output);temporary=None
        summary = dict(report_kind='property_count_profile',profile_version=VERSION,read_only=True,
                       apply_compatible=False,snapshot_at=str(snapshot),complete_database_scan=True,
                       counts=dict(counts),states=dict(sorted(states.items())),
                       listings_by_candidate_entity=dict(sorted(entities.items())),
                       listings_by_review_flag=dict(sorted(flags.items())),
                       coverage=[dict(source=s,listing_status=t,states=dict(c)) for (s,t),c in sorted(coverage.items())],
                       profiler_sha256=hashlib.sha256(Path(sys.modules[profile_text.__module__].__file__).read_bytes()).hexdigest(),
                       report_sha256=digest.hexdigest())
        summary_path=output.with_suffix('.summary.json')
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,
                                         prefix=summary_path.name+'.',suffix='.tmp',delete=False) as file:
            temporary=Path(file.name);file.write(json.dumps(summary,indent=2,sort_keys=True)+'\n')
        temporary.replace(summary_path);temporary=None
        return summary
    finally:
        conn.rollback()
        if temporary:temporary.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    import os
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv()
    conn=None
    try:
        url=os.environ.get('DATABASE_URL')
        if not url:
            print('DATABASE_URL is required.',file=sys.stderr);return 1
        conn=psycopg2.connect(url,connect_timeout=15,application_name='property_count_profile_readonly',
                              keepalives=1,keepalives_idle=15,keepalives_interval=5,keepalives_count=3,tcp_user_timeout=30000)
        print(json.dumps(profile(conn,args.output),indent=2));return 0
    except psycopg2.Error:
        print('Count profile failed; connection details suppressed.',file=sys.stderr);return 1
    finally:
        if conn is not None:conn.close()


if __name__=='__main__':raise SystemExit(main())
