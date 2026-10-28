"""Linux same-host traffic coordination. Health checks get priority over recovery."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


class TrafficBusy(Exception):
    pass


def lock_directory():
    configured = os.environ.get('PROPERTY_SCRAPER_LOCK_DIR')
    base = Path(configured) if configured else Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'property-scraper/locks'
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return base


def _open(name):
    return os.fdopen(os.open(lock_directory()/name, os.O_CREAT | os.O_RDWR, 0o600), 'a+')


@contextmanager
def health_traffic():
    # Announce health's intent first. Recovery only holds intent while acquiring
    # its traffic slot, so a waiting health check prevents fresh recovery visits.
    with _open('health-intent.lock') as intent, _open('portal-traffic.lock') as traffic:
        fcntl.flock(intent, fcntl.LOCK_EX)
        fcntl.flock(traffic, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(traffic, fcntl.LOCK_UN)
            fcntl.flock(intent, fcntl.LOCK_UN)


@contextmanager
def recovery_traffic():
    with _open('health-intent.lock') as intent, _open('portal-traffic.lock') as traffic:
        try:
            fcntl.flock(intent, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(traffic, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TrafficBusy('Health check is running or waiting') from exc
        finally:
            fcntl.flock(intent, fcntl.LOCK_UN)
        try:
            yield
        finally:
            fcntl.flock(traffic, fcntl.LOCK_UN)


@contextmanager
def single_recovery_runner():
    with _open('recovery-runner.lock') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TrafficBusy('A recovery runner is already using this host') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
