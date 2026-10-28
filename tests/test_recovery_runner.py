from argparse import Namespace
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import json
import threading
from uuid import uuid4
import pytest
from scraper.recovery_runner import Runner,Budget,import_report
from scraper.recovery_state import RecoveryState
from scraper.normaliser import normalise
from scraper.pricing import quote_dict
from tests.conftest import make_raw


def args(**updates):
    config=dict(apply=False,sources=['propertypro'],max_listings=100,max_http_requests=100,
                max_seconds=30,max_visits=2,max_quote_age=86400,retry_delay=1800,
                failure_threshold=5,portal_cooldown=1800,state_dir='test',command='run')
    return Namespace(**{**config,**updates})


def old_row(lid,source='propertypro'):
    return {**asdict(normalise(make_raw(raw_price='₦3M',raw_price_type='FOR_RENT',source=source))),
            'id':lid,'_row_version':'original-'+str(lid)}


def quote(text='₦3M/year'):
    listing=normalise(make_raw(raw_price=text,raw_price_type='FOR_RENT'))
    return {**quote_dict(listing),'price_parse_failed':listing.price_parse_failed,
            'pricing_observed_at':datetime.now(timezone.utc).isoformat()}


class Backend:
    def __init__(self,rows):self.rows={r['id']:r for r in rows};self.audits={};self.writes=0;self.crash_after_commit=False
    def factory(self):return Provider(self)


class Provider:
    def __init__(self,backend):self.backend=backend
    def fetch(self,lid):return self.backend.rows.get(lid)
    def audited(self,lid,run_id):return (lid,run_id) in self.backend.audits
    def apply(self,row,new,run_id):
        self.backend.writes+=1
        self.backend.audits[(row['id'],run_id)]=new
        self.backend.rows[row['id']]={**row,**new,'_row_version':'updated'}
        if self.backend.crash_after_commit:
            self.backend.crash_after_commit=False
            raise RuntimeError('DB committed before local checkpoint')
        return True
    def close(self):pass


class Fetchers:
    def __init__(self,results=None):self.calls=[];self.results=results or {}
    def factory(self,source,budget,state):
        parent=self
        class Fetcher:
            def observe(self,row):
                budget.take_http();state.start_visit(row['id']);parent.calls.append(row['id'])
                result=parent.results.get(row['id'],quote())
                return dict(quote=result,purpose=None,retryable=False,systemic=False,reason='observed')
            def close(self):pass
        return Fetcher()


def make_state(tmp_path,rows):
    state=RecoveryState(tmp_path,'test')
    state.seed([(r['id'],r['source'],r['price_type']) for r in rows])
    return state,Backend(rows)


def test_preview_then_apply_reuses_quotes_and_does_not_retry_unknowns(tmp_path):
    state,backend=make_state(tmp_path,[old_row(1),old_row(2),old_row(3)])
    fetchers=Fetchers({2:quote('₦3M'),3:quote('$300/year')})
    first=Runner(state,args(),backend.factory,fetchers.factory)
    assert first.run()==0 and backend.writes==0
    with state.connect() as db:
        held=db.execute("SELECT quote_json FROM jobs WHERE listing_id=3").fetchone()
        assert json.loads(held[0])['price_currency']=='USD'
    second=Runner(state,args(apply=True),backend.factory,fetchers.factory)
    assert second.run()==0 and backend.writes==1
    assert fetchers.calls==[1,2,3]
    assert second.budget.http==0
    assert json.loads(second.report.read_text())['outcomes'][0]['outcome']=='applied'


def test_crash_after_commit_reconciles_audit_without_refetch_or_duplicate_write(tmp_path):
    state,backend=make_state(tmp_path,[old_row(1)]);fetchers=Fetchers();backend.crash_after_commit=True
    first=Runner(state,args(apply=True),backend.factory,fetchers.factory)
    assert first.run()==1 and backend.writes==1
    second=Runner(state,args(apply=True),backend.factory,fetchers.factory)
    assert second.run()==0 and backend.writes==1
    assert fetchers.calls==[1]
    with state.connect() as db:assert db.execute('SELECT status FROM jobs').fetchone()[0]=='applied'


def test_global_http_cap_stops_new_visits_and_resumes_remaining_queue(tmp_path):
    state,backend=make_state(tmp_path,[old_row(n) for n in range(1,5)]);fetchers=Fetchers()
    first=Runner(state,args(max_http_requests=1),backend.factory,fetchers.factory)
    assert first.run()==0 and first.budget.http==1
    second=Runner(state,args(),backend.factory,fetchers.factory)
    assert second.run()==0 and fetchers.calls==[1,2,3,4]
    assert backend.writes==0


def test_unknown_missing_period_is_held_across_restarts(tmp_path):
    state,backend=make_state(tmp_path,[old_row(1)]);fetchers=Fetchers({1:quote('₦3M')})
    assert Runner(state,args(),backend.factory,fetchers.factory).run()==0
    assert Runner(state,args(),backend.factory,fetchers.factory).run()==0
    assert fetchers.calls==[1]


def test_stale_preview_is_deferred_for_a_fresh_visit(tmp_path):
    state,backend=make_state(tmp_path,[old_row(1)])
    stale=quote();stale['pricing_observed_at']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    job=state.claim('propertypro',False);state.start_visit(1);state.save_quote(1,backend.rows[1],stale,None,str(uuid4()))
    state.begin_run('old',{});state.finish(job,'old','previewed','saved')
    fetchers=Fetchers();assert Runner(state,args(apply=True),backend.factory,fetchers.factory).run()==0
    assert fetchers.calls==[] and backend.writes==0
    with state.connect() as db:
        row=db.execute('SELECT status,quote_json,run_id FROM jobs').fetchone()
        assert tuple(row)==('retryable',None,None)


def test_blocked_portal_pauses_while_other_portal_continues(tmp_path):
    rows=[old_row(n) for n in range(1,11)]+[old_row(100,'privateproperty')]
    state,backend=make_state(tmp_path,rows);calls=[]
    def factory(source,budget,state):
        class Fetcher:
            def observe(self,row):
                budget.take_http();state.start_visit(row['id']);calls.append(row['id'])
                if source=='propertypro':return dict(quote=None,purpose=None,retryable=True,systemic=True,reason='http_403')
                return dict(quote=quote(),purpose=None,retryable=False,systemic=False,reason='observed')
            def close(self):pass
        return Fetcher()
    runner=Runner(state,args(sources=['propertypro','privateproperty']),backend.factory,factory)
    assert runner.run()==0
    assert len([n for n in calls if n<100])==5 and 100 in calls
    assert state.portal('propertypro')['cooldown_until']>0
    before=list(calls)
    assert Runner(state,args(sources=['propertypro']),backend.factory,factory).run()==0
    assert calls==before


def test_exact_attempt_import_skips_ids_but_counter_only_reports_are_rejected(tmp_path):
    state=RecoveryState(tmp_path/'state','test')
    report=tmp_path/'propertypro-preview.json'
    report.write_text(json.dumps({'source':'propertypro','observations':[{'id':1,'outcome':'observed'},{'id':3,'outcome':'unavailable'}]}))
    assert import_report(state,report)==2
    state.seed([(n,'propertypro','FOR_RENT') for n in (1,2,3)])
    assert state.claim('propertypro',False)['listing_id']==2
    counters=tmp_path/'counters.json';counters.write_text(json.dumps({'last_completed_id':500,'counts':{'scanned':100}}))
    with pytest.raises(ValueError,match='exact listing IDs'):import_report(state,counters)


def test_signal_stop_preserves_pending_work_without_a_request(tmp_path):
    state,backend=make_state(tmp_path,[old_row(1)]);fetchers=Fetchers()
    runner=Runner(state,args(apply=True),backend.factory,fetchers.factory);runner.stopped.set()
    assert runner.run()==130 and not fetchers.calls and backend.writes==0


def test_status_can_be_read_while_runner_lock_is_held(tmp_path,capsys):
    from scraper.recovery_runner import main
    from scraper.traffic_guard import single_recovery_runner
    state=RecoveryState(tmp_path,'test')
    with single_recovery_runner():
        assert main(['status','--state-dir',str(tmp_path)])==0
    assert 'queue' in capsys.readouterr().out


def test_real_http_send_budget_counts_redirects_and_blocks_external_hosts(tmp_path,monkeypatch):
    import requests
    from requests.adapters import BaseAdapter
    from scraper.recovery_runner import PageFetcher,BudgetStop,RedirectOutsidePortal
    class Adapter(BaseAdapter):
        calls=[]
        def send(self,request,**kwargs):
            self.calls.append(request.url)
            response=requests.Response();response.request=request;response.url=request.url
            response.status_code=302;response.headers['Location']='https://propertypro.ng/second'
            response._content=b''
            return response
        def close(self):pass
    state=RecoveryState(tmp_path,'test');state.seed([(1,'propertypro','FOR_RENT')]);state.begin_run('test',{})
    budget=Budget(state,'test',10,1,30,threading.Event());fetcher=PageFetcher('propertypro',budget,state)
    adapter=Adapter();fetcher.parser.session.mount('https://',adapter);fetcher.context={'id':1}
    with pytest.raises(BudgetStop):fetcher.parser.session.get('https://propertypro.ng/first')
    assert len(adapter.calls)==1 and budget.http==1
    with pytest.raises(RedirectOutsidePortal):fetcher.parser.session.get('https://unrelated.example/')
    assert budget.http==1
    with state.connect() as db:assert db.execute('SELECT visits FROM jobs').fetchone()[0]==1
    fetcher.close()
