import json
from pathlib import Path
import subprocess
import sys

import pytest

from course_tutor.antigravity_app_usage import capture_app_usage, configure_app_usage
from course_tutor.errors import ValidationError
from course_tutor.host_usage import configure_usage
from course_tutor.usage import summarize_usage

SESSION = '11111111-1111-4111-8111-111111111111'


def fixture(tmp_path):
    home = tmp_path/'app'
    path = home/'brain'/SESSION/'.system_generated/logs/transcript.jsonl'
    path.parent.mkdir(parents=True)
    payload = {'workspacePaths': [str(tmp_path)], 'conversationId': SESSION,
               'transcriptPath': str(path), 'modelName': 'not-history-attribution'}
    return home, path, payload


def row(idx=1, **kw):
    return dict(step_index=idx, source='MODEL', type='PLANNER_RESPONSE', status='DONE',
                created_at='2026-10-19T10:00:00Z', input_tokens=100,
                output_tokens=20, cache_read_tokens=0, content='PRIVATE TEXT', **kw)


def write(path, rows):
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))


def test_dedup_privacy_cache_and_snapshot_replay(tmp_path):
    home, path, payload = fixture(tmp_path)
    write(path, [row(), {**row(), 'output_tokens': 25}, row(2)])
    log = tmp_path/'usage.jsonl'
    saved = capture_app_usage(log, tmp_path, payload, app_home=home)
    assert saved['event']['input_tokens'] == 200
    assert saved['event']['output_tokens'] == 45
    assert 'PRIVATE' not in log.read_text()
    assert saved['event']['models'] == []
    assert capture_app_usage(log, tmp_path, payload, app_home=home)['replayed']
    write(path, [row(), {**row(2), 'cache_read_tokens': 300}])
    event = capture_app_usage(log, tmp_path, payload, app_home=home)['event']
    assert event['input_tokens'] is event['cached_input_tokens'] is None
    assert event['reported_usage']['input_tokens'] == 200
    assert event['reported_usage']['cache_read_tokens'] == 300
    assert summarize_usage(log)['events'] == 2


def test_project_and_surface_scope_before_read(tmp_path):
    home, path, payload = fixture(tmp_path)
    path.write_text('PRIVATE invalid JSON\n')
    for altered in ({**payload, 'workspacePaths': [str(tmp_path/'other')]},
                    {**payload, 'workspacePaths': [str(tmp_path), str(tmp_path/'other')]},
                    {**payload, 'transcriptPath': str(tmp_path/'cli/transcript.jsonl')}):
        assert capture_app_usage(tmp_path/'usage', tmp_path, altered, app_home=home) is None
    assert not (tmp_path/'usage').exists()


@pytest.mark.parametrize('change', [{'input_tokens': True}, {'output_tokens': -1},
                                  {'step_index': None}, {'created_at': 'bad'},
                                  {'input_tokens': None}])
def test_invalid_counters_fail_without_save(tmp_path, change):
    home, path, payload = fixture(tmp_path)
    write(path, [{**row(), **change}])
    with pytest.raises(ValidationError):
        capture_app_usage(tmp_path/'usage', tmp_path, payload, app_home=home)
    assert not (tmp_path/'usage').exists()


def test_partial_tail_missing_cache_and_no_counters(tmp_path):
    home, path, payload = fixture(tmp_path)
    write(path, [{'source': 'USER_EXPLICIT', 'content': 'PRIVATE'}])
    assert capture_app_usage(tmp_path/'usage', tmp_path, payload, app_home=home) is None
    r = row()
    del r['cache_read_tokens']
    write(path, [r])
    with path.open('a') as f:
        f.write('{"incomplete":')
    event = capture_app_usage(tmp_path/'usage', tmp_path, payload, app_home=home)['event']
    assert event['input_tokens'] is None
    assert event['output_tokens'] == 20


def test_setup_preserves_existing_hooks_and_is_idempotent(tmp_path):
    path = tmp_path/'.agents/hooks.json'
    path.parent.mkdir()
    original = '{"existing": {"enabled": false}}\n'
    path.write_text(original)
    result = configure_usage(tmp_path, tmp_path/'usage', hosts=['antigravity-app'])['configured'][0]
    assert Path(result['backup_path']).read_text() == original
    data = json.loads(path.read_text())
    assert data['existing'] == {'enabled': False}
    assert set(data['lumen-desktop-usage']) == {'enabled', 'PostInvocation', 'Stop'}
    assert not configure_app_usage(tmp_path, tmp_path/'usage')['changed']
    data['lumen-desktop-usage']['enabled'] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        configure_app_usage(tmp_path, tmp_path/'usage')


def test_hook_process_outputs_only_empty_object_on_excluded_surface(tmp_path):
    _, _, payload = fixture(tmp_path)
    payload['transcriptPath'] = str(tmp_path/'cli/transcript.jsonl')
    proc = subprocess.run([sys.executable, '-m', 'course_tutor.antigravity_app_usage',
                           '--project', str(tmp_path), '--log', str(tmp_path/'usage')],
                          input=json.dumps(payload), text=True, capture_output=True)
    assert proc.returncode == 0
    assert proc.stdout == '{}\n'
    assert proc.stderr == ''


def test_native_metadata_collection_scopes_before_transcript_read(tmp_path):
    import sqlite3
    from course_tutor.usage_collector import collect_usage
    home, path, _ = fixture(tmp_path)
    write(path, [row()])
    other = home/'brain'/'22222222-2222-4222-8222-222222222222'/'.system_generated/logs/transcript.jsonl'
    other.parent.mkdir(parents=True)
    other.write_text('PRIVATE malformed unrelated transcript\n')
    with sqlite3.connect(home/'conversation_summaries.db') as con:
        con.execute('CREATE TABLE conversation_summaries (conversation_id TEXT, workspace_uris TEXT, app_data_dir TEXT)')
        con.executemany('INSERT INTO conversation_summaries VALUES (?,?,?)', [
            (SESSION, json.dumps([tmp_path.as_uri()+'/']), 'antigravity'),
            (other.parts[-4], json.dumps([(tmp_path/'other').as_uri()]), 'antigravity'),
            (SESSION, json.dumps([tmp_path.as_uri()]), 'antigravity-cli')])
    args = dict(hosts=['antigravity-app'], antigravity_app_home=home)
    first = collect_usage(tmp_path/'usage', tmp_path, **args)
    assert first['files_scanned'] == first['snapshots_appended'] == 1
    assert first['errors'] == []
    assert collect_usage(tmp_path/'usage', tmp_path, **args)['snapshots_replayed'] == 1


def test_missing_or_incompatible_native_database(tmp_path):
    import sqlite3
    from course_tutor.antigravity_app_usage import collect_app_usage
    home = tmp_path/'app'
    assert collect_app_usage(tmp_path/'usage', tmp_path, app_home=home)['files_scanned'] == 0
    home.mkdir()
    sqlite3.connect(home/'conversation_summaries.db').close()
    assert collect_app_usage(tmp_path/'usage', tmp_path, app_home=home)['errors']
    assert not (tmp_path/'usage').exists()
