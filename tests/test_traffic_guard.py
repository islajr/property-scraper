import fcntl
import pytest
from scraper.traffic_guard import (health_traffic,recovery_traffic,single_recovery_runner,
                                   TrafficBusy,lock_directory)


def test_health_excludes_recovery_but_recovery_workers_can_share():
    with recovery_traffic(),recovery_traffic():
        pass
    with health_traffic():
        with pytest.raises(TrafficBusy):
            with recovery_traffic():pass
    with recovery_traffic():pass


def test_health_intent_blocks_new_recovery_before_existing_traffic_finishes():
    with recovery_traffic():
        with open(lock_directory()/'health-intent.lock','a+') as intent:
            fcntl.flock(intent,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with pytest.raises(TrafficBusy):
                with recovery_traffic():pass


def test_duplicate_runner_is_rejected_and_lock_releases_on_exception():
    with pytest.raises(RuntimeError):
        with single_recovery_runner():
            with pytest.raises(TrafficBusy):
                with single_recovery_runner():pass
            raise RuntimeError('interrupted')
    with single_recovery_runner():pass
