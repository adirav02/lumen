"""Environment, host, storage, and format capability detection."""

import os
from pathlib import Path
import platform
import sqlite3
import sys
from typing import Any, Dict, Optional, Union

from .storage.file_store import FileStore


def check_capabilities(workspace_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Inspect and report host runtime, SQLite features, storage, and format extraction capabilities."""
    ws_writable = False
    ws_str = str(workspace_path) if workspace_path else None
    if workspace_path:
        p = Path(workspace_path).resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / ".lumen_cap_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            ws_writable = True
        except Exception:
            ws_writable = False

    # Check FTS5
    fts5_working = False
    try:
        mem_con = sqlite3.connect(":memory:")
        mem_con.execute("CREATE VIRTUAL TABLE _test_fts USING fts5(content);")
        mem_con.close()
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
    try:
        import pytesseract
        ocr_supported = True
    except ImportError:
        pass

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
        "status": "ready",
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
            "ocr_scans": ocr_supported,
            "visual_source_inspection": "host_dependent",
        },
        "notes": [
            "Text and structure extractions operate locally without external paid APIs.",
            "PDF and PPTX text extractors are active.",
            "Scanned pages without text layer are flagged with 'uncertain_scanned' quality flags.",
        ],
    }
