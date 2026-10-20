"""Capability state reflects imports and an actual production render probe."""
import pytest
from course_tutor import capabilities as caps


def present(monkeypatch):
    monkeypatch.setattr(caps.importlib, 'import_module', lambda name: object())
    monkeypatch.setattr(caps, 'probe_pdf_export', lambda: None)


def test_all_dependencies_and_render_present(monkeypatch, tmp_path):
    present(monkeypatch)
    report = caps.check_capabilities(tmp_path)
    assert report['status'] == 'ready'
    assert report['artifact_capabilities']['pdf_export']
    assert not report['missing']


def test_one_dependency_missing_is_degraded(monkeypatch, tmp_path):
    present(monkeypatch)
    def load(name):
        if name == 'pptx':
            raise ImportError('synthetic missing dependency')
        return object()
    monkeypatch.setattr(caps.importlib, 'import_module', load)
    report = caps.check_capabilities(tmp_path)
    assert report['status'] == 'degraded'
    assert report['missing'] == ['pptx']
    assert report['extraction_capabilities']['pptx_slides'] is False
    assert 'PPTX text extractor: unavailable.' in report['notes']
    assert not report['artifact_capabilities']['pdf_export']


def test_render_failure_is_blocked(monkeypatch, tmp_path):
    present(monkeypatch)
    def fail():
        raise RuntimeError('synthetic render failure')
    monkeypatch.setattr(caps, 'probe_pdf_export', fail)
    report = caps.check_capabilities(tmp_path)
    assert report['status'] == 'blocked'
    assert not report['artifact_capabilities']['pdf_export']
    assert 'synthetic render failure' in report['failures'][0]
