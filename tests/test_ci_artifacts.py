"""Execute artifact integrity commands without contacting GitHub or creating releases."""
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.load((ROOT / f'.github/workflows/{name}.yml').read_text(), Loader=yaml.BaseLoader)


def test_ci_enforces_complete_execution():
    steps = workflow('ci')['jobs']['test']['steps']
    runs = [s['run'] for s in steps if 'development/scripts/run_tests.py' in s.get('run', '')]
    assert len(runs) == 1 and '--fail-on-skip' in runs[0]


@pytest.mark.parametrize('damage', [None, 'changed', 'missing', 'malformed'])
def test_validated_artifact_handoff_rejects_damage_before_release(tmp_path, damage):
    package = workflow('ci')['jobs']['package']['steps']
    release = workflow('release')['jobs']['release']['steps']
    record = next(s for s in package if s['name'] == 'Record validated distribution checksums')
    verify = next(s for s in release if s['name'] == 'Verify downloaded distribution checksums')
    assert record['working-directory'] == verify['working-directory'] == 'dist'
    assert package.index(record) < len(package) - 1  # Before artifact upload.
    assert release.index(verify) < len(release) - 1  # Before draft creation.
    wheel = tmp_path / 'lumen-0.1.0-py3-none-any.whl'
    wheel.write_bytes(b'validated wheel bytes')
    (tmp_path / 'lumen-0.1.0.tar.gz').write_bytes(b'validated sdist bytes')
    subprocess.run(['bash', '-e', '-c', record['run']], cwd=tmp_path, check=True)
    assert len((tmp_path / 'SHA256SUMS').read_text().splitlines()) == 2
    if damage == 'changed':
        wheel.write_bytes(b'different wheel bytes')
    elif damage == 'missing':
        wheel.unlink()
    elif damage == 'malformed':
        with (tmp_path / 'SHA256SUMS').open('a') as manifest:
            manifest.write('not a checksum record\n')
    result = subprocess.run(['bash', '-e', '-c', verify['run']], cwd=tmp_path, capture_output=True)
    assert (result.returncode == 0) == (damage is None)
