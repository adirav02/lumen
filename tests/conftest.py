"""Recreate tiny synthetic binaries without resurrecting removed example folders."""
import importlib.util
from pathlib import Path


def pytest_sessionstart(session):
    path = Path(__file__).parent/'fixtures/build_synthetic.py'
    spec = importlib.util.spec_from_file_location('synthetic_test_fixtures', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build()
