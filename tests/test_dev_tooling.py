# TL;DR: Verify dev scaffolding checks, task lifecycle and documentation guards in isolation.
# Status: active; date: 2026-10-19.
"""Only stdlib subprocess/filesystem fixtures; never import application code."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(root, script, *args, ok=True):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script),
                             '--root', str(root), *args], capture_output=True, text=True)
    if ok:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout + result.stderr
    return result


@pytest.fixture
def repo(tmp_path):
    for name in ('agents', 'work/_template'):
        shutil.copytree(ROOT / name, tmp_path / name)
    (tmp_path / 'AGENTS.md').write_text('TL;DR: Existing loader.\nStatus: active; date: 2026-10-19.\n')
    (tmp_path / 'docs').mkdir()
    shutil.copyfile(ROOT / 'docs/task-log.md', tmp_path / 'docs/task-log.md')
    return tmp_path


def test_sync_check_idempotence_preservation_and_reasoning(repo):
    before = (repo / 'AGENTS.md').read_text()
    run(repo, 'sync_agents.py', '--check', ok=False)
    assert not (repo / '.codex').exists()
    assert (repo / 'AGENTS.md').read_text() == before
    legacy = repo / '.claude/agents/course-existing.md'
    legacy.parent.mkdir(parents=True)
    legacy.write_text('Legacy profile, keep verbatim.\n')
    run(repo, 'sync_agents.py')
    assert (repo / 'AGENTS.md').read_text().startswith(before)
    snapshot = {p: p.read_bytes() for p in repo.rglob('*') if p.is_file()}
    run(repo, 'sync_agents.py')
    run(repo, 'sync_agents.py', '--check')
    assert snapshot == {p: p.read_bytes() for p in repo.rglob('*') if p.is_file()}
    assert legacy.read_text() == 'Legacy profile, keep verbatim.\n'
    for role, effort in {'dev_explorer': 'low', 'dev_worker': 'low', 'dev_planner': 'high',
                         'dev_reviewer': 'medium'}.items():
        native = (repo / f'.codex/agents/{role}.toml').read_text()
        assert f'name = "{role}"' in native
        assert f'model_reasoning_effort = "{effort}"' in native
        assert f'name: {role}\n' in (repo / f'.claude/agents/{role}.md').read_text()
    assert 'gpt-5.6-terra' in (repo / '.codex/agents/dev_explorer.toml').read_text()
    assert not (repo / '.codex/agents/manager.toml').exists()
    changed = repo / '.claude/agents/dev_worker.md'
    changed.write_text(changed.read_text() + '\nStale\n')
    run(repo, 'sync_agents.py', '--check', ok=False)
    assert changed.read_text().endswith('Stale\n')


def test_sync_refuses_unmarked_native_collision(repo):
    path = repo / '.codex/agents/dev_explorer.toml'
    path.parent.mkdir(parents=True)
    path.write_text('name = "hand-maintained"\n')
    run(repo, 'sync_agents.py', ok=False)
    assert path.read_text() == 'name = "hand-maintained"\n'


@pytest.mark.parametrize('folder,suffix', [('.codex/agents', '.toml'), ('.claude/agents', '.md')])
@pytest.mark.parametrize('generated', [True, False])
def test_sync_retires_only_its_own_old_role_files(repo, folder, suffix, generated):
    run(repo, 'sync_agents.py')
    old = repo / folder / ('explorer' + suffix)
    new = repo / folder / ('dev_explorer' + suffix)
    content = new.read_text() if generated else 'Hand-maintained legacy role.\n'
    old.write_text(content)
    run(repo, 'sync_agents.py', '--check', ok=False)
    assert old.read_text() == content  # Check mode never deletes old profiles.
    run(repo, 'sync_agents.py', ok=generated)
    assert old.exists() != generated
    assert new.is_file()


def test_task_create_status_archive_and_collision(repo):
    run(repo, 'new_task.py', '../escape', ok=False)
    result = run(repo, 'new_task.py', 'sample-work')
    task = Path(result.stdout.strip())
    data = json.loads((task / 'status.json').read_text())
    assert data['task_id'] == datetime.now(timezone.utc).strftime('%Y%m%d') + '-sample-work'
    assert data['started_utc'] == data['updated'] and data['ended_utc'] is None
    assert data['mode'] == 'solo' and data['reason'].strip()
    assert data['state'] == 'planned' and data['based_on_commit'] == 'unknown'
    assert datetime.fromisoformat(data['updated']).tzinfo is not None
    assert '{{' not in (task / 'brief.md').read_text()
    run(repo, 'new_task.py', 'sample-work', ok=False)
    assert data['task_id'] in run(repo, 'task_status.py').stdout
    run(repo, 'archive_task.py', data['task_id'], ok=False)
    data['state'] = 'done'
    (task / 'status.json').write_text(json.dumps(data))
    review = task / 'review.md'
    review.write_text(review.read_text().replace('Verdict: PENDING', 'Verdict: PASS'))
    run(repo, 'archive_task.py', data['task_id'])
    archived = json.loads((repo / 'work/_archive' / data['task_id'] / 'status.json').read_text())
    assert archived['started_utc'] == data['started_utc']
    assert datetime.fromisoformat(archived['ended_utc']) >= datetime.fromisoformat(data['started_utc'])
    assert not task.exists()
    assert (repo / 'work/_archive' / data['task_id']).is_dir()
    assert data['task_id'] in (repo / 'docs/task-log.md').read_text()
    assert data['task_id'] not in run(repo, 'task_status.py').stdout
    run(repo, 'check_docs.py')


@pytest.mark.parametrize('failure', ['length', 'header', 'index', 'status'])
def test_docs_checks_reject_invalid_files(repo, failure):
    path = repo / 'docs/example.md'
    good = 'TL;DR: Example.\nStatus: active; date: 2026-10-19.\n\n# Example\n'
    path.write_text(good)
    run(repo, 'gen_doc_index.py')
    run(repo, 'check_docs.py')
    if failure == 'length':
        path.write_text(good + 'line\n' * 150)
    elif failure == 'header':
        path.write_text(good.replace('TL;DR:', 'Summary:'))
    elif failure == 'status':
        path.write_text(good.replace('Status:', 'State:'))
    else:
        (repo / 'docs/unindexed.json').write_text('{}')
    run(repo, 'check_docs.py', ok=False)
