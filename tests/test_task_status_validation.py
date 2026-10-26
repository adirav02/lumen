# TL;DR: Check task status validation and unchanged compact CLI output.
# Status: active; date: 2026-10-19.
"""Exercise the status CLI against isolated task directories."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'development/scripts/task_status.py'
VALID = {
    'task_id': '20261019-example', 'title': 'Example', 'state': 'planned',
    'owner_role': 'manager', 'host': None, 'model': None,
    'updated': '2026-10-19T00:00:00+00:00', 'based_on_commit': 'unknown',
    'next_step': 'Review changes', 'mode': 'solo', 'reason': 'Routine task.',
}


def write_status(root, data, folder='20261019-example'):
    path = root / 'development/work' / folder / 'status.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def run(root):
    return subprocess.run([sys.executable, str(SCRIPT), '--root', str(root)],
                          capture_output=True, text=True)


def assert_invalid(root, path, reason):
    result = run(root)
    assert result.returncode == 1
    assert result.stdout == ''
    assert str(path) in result.stderr
    assert reason in result.stderr
    assert 'Traceback' not in result.stderr
    assert len(result.stderr.splitlines()) == 1
    assert len(result.stderr) < len(str(path)) + 250


@pytest.mark.parametrize('state', ['planned', 'in_progress', 'review', 'done', 'blocked'])
def test_valid_states(tmp_path, state):
    write_status(tmp_path, {**VALID, 'state': state})
    result = run(tmp_path)
    assert result.returncode == 0
    assert result.stderr == ''
    assert result.stdout == (
        'TASK | STATE | OWNER | HOST/MODEL | NEXT\n'
        f'20261019-example | {state} | manager | -/- | Review changes\n')


def test_compact_sorting_whitespace_and_only_status_reads(tmp_path):
    later = write_status(tmp_path, {**VALID, 'task_id': ' second\n task ',
                                   'host': ' test\n host ', 'model': ' model ',
                                   'next_step': ' review\t changes '}, 'z-task')
    write_status(tmp_path, {**VALID, 'extra': 'allowed'}, 'a-task')
    for name in ('brief.md', 'plan.md', 'findings.md'):
        document = later.parent / name
        document.write_bytes(b'\xff\xfe')
        document.chmod(0)
    ignored = write_status(tmp_path, None, '_ignored')
    ignored.write_text('invalid JSON')
    result = run(tmp_path)
    assert result.returncode == 0
    assert result.stderr == ''
    assert result.stdout == (
        'TASK | STATE | OWNER | HOST/MODEL | NEXT\n'
        '20261019-example | planned | manager | -/- | Review changes\n'
        'second task | planned | manager | test host / model | review changes\n')


@pytest.mark.parametrize('field', list(VALID))
def test_every_required_field(tmp_path, field):
    data = {key: value for key, value in VALID.items() if key != field}
    path = write_status(tmp_path, data)
    assert_invalid(tmp_path, path, 'missing required fields: ' + field)


@pytest.mark.parametrize('raw', ['{', '{"state":', 'not JSON'])
def test_invalid_json(tmp_path, raw):
    path = write_status(tmp_path, VALID)
    path.write_text(raw)
    assert_invalid(tmp_path, path, 'invalid JSON')


@pytest.mark.parametrize('data', [None, [], ['planned'], 'planned', 1, True])
def test_non_object_roots(tmp_path, data):
    path = write_status(tmp_path, data)
    assert_invalid(tmp_path, path, 'expected a JSON object')


@pytest.mark.parametrize('state', ['unknown', 'PLANNED', '', None, [], {}, 1, True])
def test_unknown_or_non_string_states(tmp_path, state):
    path = write_status(tmp_path, {**VALID, 'state': state})
    assert_invalid(tmp_path, path, 'unknown state')


@pytest.mark.parametrize('mode', ['solo', 'delegated'])
def test_valid_modes(tmp_path, mode):
    write_status(tmp_path, {**VALID, 'mode': mode})
    assert run(tmp_path).returncode == 0


@pytest.mark.parametrize('mode', ['', 'other', None, []])
def test_invalid_modes(tmp_path, mode):
    path = write_status(tmp_path, {**VALID, 'mode': mode})
    assert_invalid(tmp_path, path, 'unknown mode')


@pytest.mark.parametrize('reason', ['', ' ', 'two\nlines', None, []])
def test_invalid_reasons(tmp_path, reason):
    path = write_status(tmp_path, {**VALID, 'reason': reason})
    assert_invalid(tmp_path, path, 'reason must be a nonempty one-line string')
