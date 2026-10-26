"""Recreate tiny synthetic binaries without resurrecting removed example folders."""
import importlib.util
from pathlib import Path

import pytest

from course_tutor import usage_collector


def pytest_sessionstart(session):
    path = Path(__file__).parent/'fixtures/build_synthetic.py'
    spec = importlib.util.spec_from_file_location('synthetic_test_fixtures', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build()


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
