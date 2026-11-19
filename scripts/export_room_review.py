"""Export current room coverage and actionable worksheets without database writes."""
import argparse
from collections import Counter
import csv
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

FIELDS=('bedrooms','bathrooms')
COLUMNS=('listing_id','source','external_id','url','title','listing_status','property_type','property_category',
 'asset_scope','priority','stored_bedrooms','stored_bathrooms','original_bedrooms','original_bathrooms',
 'bedrooms_status','bathrooms_status','bedroom_candidate','bathroom_candidate','bedroom_evidence_status',
 'bathroom_evidence_status','room_counts_current','review_flags','last_recorded_outcome','last_recorded_attempt_at',
 'last_health_check_at','action_code','next_action','source_hash','reviewed_bedrooms','reviewed_bathrooms',
 'reviewed_basis','review_result','review_evidence','reviewed_at','reviewer_note')


def read_attempts(root):
    latest={};invalid=0
    if root is None:return latest,invalid
    for path in sorted(Path(root).glob('verification-*/outcomes.jsonl')):
        with path.open() as file:
            for line in file:
                try:
                    entry=json.loads(line);lid=entry['listing_id']
                    if type(lid) is not int or not isinstance(entry.get('outcome'),str):raise ValueError
                    latest[lid]=entry
                except (ValueError,KeyError,TypeError):invalid+=1
    return latest,invalid


def next_action(row,attempt):
    outcome=attempt.get('outcome','');data=row['room_count_data'] or {}
    if not row['room_counts_current']:
        return 'REFRESH_STALE_SOURCE','Refresh the identity-matched primary listing and reassess before accepting a value from an old assessment.'
    if outcome in {'HTTP_404','HTTP_410','IDENTITY_CHANGED','PRIMARY_IDENTITY_UNAVAILABLE'}:
        return 'UNAVAILABLE_OR_REPLACED_PAGE','Locate a matching archived/primary advert or ask the agent for this exact listing. An unavailable page does not establish a room count or removal.'
    if outcome=='DESCRIPTION_MISSING_REVIEW_REQUIRED':
        return 'RECHECK_INCOMPLETE_PRIMARY_BODY','The matching page was fetched, but its description was missing and the saved source was preserved. Inspect the primary page and parser before a coherent refresh; do not replace saved text with an incomplete body.'
    if outcome.endswith('CHANGE_REVIEW_REQUIRED') or outcome=='ASSET_IDENTITY_REVIEW_REQUIRED':
        return 'RESOLVE_CHANGED_ASSET','Compare saved and current advert identity, location, type and unit scope; resolve the change before refreshing its counts.'
    if outcome.startswith(('HTTP_','ROBOTS_','SOURCE_PAUSED')) or outcome=='NETWORK_UNAVAILABLE':
        return 'BOUNDED_ACCESS_RETRY','Retry the same IDs in a bounded pass after access recovers, respecting robots rules and source backoff. Preserve existing values.'
    if row['property_category']=='LAND' and any((row[f] or 0)>0 for f in FIELDS):
        return 'LAND_OR_STRUCTURE_CONTEXT','Confirm whether the advert includes a habitable structure. Keep land and structure quantities separate; do not infer rooms from plots.'
    if any(data.get(f,{}).get('evidence_status')=='KNOWN' and row[f+'_status']=='UNVERIFIED' for f in FIELDS):
        return 'RECONCILE_SUPPORTED_CANDIDATE','The saved source supports a candidate that differs from the retained number. Revisit the primary page with the current parser; verify explicit metrics and per-unit basis, and record the evidence before correction.'
    if outcome in {'ROOM_OBSERVATION','FULL_OBSERVATION'}:
        return 'PRIMARY_QUANTITY_STILL_MISSING','A matching page was visited but did not settle this field. Inspect explicit title/description wording and unit basis; request the missing quantity from the portal/agent if needed. Do not substitute zero or copy another metric.'
    return 'PRIMARY_VERIFICATION_NEEDED','Check the exact primary page with the current parser and record explicit bedroom/bathroom evidence. No successful visit is established by the supplied run logs.'


def export(conn,output_dir,*,verification_root=None):
    os.umask(0o077);output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');attempts,invalid=read_attempts(verification_root)
    paths={kind:output_dir/(kind+'-'+stamp+'.csv') for kind in ('pending-room-review','remaining-exceptional-room-counts','remaining-100plus-room-counts')}
    temporaries={};handles={};writers={};counts=Counter();coverage=Counter();actions=Counter()
    conn.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
    try:
        with conn.cursor() as q:
            q.execute("SET LOCAL statement_timeout='90s'")
            q.execute("SELECT transaction_timestamp(),current_setting('transaction_read_only')")
            snapshot,mode=q.fetchone()
            if mode!='on':raise ValueError('Read-only export required')
        for kind in paths:
            file=tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=output_dir,delete=False,newline='')
            temporaries[kind]=Path(file.name);handles[kind]=file
            writer=csv.DictWriter(file,fieldnames=COLUMNS);writer.writeheader();writers[kind]=writer
        from psycopg2.extras import RealDictCursor
        with conn.cursor(name='current_room_review',cursor_factory=RealDictCursor) as q:
            q.itersize=500
            q.execute('''SELECT s.id,s.source,s.external_id,s.url,s.title,s.listing_status,s.property_type,
              s.property_category,s.property_asset_scope,s.bedrooms,s.bathrooms,s.room_count_data,s.room_count_legacy,
              s.last_health_check_at,r.bedrooms_status,r.bathrooms_status,r.room_counts_current
              FROM raw_data.scraped_listings s JOIN raw_data.property_research_current r ON r.listing_id=s.id ORDER BY s.id''')
            for row in q:
                counts['listings']+=1;data=row['room_count_data'] or {};flags=data.get('review_flags',[])
                for field in FIELDS:coverage[(row['source'],row['property_category'],row['listing_status'],field,row[field+'_status'])]+=1
                pending=flags or any(row[f+'_status'] not in {'KNOWN','NOT_APPLICABLE'} for f in FIELDS)
                if not pending:continue
                counts['pending']+=1;attempt=attempts.get(row['id'],{});action,note=next_action(row,attempt);actions[action]+=1
                bed=data.get('bedrooms',{});bath=data.get('bathrooms',{});legacy=row['room_count_legacy'] or {}
                record=dict.fromkeys(COLUMNS,'');record.update(listing_id=row['id'],source=row['source'],external_id=row['external_id'],
                    url=row['url'],title=row['title'],listing_status=row['listing_status'],property_type=row['property_type'],
                    property_category=row['property_category'],asset_scope=row['property_asset_scope'],priority=data.get('review_priority',4),
                    stored_bedrooms=row['bedrooms'],stored_bathrooms=row['bathrooms'],original_bedrooms=legacy.get('bedrooms'),
                    original_bathrooms=legacy.get('bathrooms'),bedrooms_status=row['bedrooms_status'],bathrooms_status=row['bathrooms_status'],
                    bedroom_candidate=bed.get('value'),bathroom_candidate=bath.get('value'),bedroom_evidence_status=bed.get('evidence_status'),
                    bathroom_evidence_status=bath.get('evidence_status'),room_counts_current=row['room_counts_current'],
                    review_flags=json.dumps(flags,sort_keys=True),last_recorded_outcome=attempt.get('outcome','NO_IMPORTED_ATTEMPT'),
                    last_recorded_attempt_at=attempt.get('observed_at',''),last_health_check_at=row['last_health_check_at'],
                    action_code=action,next_action=note,source_hash=data.get('source_hash',''))
                writers['pending-room-review'].writerow(record)
                if any(f.get('priority',5)<=1 for f in flags):writers['remaining-exceptional-room-counts'].writerow(record);counts['exceptional']+=1
                if any(row[f] is not None and row[f]>=100 for f in FIELDS):writers['remaining-100plus-room-counts'].writerow(record);counts['100plus']+=1
        conn.rollback()
        for kind,file in handles.items():file.close();temporaries[kind].replace(paths[kind])
        summary=dict(read_only=True,snapshot_at=str(snapshot),counts=dict(counts),actions=dict(actions),
            verification_logs=str(verification_root) if verification_root else None,imported_listing_attempts=len(attempts),
            skipped_invalid_log_lines=invalid,coverage=[dict(source=k[0],category=k[1],listing_status=k[2],field=k[3],status=k[4],count=v) for k,v in sorted(coverage.items(),key=lambda x:str(x[0]))],
            files={k:dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for k,p in paths.items()},
            review_note='Blank review columns are annotations only; editing a CSV does not update production. A checked decision still needs a source-bound, audited repair. A recorded attempt is not an independent inspection.')
        summary_path=output_dir/('room-review-'+stamp+'.json');summary_path.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
        temporary=output_dir/'current.json.tmp';temporary.write_text(json.dumps(dict(summary=str(summary_path.resolve()),files=summary['files']),indent=2)+'\n');temporary.replace(output_dir/'current.json')
        return summary
    finally:
        conn.rollback()
        for file in handles.values():file.close()
        for path in temporaries.values():path.unlink(missing_ok=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--verification-root',type=Path,help='Optional directory containing verification-*/outcomes.jsonl; absent logs do not imply no historic visit.')
    args=p.parse_args(argv)
    from dotenv import load_dotenv
    import psycopg2
    load_dotenv();conn=None
    try:
        conn=psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=15,application_name='room_review_readonly_export',
            keepalives=1,keepalives_idle=15,keepalives_interval=5,keepalives_count=3,tcp_user_timeout=30000)
        print(json.dumps(export(conn,args.output_dir,verification_root=args.verification_root),indent=2,sort_keys=True));return 0
    except (psycopg2.Error,ValueError,OSError,KeyError):
        print('Room review export failed; database and connection details suppressed.',file=sys.stderr);return 1
    finally:
        if conn is not None:conn.close()


if __name__=='__main__':raise SystemExit(main())
