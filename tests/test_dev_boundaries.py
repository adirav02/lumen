# TL;DR: Guard legacy doc exemptions and separation of dev tools from tutoring.
# Status: active; date: 2026-10-19.
"""Static boundary checks and a temporary legacy-document fixture."""
import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_indexes_route_preserved_roadmap_without_root_plan(tmp_path):
    folder = tmp_path / 'development/docs/roadmap'
    folder.mkdir(parents=True)
    original = '# Legacy roadmap\n' + 'unchanged\n' * 160
    (folder / '01-history.md').write_text(original)
    subprocess.run([sys.executable, str(ROOT / 'development/scripts/gen_doc_index.py'),
                    '--root', str(tmp_path)], check=True, capture_output=True)
    index = (tmp_path / 'development/docs/INDEX.md').read_text()
    assert '[roadmap/01-history.md](roadmap/01-history.md)' in index
    assert 'Verbatim historical roadmap detail' in index
    assert (folder / '01-history.md').read_text() == original
    assert not (tmp_path / 'plan.md').exists()


def test_legacy_exemption_does_not_hide_new_docs(tmp_path):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'development/scripts').mkdir(parents=True)
    (tmp_path / 'docs/old.md').write_text('# Historical contract\n' + 'old\n' * 160)
    (tmp_path / 'development/scripts/legacy_docs.json').write_text(json.dumps({'files': ['docs/old.md']}))
    subprocess.run([sys.executable, str(ROOT / 'development/scripts/gen_doc_index.py'),
                    '--root', str(tmp_path)], check=True, capture_output=True)
    command = [sys.executable, str(ROOT / 'development/scripts/check_docs.py'), '--root', str(tmp_path)]
    missing = subprocess.run(command, capture_output=True, text=True)
    assert missing.returncode != 0 and '.rgignore' in missing.stdout
    subprocess.run([*command, '--write-rgignore'], check=True, capture_output=True)
    ignore = tmp_path / '.rgignore'
    generated = ignore.read_text()
    assert '/docs/old.md\n' in generated
    ignore.write_text(generated.replace('/docs/old.md\n', ''))
    stale = subprocess.run(command, capture_output=True, text=True)
    assert stale.returncode != 0 and '.rgignore' in stale.stdout
    subprocess.run([*command, '--write-rgignore'], check=True, capture_output=True)
    (tmp_path / 'docs/new.md').write_text('# Missing the required headers\n')
    result = subprocess.run([sys.executable, str(ROOT / 'development/scripts/check_docs.py'),
                             '--root', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0 and 'new.md' in result.stdout


def test_development_and_tutoring_boundaries():
    for role in ('dev_explorer', 'dev_worker', 'dev_planner', 'dev_reviewer', 'manager'):
        folder = 'development/agents' if role == 'manager' else 'development/archive/delegated-agents'
        assert 'description: Development only;' in (ROOT / folder / f'{role}.md').read_text()
    for path in (ROOT / 'src').rglob('*.py'):
        text = path.read_text()
        assert 'agents/hosts.yaml' not in text and 'agents/dev_explorer.md' not in text
    for name in ('sync_agents', '_agent_sources', '_agent_render', '_devtools',
                 'new_task', 'task_status', 'archive_task', 'gen_doc_index',
                 'gen_repo_map', 'check_docs'):
        tree = ast.parse((ROOT / f'development/scripts/{name}.py').read_text())
        for node in ast.walk(tree):
            modules = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                       [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            assert not any(m.split('.')[0] in {'course_tutor', 'lumen'} for m in modules)
