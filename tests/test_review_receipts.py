# TL;DR: Test tree identities, successful receipts and failure invalidation.
# Status: active; date: 2026-10-19.
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from _test_receipt import receipt_status, save_receipt, tree_identity
import run_tests


@pytest.fixture
def git_repo(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'redacted-email')
    (tmp_path / '.gitignore').write_text('.tmp/\nwork/\n')
    (tmp_path / 'tracked').write_text('original\n')
    git('add', '.')
    git('commit', '-m', 'fixture')
    return tmp_path


def test_identity_includes_staged_unstaged_and_untracked(git_repo):
    root = git_repo
    initial = tree_identity(root)
    (root / 'tracked').write_text('changed\n')
    unstaged = tree_identity(root)
    assert unstaged != initial
    subprocess.run(['git', 'add', 'tracked'], cwd=root, check=True)
    assert tree_identity(root) == unstaged
    (root / 'new').write_bytes(b'\x00one')
    first = tree_identity(root)
    (root / 'new').write_bytes(b'\x00two')
    assert tree_identity(root) != first
    (root / '.tmp').mkdir()
    (root / '.tmp/cache').write_text('ignored')
    before = tree_identity(root)
    (root / '.tmp/cache').write_text('different')
    assert tree_identity(root) == before


def test_receipt_matches_only_tested_tree_and_records_scope(git_repo):
    (git_repo / '.tmp').mkdir()
    before = tree_identity(git_repo)
    receipt = save_receipt(git_repo, before, 42, [])
    assert receipt_status(git_repo) == (receipt, True)
    assert receipt['full_suite'] is True and receipt['passed'] == 42
    assert receipt['timestamp_utc'].endswith('+00:00')
    (git_repo / 'tracked').write_text('later')
    assert receipt_status(git_repo)[1] is False
    receipt = save_receipt(git_repo, before, 2, ['tests/test_example.py'])
    assert receipt['tree_unchanged'] is False and receipt['full_suite'] is False
    assert receipt_status(git_repo)[1] is False


@pytest.mark.parametrize('code', [0, 1])
def test_wrapper_writes_success_receipt_and_clears_it_on_failure(git_repo, monkeypatch, code):
    (git_repo / '.tmp').mkdir()
    stale = git_repo / '.tmp/test-receipt.json'
    stale.write_text('{}')
    real_run = subprocess.run
    def fake_run(command, **kwargs):
        if '--_pytest-child' in command:
            Path(command[3]).write_text(json.dumps({'passed': 7, 'failures': {}}))
            return SimpleNamespace(returncode=code)
        return real_run(command, **kwargs)
    monkeypatch.setattr(run_tests, 'ROOT', git_repo)
    monkeypatch.setattr(run_tests.subprocess, 'run', fake_run)
    assert run_tests.main(['tests/focused.py']) == code
    if code:
        assert not stale.exists()
    else:
        receipt, matches = receipt_status(git_repo)
        assert matches and receipt['passed'] == 7 and receipt['full_suite'] is False
