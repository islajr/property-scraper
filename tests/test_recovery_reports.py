import csv
import json
import sqlite3

import pytest

from scraper.recovery_state import RecoveryState
from scripts.export_recovery_reviews import export_reviews


def test_reports_refresh_holds_escape_portal_text_and_leave_queue_unchanged(tmp_path):
    state = RecoveryState(tmp_path, 'test')
    state.seed([(1, 'propertypro', 'FOR_RENT')])
    state.begin_run('test', {})
    job = state.claim('propertypro', False)
    state.finish(job, 'test', 'held', 'period_unknown', observation=(
        {'url': 'https://example.test/property?x="', 'price_type': 'FOR_RENT'},
        {'raw_price_text': '=1+1<script>alert(1)</script>', 'price_type': 'FOR_RENT'}, None))
    assert export_reviews(tmp_path) == 1
    page = (tmp_path/'manual-review.html').read_text()
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;' in page and 'Open property' in page
    with (tmp_path/'manual-review.csv').open(newline='') as file:
        row = next(csv.DictReader(file))
        assert row['displayed_price'].startswith("'=1+1")
    data = json.loads((tmp_path/'manual-review.json').read_text())
    assert data['held_count'] == 1 and data['listings'][0]['listing_id'] == 1
    with state.connect() as db:
        assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'held'
    state.reset([1])
    assert export_reviews(tmp_path) == 0
    assert json.loads((tmp_path/'manual-review.json').read_text())['listings'] == []
    assert 'Open property' not in (tmp_path/'manual-review.html').read_text()
    assert (tmp_path/'manual-review.html').stat().st_mode & 0o777 == 0o600


def test_export_does_not_create_a_missing_queue(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        export_reviews(tmp_path)
    assert not (tmp_path/'queue.sqlite3').exists()
