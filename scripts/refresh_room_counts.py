"""Bounded primary-page room recovery. Default observes only; --apply saves rooms.

Only matching listing identity AND matching saved title/description are eligible.
Changed source text is deferred to the existing full health-check observation path,
not a mixture of fresh metrics and stale source text. Prices are never updated here.
"""
import argparse,json,os,sys,time,tempfile
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin,urlparse
from urllib.robotparser import RobotFileParser
from uuid import uuid4
from bs4 import BeautifulSoup
from scraper.classification_artifact import database_fingerprint
from scraper.normaliser import normalise
from scraper.parsers.propertypro import PropertyProParser
from scraper.parsers.privateproperty import PrivatePropertyParser
from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
from scraper.room_count_store import persist
from scraper.traffic_guard import recovery_traffic,TrafficBusy

PARSERS={p.source:p for p in (PropertyProParser,PrivatePropertyParser,NigeriaPropertyCentreParser)}


def primary_observation(parser,row,robots):
    if not robots.can_fetch(parser.HEADERS['User-Agent'],row['url']):return None,'ROBOTS_DISALLOWED'
    import requests
    try:
        response=parser.session.get(row['url'],timeout=15)
        if response.status_code!=200:return None,'HTTP_'+str(response.status_code)
        if urlparse(response.url).hostname!=urlparse(row['url']).hostname or parser._extract_external_id(response.url)!=row['external_id']:
            return None,'IDENTITY_CHANGED'
        soup=BeautifulSoup(response.text,'html.parser');canonical=soup.select_one('link[rel="canonical"]')
        if canonical and parser._extract_external_id(canonical.get('href',''))!=row['external_id']:return None,'IDENTITY_CHANGED'
        raw=parser.parse_listing(soup,response.url)
        if raw is None:return None,'PRIMARY_UNAVAILABLE'
        # Preserve exact snapshot semantics; cosmetic changes may be harmless,
        # but the full observation path is responsible for deciding that.
        if raw.title!=row.get('title') or raw.description!=row.get('description'):return None,'SOURCE_CHANGED_REFRESH_FULL_LISTING'
        return normalise(raw),'OBSERVED'
    except requests.RequestException:return None,'NETWORK_UNAVAILABLE'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--source',choices=sorted(PARSERS));p.add_argument('--after-id',type=int,default=0)
    p.add_argument('--limit',type=int,default=25);p.add_argument('--apply',action='store_true')
    p.add_argument('--ids',help='Comma-separated listing IDs from the prioritized worksheet')
    p.add_argument('--field',choices=('bedrooms','bathrooms','either'),default='either');args=p.parse_args(argv)
    os.umask(0o077)
    if args.output.exists():p.error('Use a new output path; completed recovery reports are never overwritten')
    if not 1<=args.limit<=250 or args.after_id<0:p.error('Use --limit 1..250 and a nonnegative --after-id')
    ids=()
    if args.ids:
        try:
            ids=tuple(sorted(set(int(i) for i in args.ids.split(','))))
            if not ids or len(ids)>250 or min(ids)<1:raise ValueError
        except ValueError:p.error('--ids requires 1..250 positive listing IDs')
    from dotenv import load_dotenv
    import psycopg2
    import requests
    load_dotenv();conn=None;temporary=None
    try:
        url=os.environ.get('DATABASE_URL')
        if not url:raise ValueError('DATABASE_URL required')
        conn=psycopg2.connect(url,connect_timeout=15,application_name='primary_room_recovery',keepalives=1,keepalives_idle=15,
            keepalives_interval=5,keepalives_count=3,tcp_user_timeout=30000)
        conn.set_session(readonly=True,autocommit=False)
        with conn.cursor() as c:
            c.execute("SET LOCAL statement_timeout='30s'")
            if args.apply:
                c.execute("SELECT to_regclass('raw_data.current_property_rooms') IS NOT NULL")
                if not c.fetchone()[0]:raise ValueError('Apply the room migration before enabling writes')
            conditions=["s.id>%s","s.listing_status='ACTIVE'"]
            params=[args.after_id]
            if ids:conditions.append('s.id=ANY(%s)');params.append(list(ids))
            else:
                fields=('bedrooms','bathrooms') if args.field=='either' else (args.field,)
                conditions.append('('+' OR '.join("coalesce(to_jsonb(s)->'room_count_data'->'%s'->>'status','PENDING') NOT IN ('KNOWN','NOT_APPLICABLE')" % field for field in fields)+')')
            if args.source:conditions.append('s.source=%s');params.append(args.source)
            params.append(args.limit)
            c.execute('SELECT row_to_json(s),xmin::text FROM raw_data.scraped_listings s WHERE '+' AND '.join(conditions)+' ORDER BY id LIMIT %s',params)
            targets=c.fetchall()
        conn.rollback();conn.set_session(readonly=not args.apply)
        report=dict(run_id=str(uuid4()),database_fingerprint=database_fingerprint(conn),apply=args.apply,
            observed_at=datetime.now(timezone.utc).isoformat(),rows=[],next_after_id=args.after_id,
            selection=dict(ids=list(ids),field=args.field,source=args.source,limit=args.limit),summary={})
        from collections import Counter
        from scraper.room_count_store import proposal
        metrics=Counter()
        parsers={};policies={}
        # Use the same lock directory as production when running from a worktree.
        with recovery_traffic():
            for row,version in targets:
                source=row['source'];entry=dict(listing_id=row['id'],source=source,url=row['url'])
                before=proposal(row)
                entry['before']={f:dict(value=row.get(f),status=before['room_count_data'][f]['status']) for f in ('bedrooms','bathrooms')}
                report['next_after_id']=row['id']
                if source not in PARSERS:entry['outcome']='UNSUPPORTED_SOURCE';report['rows'].append(entry);continue
                if source not in parsers:
                    parser=PARSERS[source]({},load_robots=False);parsers[source]=parser
                    robots=RobotFileParser()
                    try:
                        response=parser.session.get(urljoin(parser.base_url,'/robots.txt'),timeout=10)
                        if response.status_code==200:robots.parse(response.text.splitlines())
                        elif response.status_code==404:robots.parse([])
                        else:robots=None
                    except requests.RequestException:robots=None
                    policies[source]=robots
                if policies[source] is None:entry['outcome']='ROBOTS_UNAVAILABLE'
                else:
                    time.sleep(2.5)
                    observed,outcome=primary_observation(parsers[source],row,policies[source]);entry['outcome']=outcome
                    if observed:
                        entry.update(raw_bedrooms=observed.raw_bedrooms,raw_bathrooms=observed.raw_bathrooms,
                            metric_sources=observed.room_metric_sources)
                        after=proposal(row,listing=observed,previous=row)
                        entry['after']={f:dict(value=after[f],status=after['room_count_data'][f]['status'],
                            storage_action=after['room_count_data'][f]['storage_action']) for f in ('bedrooms','bathrooms')}
                        for field in ('bedrooms','bathrooms'):
                            if after['room_count_data'][field]['status']=='KNOWN':
                                metrics[field+'_supported_observations']+=1
                                if before['room_count_data'][field]['status']!='KNOWN':metrics[field+'_newly_supported']+=1
                            metrics[field+'_proposed_corrections']+=row.get(field) is not None and after[field]!=row.get(field)
                            metrics[field+'_proposed_fills']+=row.get(field) is None and after[field] is not None
                        if args.apply:
                            with conn.cursor() as c:
                                c.execute("SET LOCAL lock_timeout='3s'")
                                c.execute('SELECT xmin::text FROM raw_data.scraped_listings WHERE id=%s FOR UPDATE',(row['id'],));current=c.fetchone()
                                if not current or current[0]!=version:entry['outcome']='CONCURRENT_CHANGE'
                                else:entry['repair']=persist(c,row['id'],run_id=report['run_id'],listing=observed,previous=row)
                            conn.commit()
                        else:
                            entry['proposal']=after
                report['rows'].append(entry)
                metrics['attempted']+=1;metrics['outcome:'+entry['outcome']]+=1
                report['summary']=dict(metrics)
                # Keep completed per-row outcomes durable even if later requests fail.
                args.output.parent.mkdir(parents=True,exist_ok=True)
                with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=args.output.parent,delete=False) as file:
                    temporary=Path(file.name);file.write(json.dumps(report,indent=2)+'\n')
                temporary.replace(args.output);temporary=None
        if not args.output.exists():
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(dict(output=str(args.output),attempted=len(report['rows']),next_after_id=report['next_after_id'],apply=args.apply)));return 0
    except TrafficBusy:
        print('Health traffic owns the portal slot; recovery deferred.',file=sys.stderr);return 2
    except psycopg2.Error:
        print('Room recovery database operation failed; connection details suppressed. Inspect the saved outcomes before retry.',file=sys.stderr);return 1
    except (ValueError,OSError):
        print('Check recovery arguments, output permissions and migration state.',file=sys.stderr);return 1
    finally:
        if conn is not None:conn.close()
        if temporary:temporary.unlink(missing_ok=True)


if __name__=='__main__':raise SystemExit(main())
