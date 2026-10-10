# Codex Review and Continuation Handoff — Lumen

**Date**: 2026-10-10  
**Repository**: `lumen`  
**Git Base**: Verified repairs following commit `88f81d5`  
**Author / Initial Implementer**: Antigravity Assistant  
**Target Recipient**: OpenAI Codex (and continuing engineering agents)

---

## 1. Executive Summary & Verified Defect Resolutions

In response to Codex's probes on commit `88f81d5`, all 8 identified defects have been repaired and verified across 51 automated tests (including 7 comprehensive regression tests in `tests/test_verified_defect_repairs.py`) and the synthetic probability demo.

### Key Fixes Implemented

1. **Observed, Validated Work Required Before Awarding Scores (Defect 1)**:
   - `record_assessment_item_score` enforces:
     - An attempt linked to the exact assessment item, exercise version, course, and learner.
     - A committed work submission with non-empty observed content.
     - Active evaluated evidence tied to that submission.
     - Rejection of non-finite values (`NaN`, `Inf`).
   - `get_progress` reports separate projections for `observed_scores`, `coverage`, `assistance`, and `pending_work` without penalizing unattempted items.

2. **Assessment Scores Follow Evidence Corrections/Retractions (Defect 2)**:
   - When evidence is retracted or superseded via `correct_evidence`, any linked scored assessment items revert to `score_status="pending_review"` and `points_awarded=None`.
   - The assessment status reverts from `completed` back to `open`.
   - Full audit history is recorded in `score_history` and persists across workspace reopening.

3. **Removed Automatic Exercise Validation Throughout Public Interface (Defect 3)**:
   - `create_exercise` defaults new questions to `pending_review` and ignores strings claiming `"validated"`.
   - Explicit validation transition (`validate_exercise_version`) requires non-empty reference solution, structured rubric, and recorded verification checks.
   - Question text or rubric updates (`update_exercise_version`) reset `validation_state` to `pending_review`, invalidate active evaluations, and revert linked assessment items to `pending_review`.

4. **Closed Evidence and Assistance Bypasses in LearningService (Defect 4)**:
   - `commit_evidence` strictly rejects non-submission event IDs (e.g. `hint_given`).
   - `record_attempt_event` rejects empty `work_submission` content.
   - Calling `commit_evidence` or `correct_evidence` with `independent_mastery` is rejected if a hint or solution preceded the submission.
   - Subpart metadata changes across correction cannot evade preceding assistance.
   - Work submitted *before* later assistance preserves independent mastery eligibility.

5. **Source Extraction Outside Database Transactions in ingest_source (Defect 5)**:
   - `ingest_source` stages immutable bytes into a quarantine copy and runs format extractors outside SQLite transactions (`assert not con.in_transaction`).
   - Fast atomic commit phase publishes staged bytes and records metadata and idempotency receipts.

6. **Reported Incomplete Retrieval and Preserved Review Status (Defect 6)**:
   - `expand_unit_dependencies` returns `ClosureResult` distinguishing `expansion_requested` from `closure_complete`, and records `unresolved_dependencies` and `missing_roots`.
   - `read_units` and `search` return `status`, `is_pending_review`, and uncertainty flags.

7. **Recoverable Restore Activation (Defect 7)**:
   - `restore_workspace` stages complete candidate in a sandbox and checks active database locks before activation.
   - Backs up previous workspace to a rollback directory before directory swap.
   - On activation failure, restores previous workspace completely with zero data loss.

8. **Efficiency Benchmark Labeled as Synthetic Heuristic (Defect 8)**:
   - Benchmark labeled as heuristic payload reduction on synthetic tasks.
   - Removed all claims of measured total cost or model token savings.

---

## 2. Exact Commands Executed and Verified

```bash
# 1. Environment & editable package installation
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2. Capabilities check
.venv/bin/lumen capabilities
# Output: {"status": "success", "data": {"contract_version": "1.0.0", "runtime": {"fts5_supported": true}, ...}}

# 3. Full automated test suite (51/51 passed)
.venv/bin/pytest -v
# Output: 51 passed in 2.10s

# 4. Standalone synthetic probability course demonstration
.venv/bin/python demo.py
# Output: All 11 demonstration steps succeeded with verified restore integrity!

# 5. Multi-turn efficiency benchmark test
.venv/bin/pytest tests/test_efficiency.py -s -v
# Output: 71.4% heuristic payload reduction across synthetic 6-turn task
```

---

## 3. Test Suite Breakdown

All 44 automated test cases in `tests/` pass cleanly:
- `tests/test_storage_and_integrity.py` (13 tests): F05, F06, F15, F16, F18, F19, F24, F25, restore fidelity, auto-cid retry, populated workspace protection, database source reference audit, complete dependency closure/cycle/cross-course/ambiguity.
- `tests/test_ingestion_and_retrieval.py` (8 tests): F01, F02/F26, F03, F04, F23, preamble condition preservation & pending review default, raw section persistence & enrichment workflow, realistic PDF/PPTX/Hebrew fixtures.
- `tests/test_tutoring_and_evidence.py` (12 tests): F07, F08, F09/F13, F10, F11, F12, F20, event-anchored evidence, strict booleans, duplicate evaluation rejection, solution correction boundary, diagnostic item attempt & scoring lifecycle.
- `tests/test_cli_and_e2e.py` (3 tests): CLI capabilities, error envelopes, and complete end-to-end course slice.
- `tests/test_scenarios_extended.py` (6 tests): F14, F17, F21, F22, F28, F29.
- `tests/test_efficiency.py` (2 tests): Single-operation payload measurements and 6-turn multi-turn interaction task benchmark.

---

## 4. Key Architectural Decisions & Storage Locations

1. **Python 3.14 Transaction Handling**:
   - Under `autocommit=True`, transactions started with `BEGIN IMMEDIATE;` are committed with `con.execute("COMMIT;")` and `con.execute("ROLLBACK;")`. `src/course_tutor/storage/db.py` uses SQLite `SAVEPOINT`s for safe nested transactions.
2. **Authoritative SQLite**:
   - SQLite (`lumen.db`) is the sole authoritative store. JSON is strictly an interchange format.
3. **Storage Hierarchy**:
   - `<workspace>/lumen.db`: SQLite database.
   - `<workspace>/originals/<hash[:16]>_<filename>`: Immutable source files and student attachments.
   - `<workspace>/staging/`: Upload quarantine directory.
4. **Key Modules**:
   - `src/course_tutor/cli.py`: Console entry point (`lumen`).
   - `src/course_tutor/api.py`: `LumenCore` facade coordinating idempotency receipts and transactions.
   - `src/course_tutor/storage/`: Database connection, versioned migrations, file store, repositories.
   - `src/course_tutor/ingestion/`: Format dispatch, quality checks, raw section extraction, semantic unit construction, agent enrichment.
   - `src/course_tutor/retrieval/`: FTS5 index, multilingual search, complete cycle-safe dependency closure.
   - `src/course_tutor/learning/`: Attempts, assistance enforcement, event-anchored evidence commits, mistake corrections.
   - `src/course_tutor/assessment/`: Diagnostic blueprints, item-level attempts and scoring, course brief.
   - `src/course_tutor/backup/`: Snapshot backup and restore with populated workspace safeguards and DB reference audit.

---

## 5. Review Targets for Codex Continuation

1. **Live Smoke Testing in Native Codex Session**: Run `lumen capabilities`, `lumen course-brief`, and `lumen search` from inside the Codex client environment.
2. **Further Question Authoring Workflows**: Build upon `validate_exercise_version` and `start_assessment_item_attempt` for interactive diagnostic creation.
