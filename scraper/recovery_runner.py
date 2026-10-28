"""Bounded, resumable live recovery. Preview by default; explicit --apply writes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlparse
from uuid import uuid4

from scraper.recovery_policy import POLICY_VERSION, quote_decision, primary_purpose
from scraper.recovery_state import RecoveryState
from scraper.traffic_guard import TrafficBusy, recovery_traffic, single_recovery_runner

SOURCES = ('propertypro', 'privateproperty', 'nigeriapropertycentre')


class BudgetStop(Exception): pass
class RedirectOutsidePortal(Exception): pass


class Budget:
    def __init__(self, state, run_id, max_listings, max_http, max_seconds, stopped):
        self.state, self.run_id = state, run_id
        self.max_listings, self.max_http = max_listings, max_http
        self.deadline = time.monotonic()+max_seconds
        self.stopped, self.lock = stopped, threading.Lock()
        self.listings = self.http = 0
        self.reason = None

    def alive(self):
        return not self.stopped.is_set() and time.monotonic() < self.deadline

    def take_listing(self):
        with self.lock:
            if not self.alive():
                self.reason = 'interrupted' if self.stopped.is_set() else 'time_limit'
                return False
            if self.max_listings is not None and self.listings >= self.max_listings:
                self.reason = 'listing_limit'
                return False
            if self.http >= self.max_http:
                self.reason = 'http_limit'
                return False
            self.listings += 1
            return True

    def take_http(self):
        with self.lock:
            if not self.alive() or self.http >= self.max_http:
                self.reason = 'interrupted' if self.stopped.is_set() else 'http_or_time_limit'
                raise BudgetStop(self.reason)
            # Persist the reservation before send, including retries and redirects.
            self.state.request(self.run_id)
            self.http += 1


class Postgres:
    def __init__(self, apply=False):
        self.allow_apply = apply
        self._read = self._write = None

    def read(self):
        if self._read is None:
            import config, psycopg2
            self._read = psycopg2.connect(config.DATABASE_URL, connect_timeout=15)
            self._read.set_session(readonly=True, autocommit=True)
            with self._read.cursor() as cur: cur.execute("SET statement_timeout='30s'")
        return self._read

    def target(self):
        params = self.read().get_dsn_parameters()
        identity = {key:params.get(key) for key in ('host','port','dbname','user')}
        return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

    def candidates(self, sources):
        with self.read().cursor() as cur:
            cur.execute("""SELECT id,source,price_type FROM raw_data.scraped_listings
                WHERE source=ANY(%s) AND listing_status='ACTIVE'
                AND price_type IN ('FOR_RENT','FOR_SHORT_LET')
                AND price_period_status <> 'KNOWN' ORDER BY id""", (list(sources),))
            return cur.fetchall()

    def fetch(self, lid):
        with self.read().cursor() as cur:
            cur.execute('SELECT row_to_json(sl),xmin::text FROM raw_data.scraped_listings sl WHERE id=%s', (lid,))
            row = cur.fetchone()
        return {**row[0], '_row_version':row[1]} if row else None

    def audited(self, lid, run_id):
        with self.read().cursor() as cur:
            cur.execute('''SELECT EXISTS(SELECT 1 FROM raw_data.rental_pricing_backfills
                WHERE listing_id=%s AND run_id=%s AND reversed_at IS NULL)''', (lid,run_id))
            return cur.fetchone()[0]

    def apply(self, row, quote, run_id):
        if not self.allow_apply: raise RuntimeError('Production writes require --apply')
        if self._write is None:
            import config, psycopg2
            self._write = psycopg2.connect(config.DATABASE_URL,connect_timeout=15)
            with self._write.cursor() as cur:
                cur.execute("SET statement_timeout='30s'")
                cur.execute("SET lock_timeout='5s'")
            self._write.commit()
        from scripts.backfill_rental_pricing import apply_proposal
        return apply_proposal(self._write,row,quote,run_id,'live')

    def close(self):
        for conn in (self._read,self._write):
            if conn: conn.close()


class PageFetcher:
    """Reuse portal parsing/pacing; construct without unused robots.txt requests."""
    def __init__(self, source, budget, state):
        from scraper.parsers.propertypro import PropertyProParser
        from scraper.parsers.privateproperty import PrivatePropertyParser
        from scraper.parsers.nigeriapropertycentre import NigeriaPropertyCentreParser
        classes = {c.source:c for c in (PropertyProParser,PrivatePropertyParser,NigeriaPropertyCentreParser)}
        self.parser = classes[source]({},load_robots=False)
        self.parser.session.max_redirects = 5
        self.source, self.budget, self.state = source,budget,state
        self.context = {}
        host = urlparse(self.parser.base_url).hostname.removeprefix('www.')
        original_send = self.parser.session.send
        def send(request, **kwargs):
            requested = urlparse(request.url)
            if requested.scheme not in ('http','https') or (requested.hostname or '').removeprefix('www.') != host:
                raise RedirectOutsidePortal('Redirect outside the configured portal')
            self.budget.take_http()
            if not self.context.get('started'):
                self.state.start_visit(self.context['id'])
                self.context['started'] = True
            kwargs['timeout'] = 15
            self.context.pop('transport_error',None)
            try:
                return original_send(request,**kwargs)
            except Exception as exc:
                self.context['transport_error']=type(exc).__name__
                raise
        self.parser.session.send = send
        def response_seen(response,*args,**kwargs):
            self.context['status'] = response.status_code
        self.parser.session.hooks['response'].append(response_seen)

    def observe(self, row):
        from bs4 import BeautifulSoup
        from scraper.normaliser import normalise
        from scraper.pricing import quote_dict
        self.context = {'id':row['id']}
        self.parser._polite_delay()
        # Queue retries replace the discovery parser's long blocking backoff.
        import requests
        try:
            response = self.parser.session.get(row['url'])
            response.raise_for_status()
            html = response.text
            self.parser.last_response_url = response.url
        except requests.RequestException:
            html = None
        status = self.context.get('status')
        if html is None:
            retryable = bool(self.context.get('transport_error')) or status is None or status in (403,429) or status >= 500
            return dict(quote=None,purpose=None,retryable=retryable,
                        systemic=retryable,reason=f'http_{status}' if status else 'network_error')
        final = self.parser.last_response_url
        if self.parser._extract_external_id(final) != row['external_id']:
            return dict(quote=None,purpose=None,retryable=False,systemic=False,reason='redirected_identity')
        try:
            soup = BeautifulSoup(html,'html.parser')
            purpose = primary_purpose(soup,self.source)
            raw = self.parser.parse_listing(soup,final)
        except Exception as exc:
            return dict(quote=None,purpose=None,retryable=False,systemic=True,reason='parser_error:'+type(exc).__name__)
        if raw is None:
            return dict(quote=None,purpose=purpose,retryable=False,systemic=True,reason='primary_parser_failed')
        try:
            listing = normalise(raw)
        except Exception as exc:
            return dict(quote=None,purpose=purpose,retryable=False,systemic=True,reason='normalisation_error:'+type(exc).__name__)
        quote = {**quote_dict(listing),'price_parse_failed':listing.price_parse_failed,
                 'pricing_observed_at':datetime.now(timezone.utc).isoformat()}
        return dict(quote=quote,purpose=purpose,retryable=False,systemic=False,reason='observed')

    def close(self): self.parser.session.close()


class Runner:
    def __init__(self, state, args, provider_factory=None, fetcher_factory=None):
        self.state, self.args = state,args
        self.run_id = str(uuid4())
        self.stopped = threading.Event()
        self.budget = Budget(state,self.run_id,args.max_listings,args.max_http_requests,args.max_seconds,self.stopped)
        self.provider_factory = provider_factory or (lambda:Postgres(args.apply))
        self.fetcher_factory = fetcher_factory or PageFetcher
        self.report_lock = threading.Lock()
        self.report = state.directory/('run-'+self.run_id+'.json')
        self.journal = state.directory/('run-'+self.run_id+'.jsonl')
        self.fatal = False

    def emit(self, source, event, **fields):
        item = dict(time=datetime.now(timezone.utc).isoformat(),run_id=self.run_id,
                    source=source,event=event,**fields)
        with self.report_lock:
            with self.journal.open('a') as f: f.write(json.dumps(item)+'\n')
            snapshot = self.state.summary(self.run_id)
            snapshot.update(policy_version=POLICY_VERSION,report=str(self.report),last_event=item)
            temp = self.report.with_suffix('.tmp')
            temp.write_text(json.dumps(snapshot,indent=2)+'\n');temp.replace(self.report)
            print(json.dumps(item),flush=True)

    def finish(self, job, status, reason, retry_at=0, observation=None, clear_quote=False):
        self.state.finish(job,self.run_id,status,reason,retry_at,observation,clear_quote)
        self.emit(job['source'],status,listing_id=job['listing_id'],reason=reason)

    def saved(self, job, provider):
        row, quote = json.loads(job['row_json']),json.loads(job['quote_json'])
        # Reconcile DB commit-before-checkpoint crashes before considering any retry.
        if provider.audited(job['listing_id'],job['run_id']):
            self.finish(job,'applied','reconciled_database_audit');return
        current = provider.fetch(job['listing_id'])
        if not current or current['_row_version'] != row['_row_version']:
            self.finish(job,'skipped','changed_since_observation');return
        approved, reason = quote_decision(current,quote,job['visible_purpose'])
        if not approved:
            self.finish(job,'held',reason);return
        observed = datetime.fromisoformat(quote['pricing_observed_at'])
        if (datetime.now(timezone.utc)-observed).total_seconds() > self.args.max_quote_age:
            self.finish(job,'retryable','preview_expired',time.time()+300,clear_quote=True);return
        if not self.args.apply or self.stopped.is_set():
            self.finish(job,'previewed','reviewed_quote_saved');return
        applied = provider.apply(row,quote,job['run_id'])
        self.finish(job,'applied' if applied else 'skipped',
                    'explicit_primary_quote' if applied else 'concurrent_update')

    def worker(self, source):
        provider, fetcher = self.provider_factory(),None
        job = None
        try:
            portal = self.state.portal(source)
            if portal['cooldown_until'] > time.time():
                self.emit(source,'portal_deferred',until=portal['cooldown_until'],reason=portal['reason']);return
            while self.budget.alive():
                job = self.state.claim(source,self.args.apply,self.args.max_visits)
                if job is None:
                    self.emit(source,'no_ready_work');return
                if not self.budget.take_listing():
                    self.state.release(job);job=None;return
                if job['quote_json']:
                    self.saved(job,provider);job=None;continue
                row = provider.fetch(job['listing_id'])
                if not row or row['listing_status']!='ACTIVE' or row['price_type'] not in ('FOR_RENT','FOR_SHORT_LET') or row['price_period_status']=='KNOWN':
                    self.finish(job,'skipped','no_longer_eligible');job=None;continue
                waiting=False
                while self.budget.alive():
                    try:
                        with recovery_traffic():
                            if fetcher is None: fetcher=self.fetcher_factory(source,self.budget,self.state)
                            observation=fetcher.observe(row)
                        if waiting:self.emit(source,'resuming_after_health_check')
                        break
                    except TrafficBusy:
                        if not waiting:self.emit(source,'waiting_for_health_check',listing_id=job['listing_id'])
                        waiting=True
                        self.stopped.wait(5)
                else:
                    self.state.release(job);job=None;return
                approved, reason = quote_decision(row,observation['quote'],observation['purpose'])
                until = self.state.portal_result(source,observation['systemic'],observation['reason'],
                                                 self.args.failure_threshold,self.args.portal_cooldown)
                if approved:
                    audit_run=str(uuid4())
                    self.state.save_quote(job['listing_id'],row,observation['quote'],observation['purpose'],audit_run)
                    saved={**job,'row_json':json.dumps(row),'quote_json':json.dumps(observation['quote']),
                           'visible_purpose':observation['purpose'],'run_id':audit_run}
                    self.saved(saved,provider)
                elif observation['retryable']:
                    self.finish(job,'retryable',observation['reason'],time.time()+self.args.retry_delay,
                                (row,observation['quote'],observation['purpose']))
                else:
                    self.finish(job,'held',reason if observation['quote'] else observation['reason'],
                                observation=(row,observation['quote'],observation['purpose']))
                job=None
                if until:
                    self.emit(source,'portal_backoff',until=until);return
        except BudgetStop:
            if job: self.finish(job,'retryable','request_or_time_budget',time.time()+300)
        except RedirectOutsidePortal:
            if job: self.finish(job,'held','redirect_outside_portal')
            self.emit(source,'portal_stopped',reason='redirect_outside_portal')
        except Exception as exc:
            # Leave an in-progress quote intact for audit reconciliation on restart.
            self.fatal=True;self.stopped.set()
            self.emit(source,'worker_error',error=type(exc).__name__)
        finally:
            if fetcher: fetcher.close()
            provider.close()

    def run(self):
        self.state.recover_interrupted()
        self.state.begin_run(self.run_id,vars(self.args))
        self.emit(None,'started',apply=self.args.apply,max_listings=self.args.max_listings,
                  max_http_requests=self.args.max_http_requests,max_seconds=self.args.max_seconds)
        previous={}
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT,signal.SIGTERM):
                previous[signum]=signal.signal(signum,lambda *_:self.stopped.set())
        try:
            with ThreadPoolExecutor(max_workers=len(self.args.sources)) as pool:
                list(pool.map(self.worker,self.args.sources))
        finally:
            for signum,handler in previous.items():signal.signal(signum,handler)
            status='failed' if self.fatal else 'interrupted' if self.stopped.is_set() else self.budget.reason or 'no_ready_work'
            self.state.finish_run(self.run_id,status)
            self.emit(None,'finished',status=status,http_attempts=self.budget.http,listings_claimed=self.budget.listings)
        return 1 if self.fatal else 130 if self.stopped.is_set() else 0


def default_directory():
    return Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))/'property-scraper/rental-recovery'


def import_report(state,path,source=None):
    path=Path(path)
    if path.is_dir():
        files=sorted(path.glob('*-preview.json'))
        if not files:raise ValueError('No detailed preview files found in this directory')
        total=0
        for file in files:
            data=json.loads(file.read_text())
            if 'observations' in data:total+=import_report(state,file,source)
        if not total:raise ValueError('Directory has no live listing-level attempt records')
        return total
    data=json.loads(path.read_text());rows=data.get('observations')
    if rows is None:raise ValueError('Report has only counters; exact listing IDs are required to skip prior attempts safely')
    validated=[]
    for row in rows:
        portal=row.get('source') or data.get('source') or source
        if portal not in SOURCES or not isinstance(row.get('id'),int):raise ValueError('Report has an invalid source or listing ID')
        validated.append((row['id'],portal,'previous_live_attempt:'+str(row.get('outcome','reviewed'))))
    for lid,portal,reason in validated:state.import_attempt(lid,portal,reason)
    return len(validated)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run',help='Resume the queue; preview unless --apply is explicit')
    run.add_argument('--apply',action='store_true')
    run.add_argument('--sources',nargs='+',choices=SOURCES,default=list(SOURCES))
    run.add_argument('--max-listings',type=int,default=300)
    run.add_argument('--until-exhausted',action='store_true',help='Remove the listing-count cap; HTTP/time caps still apply')
    run.add_argument('--max-http-requests',type=int,default=1000)
    run.add_argument('--max-seconds',type=int,default=3600)
    run.add_argument('--max-visits',type=int,default=2)
    run.add_argument('--max-quote-age',type=int,default=86400)
    run.add_argument('--retry-delay',type=int,default=1800)
    run.add_argument('--failure-threshold',type=int,default=5)
    run.add_argument('--portal-cooldown',type=int,default=1800)
    status=sub.add_parser('status',help='Read local queue status without contacting the database or portals')
    status.add_argument('--review-report',type=Path)
    imp=sub.add_parser('import-report',help='Skip exact IDs from a previous detailed live preview')
    imp.add_argument('path',type=Path)
    imp.add_argument('--source',choices=SOURCES)
    retry=sub.add_parser('retry',help='Explicitly reconsider selected held/deferred listing IDs')
    retry.add_argument('ids',type=int,nargs='+')
    for cmd in (run,status,imp,retry):cmd.add_argument('--state-dir',type=Path,default=default_directory())
    args=parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.command=='run':
            positive=('max_listings','max_http_requests','max_seconds','max_visits','max_quote_age','retry_delay','failure_threshold','portal_cooldown')
            if any(getattr(args,k)<=0 for k in positive):parser.error('All budgets, cooldowns, and retry limits must be positive')
            args.state_dir=str(args.state_dir)
            if args.until_exhausted:args.max_listings=None
            with single_recovery_runner():
                provider=Postgres(args.apply)
                try:
                    state=RecoveryState(args.state_dir,provider.target())
                    added=state.seed(provider.candidates(args.sources))
                finally:provider.close()
                print(json.dumps(dict(event='queue_seeded',new_candidates=added,state_dir=args.state_dir)),flush=True)
                return Runner(state,args).run()
        if args.command=='status':
            state=RecoveryState.existing(args.state_dir)
            if args.review_report:
                with state.connect() as db:
                    items=[dict(r) for r in db.execute("SELECT listing_id,source,status,reason,quote_json FROM jobs WHERE status IN ('held','previewed') ORDER BY source,listing_id")]
                args.review_report.write_text(json.dumps(items,indent=2)+'\n')
            print(json.dumps(state.summary(),indent=2));return 0
        with single_recovery_runner():
            if args.command=='import-report':
                if (args.state_dir/'queue.sqlite3').exists():state=RecoveryState.existing(args.state_dir)
                else:
                    provider=Postgres(False)
                    try:state=RecoveryState(args.state_dir,provider.target())
                    finally:provider.close()
                print(json.dumps(dict(imported=import_report(state,args.path,args.source))));return 0
            state=RecoveryState.existing(args.state_dir);state.reset(args.ids)
            print(json.dumps(dict(event='selected_ids_reset',ids=args.ids)));return 0
    except (ValueError,TrafficBusy) as exc:
        parser.exit(2,str(exc)+'\n')
