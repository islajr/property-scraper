import json
import pytest
from scripts.preview_property_classification import main, proposal


def test_connection_failures_never_print_credentials(monkeypatch, capsys, tmp_path):
    import psycopg2
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:secret-token@db.invalid/database')
    def fail(*args, **kwargs):
        raise psycopg2.OperationalError('connection failed: secret-token')
    monkeypatch.setattr(psycopg2, 'connect', fail)
    assert main(['--output', str(tmp_path/'preview.jsonl')]) == 1
    captured = capsys.readouterr()
    assert 'secret-token' not in captured.err + captured.out
    assert 'connection details suppressed' in captured.err


def test_preview_has_no_apply_mode(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(['--output', str(tmp_path/'preview.jsonl'), '--apply'])
    assert error.value.code == 2


def test_preview_uses_evidence_not_previous_classification():
    for previous in ('DETACHED_DUPLEX', 'RANDOM_TITLE_FRAGMENT', None):
        result = proposal(dict(property_type=previous, title='Duplex for sale', description=None))
        assert result['property_type'] == 'DUPLEX'
        assert result['property_type_raw'] is None


@pytest.mark.parametrize('option,value', [('--limit','0'), ('--batch-size','-1'), ('--after-id','-1')])
def test_invalid_bounds_fail_before_connecting(option, value, tmp_path):
    with pytest.raises(SystemExit) as error:
        main(['--output', str(tmp_path/'preview.jsonl'), option, value])
    assert error.value.code == 2
