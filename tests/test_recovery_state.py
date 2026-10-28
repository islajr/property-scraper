import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from scraper.recovery_state import RecoveryState


def test_queue_claims_once_across_workers_and_persists(tmp_path):
    state=RecoveryState(tmp_path,'test-target');state.seed([(n,'propertypro','FOR_RENT') for n in range(1,31)])
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=list(pool.map(lambda _:state.claim('propertypro',False),range(30)))
    assert len({j['listing_id'] for j in jobs})==30
    assert RecoveryState(tmp_path,'test-target').claim('propertypro',False) is None
    with pytest.raises(ValueError):RecoveryState(tmp_path,'different-target')


def test_preview_is_applied_without_another_visit_and_held_is_not_retried(tmp_path):
    state=RecoveryState(tmp_path,'test');state.seed([(1,'propertypro','FOR_RENT'),(2,'propertypro','FOR_RENT')])
    state.begin_run('r',{})
    job=state.claim('propertypro',False);state.start_visit(1)
    state.save_quote(1,{'id':1},{'price_period':'YEAR'},None,'audit-id')
    state.finish(job,'r','previewed','explicit_primary_quote')
    other=state.claim('propertypro',False);assert other['listing_id']==2
    state.finish(other,'r','held','period_unknown')
    assert state.claim('propertypro',False) is None
    saved=state.claim('propertypro',True)
    assert json.loads(saved['quote_json'])['price_period']=='YEAR' and saved['visits']==1


def test_crash_recovery_distinguishes_saved_quote_and_interrupted_network(tmp_path):
    state=RecoveryState(tmp_path,'test');state.seed([(n,'propertypro','FOR_RENT') for n in (1,2,3)])
    state.claim('propertypro',False);state.start_visit(1)
    state.claim('propertypro',False);state.save_quote(2,{'id':2},{'price_period':'MONTH'},None,'audit')
    state.claim('propertypro',False)
    state.recover_interrupted(now=100)
    with state.connect() as db:
        results={r['listing_id']:dict(r) for r in db.execute('SELECT * FROM jobs')}
    assert results[1]['status']=='retryable' and results[1]['retry_at']==400
    assert results[2]['status']=='ready' and results[2]['run_id']=='audit'
    assert results[3]['status']=='pending'


def test_prior_attempts_and_operator_retry_are_explicit(tmp_path):
    state=RecoveryState(tmp_path,'test');state.import_attempt(7,'privateproperty','pilot_missing_unit')
    state.seed([(7,'privateproperty','FOR_RENT')])
    assert state.claim('privateproperty',True) is None
    state.reset([7]);assert state.claim('privateproperty',True)['listing_id']==7
