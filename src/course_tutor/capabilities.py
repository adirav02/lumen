"""Environment, host, storage, and format capability detection."""

import os
import importlib
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
from contextlib import closing
from typing import Any, Dict, Optional, Union

from .host import detect_host



def check_capabilities(workspace_path: Optional[Union[str, Path]] = None, host: Optional[str] = None) -> Dict[str, Any]:
    """Inspect and report host runtime, SQLite features, storage, and format extraction capabilities."""
    ws_writable = False
    ws_str = str(workspace_path) if workspace_path else None
    if workspace_path:
        p = Path(workspace_path).resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=p) as test_file:
                test_file.write(b"ok")
            ws_writable = True
        except Exception:
            ws_writable = False

    # Check FTS5
    fts5_working = False
    try:
        with closing(sqlite3.connect(":memory:")) as mem_con:
            mem_con.execute("CREATE VIRTUAL TABLE _test_fts USING fts5(content);")
        fts5_working = True
    except Exception:
        fts5_working = False

    modules = {}
    for name in ('pypdf', 'pptx', 'latex2mathml.converter'):
        try:
            importlib.import_module(name)
            modules[name] = {'available': True, 'error': None}
        except Exception as exc:
            modules[name] = {'available': False, 'error': f'{type(exc).__name__}: {exc}'}
    pdf_supported = modules['pypdf']['available']
    pptx_supported = modules['pptx']['available']
    ocr_supported = False  # No implemented OCR ingestion path.
    pdf_export = False
    render_error = None
    dependencies_ready = all(check['available'] for check in modules.values())
    # Exercise the production renderer, including MathML and PDF parsing. A
    # discoverable executable alone is never evidence of a working export path.
    if dependencies_ready:
        try:
            probe_pdf_export()
            pdf_export = True
        except Exception as exc:
            render_error = f'{type(exc).__name__}: {exc}'

    host_detection = detect_host(host)

    # Check file locking
    locking_supported = False
    try:
        import fcntl
        with tempfile.TemporaryFile() as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
        locking_supported = True
    except (ImportError, OSError):
        locking_supported = False

    wal_supported = False
    try:
        with tempfile.TemporaryDirectory(prefix='lumen-wal-') as directory:
            with closing(sqlite3.connect(str(Path(directory)/'probe.db'))) as con:
                wal_supported = con.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    except (OSError, sqlite3.Error):
        pass
    missing = [name for name, check in modules.items() if not check['available']]
    failures = []
    if not fts5_working:
        failures.append('SQLite FTS5')
    if not wal_supported:
        failures.append('SQLite WAL')
    if not locking_supported:
        failures.append('file locking')
    if workspace_path is not None and not ws_writable:
        failures.append('writable workspace')
    if render_error:
        failures.append('PDF render: '+render_error)
    status = 'blocked' if failures else 'degraded' if missing else 'ready'
    return {
        "status": status,
        "missing": missing, "failures": failures, "module_checks": modules,
        "contract_version": "1.0.0",
        "detected_host": host_detection["host"],
        "host_detection": host_detection,
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": sys.platform,
            "sqlite_version": sqlite3.sqlite_version,
            "fts5_supported": fts5_working,
            "wal_supported": wal_supported,
            "locking_supported": locking_supported,
        },
        "workspace": {
            "path": ws_str,
            "writable": ws_writable,
        },
        "extraction_capabilities": {
            "text_markdown": True,
            "pdf_text": pdf_supported,
            "pptx_slides": pptx_supported,
            "docx_ooxml": True,
            "legacy_doc": False,
            "ocr_scans": ocr_supported,
            "visual_source_inspection": "host_dependent",
            "exam_question_catalog": "text_boundaries_with_required_review",
            "question_similarity": "indexed_text_and_numeric_template_candidates",
        },
        "artifact_capabilities": {
            "assessment_paper": True,
            "reviewed_png_snapshots": True,
            "pdf_export": pdf_export,
            "pdf_render_error": render_error,
            "pdf_requirement": "Saved test requests require a rendered, visually checked PDF; a saved assessment alone is incomplete.",
        },
        "notes": [
            "Text and structure extractions operate locally without external paid APIs.",
            f"PDF text extractor: {'active' if pdf_supported else 'unavailable'}. Try doctor for dependency details.",
            f"PPTX text extractor: {'active' if pptx_supported else 'unavailable'}.",
            f"PDF export: {'verified by render probe' if pdf_export else 'unavailable'}.",
            "Scanned pages without text layer are flagged with 'uncertain_scanned' quality flags.",
        ],
    }


def probe_pdf_export():
    """Render and parse a tiny fixture using the exact production export path."""
    from .assessment.export import render_staged_paper
    paper = {'assessment_id': 'capability-probe', 'title': 'SYNTHETIC runtime probe',
             'questions': [{'item_order': 1, 'exercise_version_id': 'probe',
                            'question_text': r'Compute $\frac{1}{2}+x^2$.',
                            'source_reference': None, 'subparts': []}]}
    with tempfile.TemporaryDirectory(prefix='lumen-capability-') as directory:
        render_staged_paper(paper, directory)
        path = Path(directory)/'test.pdf'
        if not path.read_bytes().startswith(b'%PDF-'):
            raise ValueError('Renderer output is not a PDF.')
