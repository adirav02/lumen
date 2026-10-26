"""Runtime probes must exercise supported operations and reject checkout imports."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_demo_runs_self_contained_and_cleans_workspaces(tmp_path):
    import os
    # No companion examples directory or tests directory is available to the demo.
    demo = tmp_path / 'demo.py'
    demo.write_bytes((ROOT / 'demo.py').read_bytes())
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    result = subprocess.run([sys.executable, str(demo)], cwd=tmp_path,
                            env={**os.environ, 'TMPDIR': str(scratch)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DEMO COMPLETE' in result.stdout
    assert 'assisted success' in result.stdout and 'Backup/restore' in result.stdout
    assert list(scratch.glob('lumen-demo-*')) == []


def test_wheel_probe_rejects_source_environment(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('probe', ROOT / 'scripts/_installed_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    # Even with a venv, source imports cannot count as distribution evidence.
    import course_tutor
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / 'env'))
    monkeypatch.setattr(sys, 'base_prefix', str(tmp_path / 'base'))
    monkeypatch.setattr(course_tutor, '__file__', str(ROOT / 'src/course_tutor/__init__.py'))
    with pytest.raises(AssertionError, match='course_tutor'):
        probe.main(str(ROOT), str(ROOT / 'tests/fixtures/installed/lecture.txt'))


def test_demo_cleans_workspaces_after_failure(tmp_path, monkeypatch):
    import tempfile
    spec = importlib.util.spec_from_file_location('demo', ROOT / 'demo.py')
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    def fail(root):
        (root / 'workspace').mkdir()
        (root / 'restored').mkdir()
        raise RuntimeError('synthetic interruption')
    monkeypatch.setattr(demo, 'demonstrate', fail)
    with pytest.raises(RuntimeError, match='synthetic interruption'):
        demo.main()
    assert list(tmp_path.iterdir()) == []
