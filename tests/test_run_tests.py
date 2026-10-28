# TL;DR: Verify compact pytest output, full logs and targeted selection.
# Status: active; date: 2026-10-19.
"""Run a copied wrapper against isolated suites to preserve the outer run log."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(tmp_path):
    script = tmp_path / 'development/scripts/run_tests.py'
    script.parent.mkdir(parents=True)
    for name in ('run_tests.py', '_test_receipt.py', '_devtools.py'):
        shutil.copyfile(ROOT / 'development/scripts' / name, script.parent / name)
    (tmp_path / 'pytest.ini').write_text('[pytest]\n')
    (tmp_path / '.gitignore').write_text('.tmp/\n__pycache__/\n.pytest_cache/\n')
    for args in [('init',), ('config', 'user.name', 'Fixture'),
                 ('config', 'user.email', 'redacted-email'),
                 ('add', '.'), ('commit', '-m', 'fixture')]:
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)

    def run(*args):
        return subprocess.run([sys.executable, str(script), *args], cwd=tmp_path,
                              capture_output=True, text=True)

    return run, tmp_path


def test_pass(runner):
    run, root = runner
    (root / 'test_sample.py').write_text(
        'def test_one():\n    print("captured output")\n\n'
        'def test_two():\n    pass\n')
    result = run()
    assert result.returncode == 0
    assert result.stdout == 'PASS 2 tests\n'
    assert result.stderr == ''
    receipt = json.loads((root / '.tmp/test-receipt.json').read_text())
    assert receipt['passed'] == 2 and receipt['full_suite'] is True
    assert receipt['tree_unchanged'] is True and len(receipt['diff_hash']) == 64
    assert len(receipt['head_commit']) == 40
    assert '2 passed' in (root / '.tmp/test-last.log').read_text()


def test_failures_are_bounded_with_full_log(runner):
    run, root = runner
    (root / 'test_sample.py').write_text(
        'import pytest\n' + '@' + 'pytest.mark.parametrize("n", range(18))\n'
        'def test_bad(n):\n    raise ValueError("long message " + "x" * 300)\n')
    result = run()
    assert result.returncode == 1
    assert result.stderr == ''
    lines = result.stdout.splitlines()
    assert len(lines) == 31
    assert lines[-1] == str(root / '.tmp/test-last.log')
    for index in range(15):
        assert lines[index * 2] == f'test_sample.py::test_bad[{index}] ({root / "test_sample.py"}:4)'
        assert lines[index * 2 + 1] == 'x' * 300
    log = (root / '.tmp/test-last.log').read_text()
    assert 'test_bad[17]' in log and 'x' * 300 in log


@pytest.mark.parametrize('args', [('test_sample.py',), ('-k', 'selected'),
                                 ('test_sample.py', '-k', 'selected')])
def test_targeted_run(runner, args):
    run, root = runner
    (root / 'test_sample.py').write_text('def test_selected():\n    pass\n')
    (root / 'test_other.py').write_text('def test_other():\n    assert False\n')
    result = run(*args)
    assert result.returncode == 0
    assert result.stdout == 'PASS 1 tests\n'
    assert result.stderr == ''


@pytest.mark.parametrize('source,args,code', [
    ('\n\n\n\ndef broken(:\n', (), 2),
    ('def test_ok():\n    pass\n', ('-k', 'absent'), 5),
    ('def test_ok():\n    pass\n', ('--unknown-option',), 4),
    ('import pytest\n' + '@' + 'pytest.fixture\ndef broken():\n    raise RuntimeError("setup")\n'
     'def test_setup(broken):\n    pass\n', (), 1),
])
def test_pytest_error_codes_and_logs(runner, source, args, code):
    run, root = runner
    (root / 'test_sample.py').write_text(source)
    result = run(*args)
    assert result.returncode == code
    assert result.stderr == ''
    assert result.stdout.splitlines()[-1] == str(root / '.tmp/test-last.log')
    assert (root / '.tmp/test-last.log').read_text()
    if code in (1, 2):
        assert result.stdout.splitlines()[0].startswith('test_sample.py')
    if code == 2:
        assert result.stdout.splitlines()[0].endswith(f'({root / "test_sample.py"}:5)')


def test_skips_remain_visible_in_compact_summary(runner):
    run, root = runner
    (root / 'test_sample.py').write_text(
        'import pytest\ndef test_optional():\n    pytest.skip("dependency unavailable")\n'
        'def test_ok():\n    pass\n')
    result = run('-ra')
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        'PASS 1 tests', f'SKIP 1 tests (reasons in {root / ".tmp/test-last.log"})']
    assert 'dependency unavailable' in (root / '.tmp/test-last.log').read_text()


@pytest.mark.parametrize('source', [
    'import pytest\ndef test_optional():\n    pytest.skip("unavailable PDF dependency")\n',
    'import pytest\npytest.skip("unavailable PDF dependency", allow_module_level=True)\n',
])
def test_strict_run_rejects_call_and_collection_skips_without_success_receipt(runner, source):
    run, root = runner
    (root / 'test_sample.py').write_text('def test_ok():\n    pass\n')
    assert run().returncode == 0  # A previous success must not survive the failed gate.
    (root / 'test_optional.py').write_text(source)
    result = run('--fail-on-skip', '-ra')
    assert result.returncode == 1
    assert 'FAIL: 1 skipped tests' in result.stdout
    assert 'PASS' not in result.stdout
    assert not (root / '.tmp/test-receipt.json').exists()
    assert 'unavailable PDF dependency' in (root / '.tmp/test-last.log').read_text()


def test_strict_complete_run_retains_full_suite_receipt(runner):
    run, root = runner
    (root / 'test_sample.py').write_text('def test_ok():\n    pass\n')
    result = run('--fail-on-skip', '-ra', '--junitxml=.tmp/results.xml')
    assert result.returncode == 0 and result.stdout == 'PASS 1 tests\n'
    receipt = json.loads((root / '.tmp/test-receipt.json').read_text())
    assert receipt['full_suite'] is True
    assert '--fail-on-skip' in receipt['args']
    assert (root / '.tmp/results.xml').is_file()
