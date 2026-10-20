"""Host output states the declaration/observation rather than claiming live verification."""
import pytest
from course_tutor.host import detect_host
from course_tutor.errors import ValidationError


def clear(monkeypatch):
    for key in ('LUMEN_HOST','CLAUDE_CODE','ANTHROPIC','CODEX','OPENAI','CODEX_THREAD_ID','ANTIGRAVITY','GEMINI'):
        monkeypatch.delenv(key,raising=False)


def test_override_precedes_env_and_markers(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv('LUMEN_HOST','claude_code')
    monkeypatch.setenv('ANTIGRAVITY','1')
    h=detect_host('codex')
    assert h['host']=='codex' and h['method']=='override' and h['evidence']=='--host'
    assert not h['verified']
    assert detect_host()['evidence']=='LUMEN_HOST'
    with pytest.raises(ValidationError):
        detect_host('invented')


def test_marker_fallback_and_conflict(monkeypatch):
    clear(monkeypatch)
    assert detect_host()['method']=='fallback'
    monkeypatch.setenv('CODEX_THREAD_ID','synthetic')
    assert detect_host()['method']=='marker'
    monkeypatch.setenv('CLAUDE_CODE','1')
    assert detect_host()['host']=='generic_cli'
