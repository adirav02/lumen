"""Recreate tiny synthetic binaries without resurrecting removed example folders."""
import importlib.util
from pathlib import Path
import shutil
import tempfile

import pytest

from course_tutor import usage_collector


def pytest_sessionstart(session):
    path = Path(__file__).parent/'fixtures/build_synthetic.py'
    spec = importlib.util.spec_from_file_location('synthetic_test_fixtures', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Build missing synthetic binaries in scratch space. Existing fixtures are
    # immutable inputs: rebuilding PPTX ZIPs changes their timestamp bytes.
    scratch = Path(__file__).resolve().parents[1] / '.tmp'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='synthetic-fixtures-', dir=scratch) as directory:
        staged = Path(directory)
        for folder in ('audit_course/materials', 'synthetic_probability/materials',
                       'educational_evaluation'):
            (staged / folder).mkdir(parents=True)
        module.ROOT = staged
        module.build()
        for source in staged.rglob('*'):
            if source.is_file():
                target = path.parent / source.relative_to(staged)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)


@pytest.fixture
def watcher_clock(monkeypatch):
    """Advance watcher time only through requested sleeps or explicit test work."""
    class Clock:
        def __init__(self):
            self.elapsed = 0.0
            self.sleeps = []

        def monotonic(self):
            return self.elapsed

        def sleep(self, seconds):
            assert seconds > 0
            self.sleeps.append(seconds)
            self.elapsed += seconds

    clock = Clock()
    # Replace this module's clock, leaving the process-wide time module alone.
    monkeypatch.setattr(usage_collector, "time", clock)
    return clock
