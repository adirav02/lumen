# Codex Review and Continuation Handoff — Lumen

**Date**: 2026-10-10  
**Repository**: `lumen`  
**Git Commit**: `e7ad396` (initial commit) + working tree implementation  
**Author / Initial Implementer**: Antigravity Assistant  
**Target Recipient**: OpenAI Codex (and continuing engineering agents)

---

## 1. Executive Summary & Implemented Scope

All functional milestones **M0 through M4** and the **M5 verification infrastructure** from `plan.md` are fully implemented, verified, and passing automated tests.

Lumen is an installable Python package (`lumen` / `course_tutor`) backed by SQLite (with FTS5) and an immutable content-addressed file store. It provides a structured JSON CLI, complete provenance-backed retrieval, trustworthy evidence recording (distinguishing independent vs. assisted mastery), audit-preserving mistake corrections, resumable diagnostics, and byte-for-byte workspace backup and restoration.

### What Works
1. **Core Package & CLI**: Installable via `pip install -e .`. The structured CLI `lumen` emits compact JSON to stdout and diagnostic logs to stderr. Machine-readable error envelopes handle all failure modes.
2. **Database & Storage**: Versioned migrations, foreign-key enforcement, WAL mode, transaction isolation with savepoints, and immutable original storage (`originals/<hash>_<filename>`) with SHA-256 verification.
3. **Idempotency & Revisions**: Operations take stable `request_id`s and canonical request hashes. Retries return cached receipts (F15); conflicts raise `IdempotencyConflictError` (F16). Stale revision concurrency checks protect attempts (F18).
4. **Ingestion & Extraction**: Text, PDF (via `pypdf`), and PPTX (via `python-pptx`) extractors. Scanned or empty pages produce explicit `uncertain_scanned` quality flags (F01).
5. **Retrieval**: SQLite FTS5 with `unicode61` tokenizer supporting English, Hebrew, and mathematical notation. Topic aliases and dependency expansion guarantee complete assumption retrieval without truncation (F02, F03, F26).
6. **Tutoring & Evidence**: Graded assistance tracking (hints, solution exposures) ensures that success after assistance is recorded as `assisted_success` rather than false independent mastery (F07). Partial credit for arithmetic errors is preserved (F09). Untouched subparts remain unassessed (F08).
7. **Mistake Correction**: `correct_evidence` retracts or supersedes prior evidence and deterministically recalculates topic state projections without erasing audit history (F11).
8. **Diagnostics**: Coverage blueprint enforcement, question validation checks (F12), exposure tracking (F10), and transparent progress reporting without fabricated pass probabilities.
9. **Backup & Restore**: Online SQLite snapshot backup and source copy with `manifest.json`. Restore verifies database and source file hashes, foreign keys, and integrity before committing (F24, F25).
10. **Host Integration**: Instruction discovery and loaders configured for Codex (`AGENTS.md`, `.agents/skills/lumen/SKILL.md`, `.codex/`), Claude Code (`CLAUDE.md`, `.claude/`), and Antigravity.

### Incomplete / Deferred Scope
- **Live Smoke Testing Inside Native Codex CLI/IDE**: While host configurations are verified and all 30 core tests pass in Linux/Python 3.14, live interactive execution from inside the Codex client environment should be performed by Codex during continuation.
- **Local OCR Engine**: Scanned pages currently raise explicit actionable limitations (`ocr_scans: false`). If local vision/OCR is desired in future phases, a local OCR dependency (e.g. Tesseract) can be plugged into `PDFExtractor`.
- **Deferred Architecture**: Cloud synchronization, live multi-user concurrency, and external vector databases were intentionally excluded per `goal.md`.

---

## 2. Exact Commands Executed and Verified

The following commands were executed in the environment and succeeded:

```bash
# 1. Environment & editable package installation
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2. Capabilities check
.venv/bin/lumen capabilities
# Output: {"status": "success", "data": {"contract_version": "1.0.0", "fts5_supported": true, ...}}

# 3. Full automated test suite (30/30 passed)
.venv/bin/pytest -v
# Output: 30 passed in 1.62s

# 4. Standalone synthetic probability course demonstration
.venv/bin/python demo.py
# Output: All 11 demonstration steps succeeded with verified restore integrity!

# 5. Payload measurement test
.venv/bin/pytest tests/test_efficiency.py -s
# Output: Brief (931 B) vs Raw Injection (2807 B) -> 66.8% payload reduction
```

---

## 3. Test Suite Breakdown

All 30 automated test cases in `tests/` pass cleanly:
- `tests/test_storage_and_integrity.py` (9 tests): F05, F06, F15, F16, F18, F19, F24, F25, and restore fidelity.
- `tests/test_ingestion_and_retrieval.py` (5 tests): F01, F02/F26, F03, F04, F23.
- `tests/test_tutoring_and_evidence.py` (7 tests): F07, F08, F09/F13, F10, F11, F12, F20.
- `tests/test_cli_and_e2e.py` (3 tests): CLI capabilities, error envelopes, and complete end-to-end course slice.
- `tests/test_scenarios_extended.py` (6 tests): F14, F17, F21, F22, F28, F29.

---

## 4. Key Architectural Decisions & Storage Locations

1. **Python 3.14 Transaction Handling**:
   - In Python 3.14 with `autocommit=True`, transactions started with `BEGIN IMMEDIATE;` must be committed with explicit `con.execute("COMMIT;")` and `con.execute("ROLLBACK;")`. `src/course_tutor/storage/db.py` handles this and uses SQLite `SAVEPOINT`s for safe nested transactions.
2. **Authoritative SQLite vs Interchange JSON**:
   - SQLite (`lumen.db`) is the sole authoritative store. JSON is strictly an interchange format for CLI I/O and serialized entity fields.
3. **Storage Hierarchy**:
   - `<workspace>/lumen.db`: SQLite database.
   - `<workspace>/originals/<hash[:16]>_<filename>`: Immutable source files and student attachments.
   - `<workspace>/staging/`: Upload quarantine directory. Orphaned staging files are cleaned up without touching referenced originals.
4. **Entry Points & Modules**:
   - `src/course_tutor/cli.py`: Console entry point (`lumen` command).
   - `src/course_tutor/api.py`: `LumenCore` facade coordinating idempotency receipts and transactions.
   - `src/course_tutor/storage/`: Database connection, versioned migrations, file store, repositories.
   - `src/course_tutor/ingestion/`: Format dispatch, quality checks, semantic unit construction.
   - `src/course_tutor/retrieval/`: FTS5 index, multilingual search, dependency expansion.
   - `src/course_tutor/learning/`: Attempts, assistance enforcement, evidence commits, mistake corrections.
   - `src/course_tutor/assessment/`: Diagnostic blueprints, exposure tracking, course brief.
   - `src/course_tutor/backup/`: Snapshot backup and restore with manifest verification.

---

## 5. Review Targets for Codex

When continuing this codebase, please review:
1. **Live Codex Interaction**: Run `lumen course-brief` and `lumen search` from Codex prompts to verify host prompt integration.
2. **Skill Prompting**: Verify that Codex automatically loads `.agents/skills/lumen/SKILL.md` when tasked with tutoring workflows.
3. **Extended Formats**: Evaluate whether additional format handlers (e.g. DOCX or HTML) are needed for future course materials.
4. **Mathematical LaTeX Tokenization**: Check if specialized LaTeX token filtering is desired beyond standard SQLite FTS5 unicode61 tokenizer.

---

## 6. Git Working-Tree Status

Current working tree contains all source code, tests, documentation, and host configurations ready for commit:
- Untracked files:
  - `src/`, `tests/`, `examples/`, `demo.py`, `pyproject.toml`, `README.md`, `.gitignore`
  - `.agents/skills/lumen/SKILL.md`, `.claude/skills/lumen/SKILL.md`, `.codex/`
  - `docs/implementation-status.md`, `docs/codex-handoff.md`
- Preserved existing specification files: `AGENTS.md`, `CLAUDE.md`, `docs/agents.md`, `goal.md`, `plan.md`.
