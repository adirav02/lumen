"""Configured external logs expose measured, partial and unavailable scopes."""
import json
import pytest
from course_tutor.usage_collector import collect_usage
from course_tutor.errors import ValidationError
from test_usage_collector import fixture


def test_measured_external_roots_and_replay(tmp_path):
    path, project, home, log=fixture(tmp_path)
    r=collect_usage(log,project,hosts=['codex'],log_locations=[str(home/'sessions')])
    assert r['usage_state']=='measured' and r['sessions_with_usage']==1
    assert 'not per-task' in r['scope_limit']
    again=collect_usage(log,project,hosts=['codex'],log_locations=[str(path),str(home)])
    assert again['snapshots_replayed']==1 and again['snapshots_appended']==0


def test_partial_scope_and_env_location(tmp_path,monkeypatch):
    path,project,home,log=fixture(tmp_path)
    with path.open('a') as f:
        f.write('{"unfinished":')
    monkeypatch.setenv('LUMEN_USAGE_LOG_LOCATIONS',str(home))
    r=collect_usage(log,project,hosts=['codex'])
    assert r['usage_state']=='partial' and r['pending_tails']==1
    assert r['scope_limit'] and r['usage'] is not None


def test_unavailable_is_null_and_bad_config_is_explicit(tmp_path):
    home=tmp_path/'empty';home.mkdir()
    r=collect_usage(tmp_path/'usage.jsonl',tmp_path,hosts=['codex'],log_locations=[str(home)])
    assert r['usage_state']=='unavailable' and r['usage'] is None
    assert r['unavailable_reason']
    assert 'input_tokens' not in json.dumps(r)
    with pytest.raises(ValidationError,match='Configured usage log location is unreadable'):
        collect_usage(tmp_path/'usage.jsonl',tmp_path,log_locations=[str(tmp_path/'absent')])
