"""Relocation must preserve ignore boundaries, indexes and legacy host ownership."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'development/scripts'))
from gen_doc_index import generate
from check_docs import check
from sync_agents import sync
import shutil


def test_task_and_private_ignores_keep_template_and_docs_visible(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    shutil.copyfile(ROOT / '.gitignore', tmp_path / '.gitignore')
    ignored = ['development/work/20261026-example/report.md',
               'development/work/_archive/20261026-example/report.md',
               'local-courses/example/sources/original.pdf', '.lumen/lumen.db',
               '.tmp/test-receipt.json', 'test-results/pytest.xml']
    visible = ['development/work/_template/brief.md',
               'development/work/_template/findings/.gitkeep',
               'development/README.md', 'development/docs/architecture.md',
               'development/scripts/run_tests.py', 'docs/course-layout.md']
    for path in ignored + visible:
        result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', path], cwd=tmp_path)
        assert result.returncode == (0 if path in ignored else 1), path


def test_development_index_coverage_and_headers_are_enforced(tmp_path):
    folder = tmp_path / 'development/docs'
    folder.mkdir(parents=True)
    good = 'TL;DR: Example.\nStatus: active; date: 2026-10-26.\n'
    (folder / 'example.md').write_text(good)
    assert generate(tmp_path)
    assert check(tmp_path) == []
    (folder / 'unindexed.json').write_text('{}')
    assert any('unindexed.json' in error for error in check(tmp_path))
    assert generate(tmp_path)
    (folder / 'example.md').write_text('# No required header\n')
    assert any('must start with TL;DR' in error for error in check(tmp_path))


def test_sync_recognizes_pre_migration_generated_marker(tmp_path):
    shutil.copytree(ROOT / 'development/agents', tmp_path / 'development/agents')
    (tmp_path / 'AGENTS.md').write_text('Loader\n')
    old = tmp_path / '.codex/agents/dev_worker.toml'
    old.parent.mkdir(parents=True)
    old.write_text('# GENERATED from agents/ - edit the source\n')
    assert not sync(tmp_path, check=True)
    assert old.exists()
    assert sync(tmp_path)
    assert not old.exists()
    assert sync(tmp_path, check=True)
