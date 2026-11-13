from dataclasses import asdict
import hashlib
import json
from uuid import uuid4
import pytest
from scraper.classification_artifact import ReviewError, reviewed_preview, classifier_fingerprint
from scraper.property_types import classify, metadata, VERSION


def artifact_file(tmp_path, rows=None):
    rows = rows or [dict(id=1, source='propertypro', listing_status='ACTIVE', row_version='100',
                         previous=metadata({'property_type': 'OLD_LABEL'}),
                         proposed=asdict(classify(title='Mini flat')))]
    path = tmp_path/(uuid4().hex + '.jsonl')
    path.write_text(''.join(json.dumps(row, default=str) + '\n' for row in rows))
    summary = dict(read_only=True, rule_version=VERSION, database_fingerprint='test-target',
                   classifier_sha256=classifier_fingerprint(), counts=dict(scanned=len(rows)),
                   report_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    path.with_suffix('.summary.json').write_text(json.dumps(summary))
    return path


def update_summary(path, **updates):
    summary = json.loads(path.with_suffix('.summary.json').read_text())
    summary.update(updates)
    path.with_suffix('.summary.json').write_text(json.dumps(summary))


def test_artifact_is_frozen_after_full_validation(tmp_path):
    path = artifact_file(tmp_path)
    with reviewed_preview(path) as artifact:
        path.write_text('changed after validation')
        assert next(artifact.records())['proposed']['property_type'] == 'MINI_FLAT'
        assert next(artifact.records())['id'] == 1


@pytest.mark.parametrize('updates', [
    {'report_sha256':'wrong'}, {'rule_version':'other-version'},
    {'classifier_sha256':'changed-rules'}, {'read_only':False}, {'counts':{'scanned':2}},
])
def test_invalid_manifest_is_rejected(tmp_path, updates):
    path = artifact_file(tmp_path)
    update_summary(path, **updates)
    with pytest.raises(ReviewError), reviewed_preview(path):
        pass


@pytest.mark.parametrize('change', ['duplicate_id', 'bad_state', 'unknown_type', 'missing_fields', 'naive_time'])
def test_every_row_is_preflighted_even_outside_a_small_canary(tmp_path, change):
    first = json.loads(artifact_file(tmp_path).read_text())
    second = {**first, 'id':2, 'proposed':{**first['proposed']}}
    if change == 'duplicate_id': second['id'] = 1
    if change == 'bad_state': second['proposed']['property_type_status'] = 'LEGACY_UNREVIEWED'
    if change == 'unknown_type': second['proposed']['property_type'] = 'UNKNOWN_CODE'
    if change == 'missing_fields': second['previous'] = {}
    if change == 'naive_time': second['proposed']['property_type_classified_at'] = '2026-11-13T12:00:00'
    path = artifact_file(tmp_path, [first,second])
    with pytest.raises(ReviewError), reviewed_preview(path):
        pass


def test_legacy_preview_without_new_source_hash_is_readable(tmp_path):
    path = artifact_file(tmp_path)
    summary = json.loads(path.with_suffix('.summary.json').read_text())
    summary.pop('classifier_sha256')
    path.with_suffix('.summary.json').write_text(json.dumps(summary))
    with reviewed_preview(path) as artifact:
        assert len(list(artifact.records())) == 1


def test_malformed_report_fails_before_a_database_connection(tmp_path, monkeypatch):
    import psycopg2
    from scripts.backfill_property_classification import main
    path = artifact_file(tmp_path)
    path.write_text('invalid JSON')
    def unexpected(*args, **kwargs): raise AssertionError('must preflight before connecting')
    monkeypatch.setattr(psycopg2,'connect',unexpected)
    assert main(['apply','--report',str(path),'--run-id',str(uuid4()),'--apply']) == 1


def test_connection_error_details_are_suppressed(tmp_path, monkeypatch, capsys):
    import psycopg2
    from scripts.backfill_property_classification import main
    path = artifact_file(tmp_path)
    monkeypatch.setenv('DATABASE_URL','postgresql://user:private-password@invalid/db')
    def fail(*args, **kwargs): raise psycopg2.OperationalError('private-password in error')
    monkeypatch.setattr(psycopg2,'connect',fail)
    assert main(['apply','--report',str(path),'--run-id',str(uuid4())]) == 1
    captured = capsys.readouterr()
    assert 'private-password' not in captured.out + captured.err


@pytest.mark.parametrize('extra', [['--max-records','0'],['--after-id','-1'],['--through-id','0'],['--ids','0,1'],['--ids','x'],['--type','INVENTED']])
def test_invalid_cli_bounds_and_selections_fail_before_connecting(tmp_path, extra):
    from scripts.backfill_property_classification import main
    with pytest.raises(SystemExit) as result:
        main(['apply','--report',str(tmp_path/'none.jsonl'),'--run-id',str(uuid4()),*extra])
    assert result.value.code == 2


@pytest.mark.parametrize('summary_output', [False, True])
def test_output_cannot_clobber_the_reviewed_artifact(tmp_path, summary_output):
    from scripts.backfill_property_classification import main
    path=artifact_file(tmp_path)
    output=path.with_suffix('.summary.json') if summary_output else path
    before=output.read_bytes()
    with pytest.raises(SystemExit) as result:
        main(['apply','--report',str(path),'--run-id',str(uuid4()),'--output',str(output),'--apply'])
    assert result.value.code == 2 and output.read_bytes()==before
