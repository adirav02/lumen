"""Regression coverage for the quiet test wrapper's failure diagnostics."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def wrapper(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts/run_tests.py'
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location('run_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failure_keeps_location_and_last_two_error_line_tails(wrapper):
    class Longrepr:
        reprcrash = SimpleNamespace(path='tests/test_example.py', lineno=42)

        def __str__(self):
            return 'E   earlier error\nE   ' + 'x' * 400 + ' END\nE   final error\ntraceback footer'

    report = SimpleNamespace(failed=True, nodeid='test_example.py::test_bad', longrepr=Longrepr())
    summary = wrapper.Summary()
    summary.record(report)
    assert summary.failures[report.nodeid] == {
        'location': 'tests/test_example.py:42',
        'errors': ['x' * 296 + ' END', 'E   final error'],
    }


@pytest.mark.parametrize('code', [0, 1])
def test_output_preserves_pass_line_failure_cap_and_log(wrapper, tmp_path, monkeypatch, capsys, code):
    monkeypatch.setattr(wrapper, 'ROOT', tmp_path)
    monkeypatch.setattr(wrapper, 'tree_identity', lambda root: {})
    monkeypatch.setattr(wrapper, 'save_receipt', lambda *args: {'tree_unchanged': True})

    def child(command, stdout, stderr):
        Path(command[3]).write_text(json.dumps({
            'passed': 7,
            'failures': {f'test.py::test_bad[{i}]': {
                'location': 'test.py:12', 'errors': ['E   first', 'E   last'],
            } for i in range(16)},
        }))
        stdout.write('complete log\n')
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(wrapper.subprocess, 'run', child)
    assert wrapper.main([]) == code
    output = capsys.readouterr().out
    if code == 0:
        assert output == 'PASS 7 tests\n'
    else:
        assert output.count('(test.py:12)') == 15
        assert 'test.py::test_bad[14] (test.py:12)\nE   first\nE   last\n' in output
        assert 'test_bad[15]' not in output
        assert output.endswith(str(tmp_path / '.tmp/test-last.log') + '\n')
    assert (tmp_path / '.tmp/test-last.log').read_text() == 'complete log\n'
