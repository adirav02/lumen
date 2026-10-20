"""Environment, host, storage, and format capability detection."""

import os
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
from contextlib import closing
from typing import Any, Dict, Optional, Union

from .assessment.export import browser_executable



def check_capabilities(workspace_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
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

    # Check PDF extraction
    pdf_supported = False
    try:
        import pypdf
        pdf_supported = True
    except ImportError:
        pass

    # Check PPTX extraction
    pptx_supported = False
    try:
        import pptx
        pptx_supported = True
    except ImportError:
        pass

    # Check OCR / vision tool availability
    ocr_supported = False
    # Installed libraries do not establish a working OCR ingestion path.

    # Detect current host from environment
    detected_host = "generic_cli"
    if "CLAUDE_CODE" in os.environ or "ANTHROPIC" in os.environ:
        detected_host = "claude_code"
    elif "CODEX" in os.environ or "OPENAI" in os.environ:
        detected_host = "codex"
    elif "ANTIGRAVITY" in os.environ or "GEMINI" in os.environ:
        detected_host = "antigravity"

    # Check file locking
    locking_supported = False
    try:
        import fcntl
        locking_supported = hasattr(fcntl, "flock")
    except ImportError:
        locking_supported = False

    return {
        "status": "ready" if fts5_working and locking_supported and (workspace_path is None or ws_writable) else "limited",
        "contract_version": "1.0.0",
        "detected_host": detected_host,
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": sys.platform,
            "sqlite_version": sqlite3.sqlite_version,
            "fts5_supported": fts5_working,
            "wal_supported": True,
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
            "pdf_export": bool(browser_executable()),
            "pdf_requirement": "Saved test requests require a rendered, visually checked PDF; a saved assessment alone is incomplete.",
        },
        "notes": [
            "Text and structure extractions operate locally without external paid APIs.",
            "PDF and PPTX text extractors are active.",
            "Scanned pages without text layer are flagged with 'uncertain_scanned' quality flags.",
        ],
    }
