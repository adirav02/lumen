# TL;DR: Verify offline cache recovery, failure cleanup and dependency-free watcher lifecycle.
# Status: active; date: 2026-10-26.
"""No network requests; subprocess watcher runs with site packages disabled."""
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap', ROOT / 'scripts/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def test_recover_http_and_wheel_cache_without_extracting(tmp_path):
    cache, target = tmp_path / 'cache', tmp_path / 'staged'
    cache.mkdir()
    target.mkdir()
    for filename, distribution in [('wheel.body', 'demo-1.0'), ('other.whl', 'other-2.0')]:
        with zipfile.ZipFile(cache / filename, 'w') as archive:
            archive.writestr(f'{distribution}.dist-info/WHEEL',
                             'Wheel-Version: 1.0\nTag: py3-none-any\n')
            archive.writestr('vendor/nested-1.dist-info/WHEEL', 'Tag: py3-none-any\n')
            archive.writestr('../../escaped', 'Never extract me')
    (cache / 'index.body').write_text('<html>package index</html>')
    before = {p.name: p.read_bytes() for p in cache.iterdir()}
    assert bootstrap.stage_cached_wheels(cache, target) == 2
    assert {p.name for p in target.iterdir()} == {'demo-1.0-py3-none-any.whl', 'other-2.0-py3-none-any.whl'}
    assert not (tmp_path / 'escaped').exists()
    assert before == {p.name: p.read_bytes() for p in cache.iterdir()}


def test_offline_commands_and_cleanup_after_failure(tmp_path, monkeypatch):
    target = tmp_path / 'venv'
    target.mkdir()
    (target / 'pyvenv.cfg').touch()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if '-e' in command:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        bootstrap.bootstrap(tmp_path, target, tmp_path / 'empty-cache')
    assert len(calls) == 2
    assert all('--no-index' in cmd and '--no-cache-dir' in cmd for cmd in calls)
    assert '--no-build-isolation' in calls[-1]
    assert not list((tmp_path / '.tmp').iterdir())


def watcher_command(project, *args):
    return [sys.executable, '-S', str(ROOT / 'scripts/watch_usage.py'),
            '--label', 'solo-default', '--project', str(project), '--host', 'codex',
            '--usage-log-location', str(project / 'logs'), *args]


def test_watcher_starts_without_venv_or_site_packages(tmp_path):
    (tmp_path / 'logs').mkdir()
    result = subprocess.run(watcher_command(tmp_path, '--duration-seconds', '0'),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[0]['event'] == 'started' and events[0]['label'] == 'solo-default'
    assert events[-1]['event'] == 'stopped' and events[-1]['stopped'] == 'duration'
    assert not (tmp_path / '.venv').exists()


def test_watcher_sigterm_collects_and_stops(tmp_path):
    (tmp_path / 'logs').mkdir()
    process = subprocess.Popen(watcher_command(tmp_path), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        assert json.loads(process.stdout.readline())['event'] == 'started'
        process.send_signal(signal.SIGTERM)
        output, errors = process.communicate(timeout=15)
        assert process.returncode == 0, errors
        assert json.loads(output.splitlines()[-1])['event'] == 'stopped'
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
