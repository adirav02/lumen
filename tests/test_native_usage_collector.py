# TL;DR: Verify deterministic task discovery, native identity accounting and real regression.
# Status: active; date: 2026-10-19.
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect_native_usage import collect, table
from _native_usage import discover

START, END = '2026-10-19T10:00:00Z', '2026-10-19T11:00:00Z'


def log(home, repo, key, *, parent=None, role='dev_worker', rows=None, name=None):
    path = home / 'sessions' / (name or key + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(id=key, cwd=str(repo), timestamp=START, source='exec')
    if parent:
        meta['source'] = {'subagent': {'thread_spawn': dict(parent_thread_id=parent, agent_role=role)}}
    data = [dict(type='session_meta', payload=meta)] + (rows if rows is not None else [usage(key)])
    path.write_text(''.join(json.dumps(r)+'\n' for r in data))
    return path


def usage(key, **values):
    return dict(type='token_usage_record', timestamp=START, payload=dict(
        thread_id=key, response_id='response-'+key,
        usage=dict(input_tokens=100, cached_input_tokens=80, output_tokens=20,
                   reasoning_output_tokens=5, **values)))


def test_window_discovers_root_recursive_children_and_deduplicates(tmp_path):
    repo, home = tmp_path / 'repo', tmp_path / 'codex'
    tool = dict(type='response_item', timestamp=START, payload=dict(type='function_call', call_id='tool-1'))
    log(home, repo, 'root', rows=[usage('root'), usage('root'), tool, tool])
    log(home, repo, 'child', parent='root')
    log(home, repo, 'grandchild', parent='child', role='dev_reviewer')
    log(home, tmp_path / 'other', 'unrelated')
    log(home, repo, 'child', parent='root', name='copy.jsonl')
    old = usage('inactive')
    old['timestamp'] = '2026-10-18T10:00:00Z'
    log(home, repo, 'inactive', parent='root', rows=[old])
    # A future child must not be included in this task's window.
    future = log(home, repo, 'future', parent='root')
    future.write_text(future.read_text().replace(START, '2026-10-20T10:00:00Z'))
    report = collect(repo, since=START, until=END, codex_home=home)
    assert report['root_thread_id'] == 'root'
    assert report['total']['input_tokens'] == 300
    assert report['total']['fresh_input_tokens'] == 60
    assert report['total']['model_calls'] == 3
    assert report['total']['tool_calls'] == 1
    assert [r['role'] for r in report['threads']] == ['manager', 'dev_worker', 'dev_reviewer']
    assert 'Root counters exclude children' in report['note']
    assert '| TOTAL |' in table(report)
    task = tmp_path / 'task'
    task.mkdir()
    (task/'status.json').write_text(json.dumps(dict(started_utc=START, ended_utc=END)))
    assert collect(repo, task=task, codex_home=home) == report


def test_ambiguous_roots_and_missing_records_fail_explicitly(tmp_path):
    log(tmp_path, tmp_path, 'one')
    log(tmp_path, tmp_path, 'two')
    with pytest.raises(ValueError, match='found 2'):
        collect(tmp_path, since=START, until=END, codex_home=tmp_path)
    assert collect(tmp_path, root_thread='one', codex_home=tmp_path)['total']['model_calls'] == 1
    log(tmp_path, tmp_path, 'empty', rows=[])
    with pytest.raises(ValueError, match='no native per-response usage'):
        collect(tmp_path, root_thread='empty', codex_home=tmp_path)
    with pytest.raises(ValueError, match='Root session log missing'):
        collect(tmp_path, root_thread='absent', codex_home=tmp_path)


@pytest.mark.parametrize('timestamp', ['2026-10-19T10:00:00', '2026-10-19T12:00:00+02:00'])
def test_requires_utc(tmp_path, timestamp):
    with pytest.raises(ValueError, match='UTC timestamp'):
        collect(tmp_path, since=timestamp, until=END, codex_home=tmp_path)


def test_counter_conflicts_and_corruption_are_errors(tmp_path):
    row = usage('root')
    other = usage('root')
    other['payload']['usage']['input_tokens'] = 101
    path = log(tmp_path, tmp_path, 'root', rows=[row, other])
    with pytest.raises(ValueError, match='conflicting usage'):
        collect(tmp_path, root_thread='root', codex_home=tmp_path)
    path.write_text(path.read_text() + '{"unfinished":')
    with pytest.raises(ValueError, match='conflicting usage'):
        collect(tmp_path, root_thread='root', codex_home=tmp_path)
    log(tmp_path, tmp_path, 'root', rows=[row])
    with path.open('a') as stream:
        stream.write('{')
    with pytest.raises(ValueError, match='incomplete log line'):
        collect(tmp_path, root_thread='root', codex_home=tmp_path)
    log(tmp_path, tmp_path, 'root', rows=[row])
    with path.open('a') as stream:
        stream.write('broken\n')
    with pytest.raises(ValueError, match='invalid JSON'):
        collect(tmp_path, root_thread='root', codex_home=tmp_path)


def test_archived_validate_task_status_native_regression():
    home = Path.home() / '.codex'
    key = '01a153ca-2c94-70e0-adee-3dc92b1d73cf'
    sessions = discover(home)
    if key not in sessions:
        pytest.skip('Archived validate-task-status native logs unavailable; manual check required')
    result = collect(sessions[key]['meta']['cwd'], root_thread=key, codex_home=home,
                     since='2026-10-19T10:57:56.397Z', until='2026-10-19T11:04:22.300Z')
    total = result['total']
    assert tuple(total[k] for k in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'model_calls')) == (
        2878590, 2650624, 19343, 77)
