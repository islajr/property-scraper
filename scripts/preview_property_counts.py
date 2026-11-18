"""Read-only count-assessment preview. No apply mode, migrations, or portal requests."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
from scraper.property_counts import VERSION,assess_counts,extractor_hash


def preview(conn,output):
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    counts=Counter(scanned=0,with_accepted_counts=0,with_held_counts=0)
    relationships=Counter();states=Counter();questions=Counter();digest=hashlib.sha256();temporary=None
    try:
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SELECT transaction_timestamp(),current_setting('transaction_read_only')")
            snapshot,mode=cur.fetchone()
            if mode!='on':raise RuntimeError('Count preview requires read-only access')
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,prefix=output.name+'.',delete=False) as file:
            temporary=Path(file.name)
            with conn.cursor(name='property_count_preview') as cur:
                cur.itersize=500
                cur.execute('SELECT id,source,listing_status,title,description,xmin::text,external_id,property_type_raw FROM raw_data.scraped_listings ORDER BY id')
                for lid,source,status,title,description,row_version,external_id,raw_type in cur:
                    result=assess_counts(title,description,source=source,external_id=external_id,raw_type=raw_type)
                    counts['scanned']+=1
                    counts['with_accepted_counts']+=any(o['decision']=='ACCEPT' for o in result['observations'])
                    counts['with_held_counts']+=any(o['decision']=='HOLD' for o in result['observations'])
                    states[result['state']]+=1
                    relationships.update({o['relationship'] for o in result['observations'] if o['decision']=='ACCEPT'})
                    questions.update(q['reason'] for q in result['questions'])
                    record=dict(id=lid,source=source,listing_status=status,row_version=row_version,assessment=result)
                    line=json.dumps(record,sort_keys=True,ensure_ascii=False)+'\n'
                    file.write(line);digest.update(line.encode())
        conn.rollback();temporary.replace(output);temporary=None
        summary=dict(report_kind='property_count_assessment_preview',rule_version=VERSION,
                     read_only=True,apply_compatible=False,snapshot_at=str(snapshot),
                     extractor_sha256=extractor_hash(),report_sha256=digest.hexdigest(),
                     counts=dict(counts),states=dict(states),
                     listings_by_accepted_relationship=dict(relationships),questions=dict(questions))
        target=output.with_suffix('.summary.json')
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,prefix=target.name+'.',delete=False) as file:
            temporary=Path(file.name);file.write(json.dumps(summary,indent=2,sort_keys=True)+'\n')
        temporary.replace(target);temporary=None
        return summary
    finally:
        conn.rollback()
        if temporary:temporary.unlink(missing_ok=True)


def main(argv=None):
    import argparse,os,sys
    import psycopg2
    from dotenv import load_dotenv
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    load_dotenv();conn=None
    try:
        url=os.environ.get('DATABASE_URL')
        if not url:print('DATABASE_URL is required.',file=sys.stderr);return 1
        conn=psycopg2.connect(url,connect_timeout=15,application_name='property_count_preview_readonly',
                              keepalives=1,keepalives_idle=15,keepalives_interval=5,keepalives_count=3,tcp_user_timeout=30000)
        print(json.dumps(preview(conn,args.output),indent=2));return 0
    except psycopg2.Error:
        print('Count preview failed; connection details suppressed.',file=sys.stderr);return 1
    finally:
        if conn is not None:conn.close()


if __name__=='__main__':raise SystemExit(main())
