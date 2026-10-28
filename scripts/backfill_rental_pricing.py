#!/usr/bin/env python3
"""Bounded rental metadata recovery. Defaults to a read-only inventory.

No amount-based guesses, annualisation, FX conversions, or lifecycle writes.
Apply migration 004 before --apply. Live mode is opt-in and bounded by --limit.
"""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4, UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper.pricing import PERIOD_FIELDS, QUOTE_FIELDS, SHORT_LET, parse_amount, parse_terms, quote_dict, classify_change, comparable

RULE_VERSION = 'rental-period-v1'
AUDIT_FIELDS = (*QUOTE_FIELDS, 'price_parse_failed', 'pricing_observed_at')
SOURCES = ('propertypro', 'privateproperty', 'nigeriapropertycentre')


def metadata(row):
    return {k:row.get(k) for k in AUDIT_FIELDS}


def offline_proposal(row):
    """Only bind a historical cadence to evidence quoting the SAME saved NGN amount."""
    new = metadata(row)
    defaults = dict(price_period=None, price_period_count=None, price_period_status='UNKNOWN',
                    price_period_source='LEGACY_UNKNOWN', price_basis='UNKNOWN')
    for key,val in defaults.items():
        if new.get(key) is None: new[key]=val
    original = {**metadata(row), **{k: row.get(k) if row.get(k) is not None else v for k,v in defaults.items()}}
    kind = row.get('price_type')
    signal = next((row.get(field) for field in ('url','title') if SHORT_LET.search(row.get(field) or '')),None)
    if signal and kind != 'FOR_SHORT_LET':
        kind = new['price_type'] = 'FOR_SHORT_LET'
        new.update(price_period=None,price_period_count=None,price_period_status='UNKNOWN',
                   price_period_source='URL' if signal==row.get('url') else 'TITLE',price_period_evidence=signal[:1000])
    if kind=='FOR_SALE':
        new.update(price_period=None,price_period_count=None,price_period_status='NOT_APPLICABLE')
        return new if new!=original else None
    if kind not in ('FOR_RENT','FOR_SHORT_LET'):return None
    if row.get('price_period_status')=='KNOWN' and row.get('price_type')==kind:return None
    evidence=[]
    for field,source in [('raw_price_text','PORTAL_PRICE'),('title','TITLE'),('description','DESCRIPTION')]:
        for clause in re.split(r'[\n;!?]|(?<=\.)\s+',row.get(field) or ''):
            # Conservative: do not recover rent from fees, deposits, or minimum stays.
            if re.search(r'service|charge|deposit|caution|security|minimum|min\.?\s+stay|upfront',clause,re.I):continue
            for match in re.finditer(r'(?:₦|\bNGN\s*)\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|[kmb]\b)?',clause,re.I):
                excerpt=clause[match.start():match.end()+70]
                amount,failed=parse_amount(excerpt)
                terms=parse_terms(excerpt,kind,source)
                if not failed and amount==row.get('price_kobo') and terms.price_period_status in ('KNOWN','CONFLICT','UNSUPPORTED'):
                    evidence.append(terms)
    if evidence:
        known={(e.price_period,e.price_period_count) for e in evidence if e.price_period_status=='KNOWN'}
        first=evidence[0]
        fields=asdict(first)
        # Offline metadata recovery does not invent an original primary price label.
        fields['raw_price_text']=row.get('raw_price_text')
        fields['price_period_evidence']=' | '.join(e.price_period_evidence or '' for e in evidence)[:1000]
        if len(known)>1 or any(e.price_period_status=='CONFLICT' for e in evidence):
            fields.update(price_period=None,price_period_count=None,price_period_status='CONFLICT')
        new.update(fields)
    return new if new!=original else None


def apply_proposal(conn, row, new, run_id, mode):
    """Compare-and-set the whole quote, audit it, and write history in one transaction."""
    from psycopg2.extras import Json
    from scraper.db_writer import DatabaseWriter
    writer=DatabaseWriter.__new__(DatabaseWriter);writer.conn=conn
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE id=%s FOR UPDATE',(row['id'],))
            found=cur.fetchone()
            if not found or found[1]!=row['_row_version']:
                conn.rollback();return False
            old=metadata(found[0])
            cur.execute('UPDATE raw_data.scraped_listings SET '+', '.join(f'{k}=%({k})s' for k in AUDIT_FIELDS)+' WHERE id=%(id)s',{**new,'id':row['id']})
            cur.execute('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE id=%s',(row['id'],))
            after,version=cur.fetchone();after=metadata(after)
            cur.execute('''INSERT INTO raw_data.rental_pricing_backfills(run_id,listing_id,rule_version,old_pricing,new_pricing,applied_row_version)
                VALUES (%s,%s,%s,%s,%s,%s)''',(run_id,row['id'],RULE_VERSION,Json(old),Json(after),version))
            event=classify_change(old,after) if mode=='live' else 'PRICING_METADATA_BACKFILL'
            if event:
                writer._insert_history_events([dict(listing_id=row['id'],event_type=event,
                    old_value=old['price_kobo'],new_value=after['price_kobo'],old_pricing=old,new_pricing=after,
                    price_comparable=mode=='live' and comparable(old,after),notes=f'{mode} recovery run {run_id}')])
        conn.commit();return True
    except Exception:
        conn.rollback();raise


def rollback_run(conn,run_id,apply=False):
    with conn.cursor() as cur:
        cur.execute('SELECT id,listing_id,old_pricing,new_pricing,applied_row_version FROM raw_data.rental_pricing_backfills WHERE run_id=%s AND reversed_at IS NULL ORDER BY id DESC',(run_id,))
        entries=cur.fetchall()
    conn.commit()
    counts=Counter()
    for audit_id,listing_id,old,new,version in entries:
        with conn.cursor() as cur:
            cur.execute('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE id=%s'+(' FOR UPDATE' if apply else ''),(listing_id,))
            found=cur.fetchone()
            if not found or found[1]!=version or metadata(found[0])!=new:
                counts['changed_since_backfill']+=1;conn.rollback();continue
            counts['eligible']+=1
            if apply:
                cur.execute('UPDATE raw_data.scraped_listings SET '+', '.join(f'{k}=%({k})s' for k in AUDIT_FIELDS)+' WHERE id=%(id)s',{**old,'id':listing_id})
                cur.execute('UPDATE raw_data.rental_pricing_backfills SET reversed_at=NOW() WHERE id=%s',(audit_id,))
                # Keep original events, but a reversed observation cannot support a sale proxy.
                cur.execute('UPDATE raw_data.listing_history SET price_comparable=FALSE WHERE listing_id=%s AND notes=%s',
                            (listing_id,f'live recovery run {run_id}'))
                from scraper.db_writer import DatabaseWriter
                writer=DatabaseWriter.__new__(DatabaseWriter);writer.conn=conn
                writer._insert_history_events([dict(listing_id=listing_id,event_type='PRICING_BACKFILL_REVERSED',old_value=new['price_kobo'],new_value=old['price_kobo'],old_pricing=new,new_pricing=old,notes=f'Reversed recovery run {run_id}')])
                counts['reversed']+=1
        conn.commit()
    return counts


def live_proposal(row,parsers):
    parser=parsers.get(row['source'])
    if parser is None or row['listing_status']!='ACTIVE':return None,'ineligible'
    # No DB transaction/row lock is held during requests.
    parser._polite_delay()
    html=parser._get(row['url'])
    if not html:return None,'unavailable'
    final_url=getattr(parser,'last_response_url',row['url'])
    if parser._extract_external_id(final_url)!=row['external_id']:
        return None,'redirected'
    from bs4 import BeautifulSoup
    from scraper.normaliser import normalise
    raw=parser.parse_listing(BeautifulSoup(html,'html.parser'),final_url)
    if raw is None:return None,'unavailable'
    listing=normalise(raw)
    if listing.price_parse_failed:return None,'unparseable'
    new={**quote_dict(listing),'price_parse_failed':False,'pricing_observed_at':datetime.now(timezone.utc).isoformat()}
    if quote_dict(new)==quote_dict(row):return None,'unchanged'
    return new,'observed'


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments and arguments[0] in ('run','status','import-report','retry'):
        from scraper.recovery_runner import main as automated_main
        return automated_main(arguments)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('inventory','offline','live'),default='inventory')
    parser.add_argument('--apply',action='store_true',help='Write explicitly reviewed proposals; otherwise dry run')
    parser.add_argument('--source',choices=SOURCES)
    parser.add_argument('--status',choices=('ACTIVE','REMOVED'))
    parser.add_argument('--after-id',type=int,default=0)
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--batch-size',type=int,default=50)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--rollback-run',type=UUID)
    args=parser.parse_args(arguments)
    if args.mode=='live' and args.status=='REMOVED':parser.error('Live recovery only revisits ACTIVE listings')
    if not 1<=args.limit<=1000 or not 1<=args.batch_size<=200:parser.error('limit must be 1–1000; batch-size must be 1–200')
    if args.apply and args.mode=='inventory' and not args.rollback_run:parser.error('Inventory is read-only; choose offline or live before --apply')
    import config,psycopg2
    conn=psycopg2.connect(config.DATABASE_URL,connect_timeout=10)
    conn.set_session(readonly=not args.apply,autocommit=False)
    run_id=str(uuid4());counts=Counter();last_id=args.after_id
    print(f'Recovery run {run_id}',file=sys.stderr)
    report=dict(run_id=run_id,mode=args.mode,apply=args.apply,rule_version=RULE_VERSION)
    try:
        if args.rollback_run:
            report['counts']=dict(rollback_run(conn,str(args.rollback_run),args.apply))
        elif args.mode=='inventory':
            with conn.cursor() as cur:
                cur.execute('''SELECT price_type,source,listing_status,COALESCE(to_jsonb(sl)->>'price_period_status','UNKNOWN'), COUNT(*)
                    FROM raw_data.scraped_listings sl GROUP BY 1,2,3,4 ORDER BY 1,2,3,4''')
                report['inventory']=cur.fetchall()
        else:
            parsers={}
            if args.mode=='live':
                from scraper.parsers.propertypro import PropertyProParser
                from scraper.parsers.privateproperty import PrivatePropertyParser
                from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
                for cls in (PropertyProParser,PrivatePropertyParser,NigeriaPropertyCentreParser):
                    if not args.source or cls.source==args.source:parsers[cls.source]=cls({})
            processed=0
            while processed<args.limit:
                conditions=['id>%s',"(price_type IN ('FOR_RENT','FOR_SHORT_LET') OR url ~* 'short[-_ ]?let' OR title ~* 'short[-_ ]?let')"]
                params=[last_id]
                if args.source:conditions.append('source=%s');params.append(args.source)
                if args.status:conditions.append('listing_status=%s');params.append(args.status)
                if args.mode=='live':
                    conditions.extend(["listing_status='ACTIVE'", "COALESCE(to_jsonb(sl)->>'price_period_status','UNKNOWN') <> 'KNOWN'"])
                params.append(min(args.batch_size,args.limit-processed))
                with conn.cursor() as cur:
                    cur.execute('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE '+' AND '.join(conditions)+' ORDER BY id LIMIT %s',params)
                    rows=cur.fetchall()
                conn.commit()
                if not rows:break
                for row,version in rows:
                    row['_row_version']=version
                    if args.mode=='offline':new=offline_proposal(row)
                    else:
                        new,outcome=live_proposal(row,parsers);counts[outcome]+=1
                    counts['scanned']+=1
                    if new:
                        counts['proposed']+=1;counts[new['price_period_status']]+=1
                        if args.apply:counts['applied' if apply_proposal(conn,row,new,run_id,args.mode) else 'concurrent_update_skipped']+=1
                    else:counts['unchanged_or_unresolved']+=1
                    processed+=1;last_id=row['id']
                    if args.report:
                        progress={**report,'counts':dict(counts),'last_completed_id':last_id}
                        temp=args.report.with_suffix(args.report.suffix+'.tmp')
                        temp.write_text(json.dumps(progress,indent=2,default=str)+'\n')
                        temp.replace(args.report)
            report.update(counts=dict(counts),last_completed_id=last_id)
    finally:conn.close()
    output=json.dumps(report,indent=2,default=str)
    if args.report:args.report.write_text(output+'\n')
    print(output)
    return 0


if __name__=='__main__':raise SystemExit(main())
