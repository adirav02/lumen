# TL;DR: Verify the roadmap guard detects content loss, ordering and size violations.
# Status: active; date: 2026-10-19.
"""Exercise preservation failures without modifying the repository roadmap."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def check(root):
    return subprocess.run(
        [sys.executable, str(ROOT / 'scripts/check_roadmap.py'), '--root', str(root)],
        capture_output=True, text=True,
    )


@pytest.fixture
def roadmap(tmp_path):
    shutil.copytree(ROOT / 'docs/roadmap', tmp_path / 'docs/roadmap')
    (tmp_path / 'scripts').mkdir()
    shutil.copyfile(ROOT / 'scripts/roadmap_manifest.json',
                    tmp_path / 'scripts/roadmap_manifest.json')
    assert check(tmp_path).returncode == 0
    return tmp_path


@pytest.mark.parametrize('change', [
    'content', 'missing', 'extra', 'order', 'header', 'part_limit', 'index_limit',
])
def test_preservation_rejects_damage(roadmap, change):
    folder = roadmap / 'docs/roadmap'
    part = folder / '00-preamble.md'
    if change == 'content':
        part.write_bytes(part.read_bytes().replace(b'Fixed decisions:', b'Changed decisions:'))
    elif change == 'missing':
        part.unlink()
    elif change == 'extra':
        shutil.copyfile(part, folder / '99-extra.md')
    elif change == 'order':
        path = roadmap / 'scripts/roadmap_manifest.json'
        manifest = json.loads(path.read_text())
        manifest['parts'].reverse()
        path.write_text(json.dumps(manifest))
    elif change == 'header':
        part.write_bytes(part.read_bytes().replace(b'<!-- ROADMAP:ORIGINAL -->', b'<!-- wrong -->'))
    elif change == 'part_limit':
        part.write_bytes(part.read_bytes() + b'\n' * 150)
    else:
        (folder / 'INDEX.md').write_text('\n' * 61)
    result = check(roadmap)
    assert result.returncode != 0, result.stdout + result.stderr
