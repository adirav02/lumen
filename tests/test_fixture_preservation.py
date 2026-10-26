"""Synthetic startup generation must leave existing checkout fixture bytes intact."""
from pathlib import Path

import conftest


def test_startup_only_materializes_missing_fixture_files(tmp_path, monkeypatch):
    tests = tmp_path / 'tests'
    fixtures = tests / 'fixtures'
    existing = fixtures / 'audit_course/materials/existing.pptx'
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'immutable synthetic original')
    (fixtures / 'build_synthetic.py').write_text(
        'from pathlib import Path\n'
        'ROOT = Path(__file__).parent\n'
        'def build():\n'
        '    (ROOT / "audit_course/materials/existing.pptx").write_bytes(b"rebuilt")\n'
        '    (ROOT / "synthetic_probability/materials/missing.pdf").write_bytes(b"new fixture")\n')
    monkeypatch.setattr(conftest, '__file__', str(tests / 'conftest.py'))
    conftest.pytest_sessionstart(None)
    assert existing.read_bytes() == b'immutable synthetic original'
    assert (fixtures / 'synthetic_probability/materials/missing.pdf').read_bytes() == b'new fixture'
    assert list((tmp_path / '.tmp').iterdir()) == []
