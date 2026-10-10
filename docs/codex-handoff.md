# Codex Review and Continuation Handoff — Lumen

**Date**: 2026-10-10  
**Repository**: `lumen`  
**Git Base**: Final verification pass following commit `f7fc924507cfc3378c95b405083d871c69d89758`  
**Author / Implementer**: Antigravity Assistant  
**Target Recipient**: OpenAI Codex (and continuing engineering agents)

---

## 1. Executive Summary & Verified Defect Resolutions

In response to Codex's independent review of baseline commit `f7fc924507cfc3378c95b405083d871c69d89758`, all 4 identified defects (Defect A, Defect B, Defect C, Defect D) and related lifecycle boundary conditions have been repaired and verified across 77 automated tests (including 10 dedicated verification tests in `tests/test_final_verification.py`), the CLI capability inspector, and the synthetic probability demo.

### Fourth-Round Final Verification Defect Fixes Implemented

1. **Defect A: Zero Score Without Evaluated Active Evidence Accepted as Scored**:
   - `record_assessment_item_score` now strictly requires applicable active evaluated evidence for any confirmed score, including zero points awarded (`if not valid_evidence:`).
   - Unevaluated submissions remain `unassessed` or `pending_review` with assessment status remaining `open`.
   - Scoring attempts with retracted, pending, foreign, or empty evidence are rejected with `ValidationError` while leaving prior item and assessment state untouched.
   - Genuine evaluated incorrect work (`demonstrated_level == "incorrect"`) correctly supports a confirmed zero score.

2. **Defect B: Validation Approves Concurrently Edited Question/Solution/Rubric**:
   - `validate_exercise_version` accepts `expected_revision`, `expected_question_text`, `expected_reference_solution`, `expected_rubric`, and `expected_content_hash`.
   - Re-checks exercise version state both before and inside the write transaction. If question text, solution, rubric, or revision counter changed concurrently, raises `StaleRevisionError` or `ValidationError`.
   - Added `compute_exercise_version_hash` and optimistic revision guarding to `update_exercise_version`. Provenance records checked revision and content hash.

3. **Defect C: Reaffirming Unchanged Attempt Link Erases Valid Score and Reopens Assessment**:
   - In `link_assessment_item_attempt`: if the assessment item is already linked to the target attempt (`item.attempt_id == attempt_id`), reaffirming the link is an idempotent no-op.
   - Returns a reaffirmed receipt (`reaffirmed=True`) without clearing awarded points, resetting `score_status`, or reopening a completed assessment.
   - Genuinely different attempt links still clear the prior score, reopen the assessment, and log an audit trail entry in `score_history`.

4. **Defect D: Migration Fails on Legacy Schema-v4 Workspace with Duplicate Attempt Links**:
   - In `run_migrations`: pre-migration detection inspects `assessment_items` before Migration 005 applies `CREATE UNIQUE INDEX idx_assessment_items_unique_attempt`.
   - Safely creates `backup_v4_assessment_items` preserving original rows byte-for-byte.
   - Populates audit table `legacy_duplicate_attempt_links` and quarantines conflicting active links (`attempt_id=NULL`, `score_status='pending_review'`), logs audit history entries, and safely reopens affected assessments.
   - If `auto_quarantine_duplicates=False`, raises actionable structured error `LegacyDuplicateAttemptLinkError`.
   - Added `repair_legacy_duplicate_links` core method and CLI command (`lumen repair-legacy-duplicate-links`) to inspect and resolve quarantined links.

5. **Lifecycle Boundaries and Invariants (RISK-01 – RISK-05)**:
   - Validated `item_order` (strict `int`, rejecting `bool`, `float`, `<= 0`) and `learner_id` (non-empty string) across assessment workflows.
   - Cross-course validation prevents attaching exercise versions or blueprint topics from external courses.
   - Duplicate exercise versions in assessment creation are rejected.
   - Assistance chronology verifies that post-submission assistance does not overwrite earlier independent work and records `assistance_after_submission: True`.

### Prior Defect Fixes Retained (from Commits 733e738, bd7c52b, and f7fc924)

- Scoring/retraction race serialization in `atomic_transaction` (BEGIN IMMEDIATE).
- Unlinked item scoring rejection and attempt exclusivity.
- Strict verification check schema (rejecting 'false', 'failed', 'pending', numbers).
- Timeline assistance preservation and mixed subparts reporting.
- Atomic assessment item startup preserving unowned assessments on error.
- Exception-safe `LumenCore` init with zero lock/FD leaks and clean restore.
- Python compatibility across supported versions (3.10–3.14).
- Subpart assistance bypass prevention.
- Topic-state recomputation from invalidated evidence.
- External restore synchronization via `fcntl.flock` outside the workspace directory.

---

## 2. Exact Commands Executed and Verified

```bash
# 1. Environment & editable package installation
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2. Capabilities check
.venv/bin/lumen capabilities
# Output: {"status": "success", "data": {"contract_version": "1.0.0", "runtime": {"fts5_supported": true}, ...}}

# 3. Full automated test suite (77/77 passed)
.venv/bin/pytest -v
# Output: 77 passed in 2.76s

# 4. Standalone synthetic probability course demonstration
.venv/bin/python demo.py
# Output: All 11 demonstration steps succeeded with verified restore integrity!

# 5. Multi-turn efficiency benchmark test
.venv/bin/pytest tests/test_efficiency.py -s -v
# Output: 71.4% heuristic payload reduction across synthetic 6-turn task
```

---

## 3. Test Suite Breakdown

All 77 automated test cases pass cleanly:
- `tests/test_final_verification.py` (10 tests):
  - Defect A: Zero score strictly requires active evaluated evidence; unevaluated work stays pending.
  - Defect A: Rollback state preservation on rejected scores.
  - Defect B: Question validation rejects concurrently edited question text, solutions, and rubrics.
  - Defect B: Solution and rubric changes require exact expected revision.
  - Defect C: Reaffirming unchanged attempt link is an idempotent no-op preserving points, evidence, history, and status.
  - Defect D: Legacy schema-v4 workspace migration detects duplicate attempt links, creates backup table `backup_v4_assessment_items`, logs audit table `legacy_duplicate_attempt_links`, quarantines to `pending_review`, and allows repair.
  - Lifecycle boundaries: `item_order` strict integer type checking and non-empty `learner_id`.
  - Cross-course and duplicate assessment creation prevention.
  - Assistance chronology: post-submission assistance does not overwrite earlier independent work and records `assistance_after_submission: True`.
  - CLI update and repair commands.
- `tests/test_boundary_repairs_concurrency.py` (8 tests):
  - Multi-connection concurrency between scoring and retraction (Orderings A and B).
  - Unlinked item scoring rejection, cross-attempt isolation, attempt exclusivity (Migration 005), and relink audit.
  - Strict verification check schema (rejection of 'false', 'failed', 'pending', numbers) and finite score validation.
  - Assistance timeline and mixed subparts.
  - Failed item startup preserving unowned assessments.
  - Exception-safe LumenCore initialization releasing locks and file descriptors, allowing immediate restore.
  - File descriptor leak prevention on repeated initialization failures.
  - Idempotency replay, conflict detection on mismatched intents, and revision protection.
- `tests/test_storage_and_integrity.py` (13 tests): F05, F06, F15, F16, F18, F19, F24, F25, restore fidelity, auto-cid retry, populated workspace protection, database source reference audit, complete dependency closure/cycle/cross-course/ambiguity.
- `tests/test_ingestion_and_retrieval.py` (8 tests): F01, F02/F26, F03, F04, F23, preamble condition preservation & pending review default, raw section persistence & enrichment workflow, realistic PDF/PPTX/Hebrew fixtures.
- `tests/test_tutoring_and_evidence.py` (12 tests): F07, F08, F09/F13, F10, F11, F12, F20, event-anchored evidence, strict booleans, duplicate evaluation rejection, solution correction boundary, diagnostic item attempt & scoring lifecycle.
- `tests/test_cli_and_e2e.py` (3 tests): CLI capabilities, error envelopes, and complete end-to-end course slice.
- `tests/test_scenarios_extended.py` (6 tests): F14, F17, F21, F22, F28, F29.
- `tests/test_efficiency.py` (2 tests): Single-operation payload measurements and 6-turn multi-turn interaction task benchmark.
- `tests/test_verified_defect_repairs.py` (15 tests):
  - Defect 1: Require observed, validated work before awarding scores.
  - Defect 2: Synchronize assessment scores with evidence retractions/corrections.
  - Defect 3: Remove automatic exercise validation throughout public interface.
  - Defect 4: Close evidence and assistance bypasses in LearningService.
  - Defect 5: Perform source file staging, hashing, and extraction completely outside database transactions.
  - Defect 6: Report incomplete retrieval and preserve pending review status.
  - Defect 7: Recoverable restore activation with active database lock check.
  - Codex Defect 1: Python compatibility type hints (`Union`, `ExtractedSection`).
  - Codex Defect 2: Subpart assistance bypass prevention.
  - Codex Defect 3: Assessment scoring binding and deduplicated scoring history.
  - Codex Defect 4: Recheck question validation when scoring.
  - Codex Defect 5: Exercise validation atomic checks and revision snapshots.
  - Codex Defect 6: Topic-state recomputation from invalidated evidence rows.
  - Codex Defect 7: Restore synchronization and detached handle detection.
  - Codex Defect 8: Assessment coverage separation (`topic_coverage` vs `course_topic_coverage`).

---

## 4. Key Architectural Decisions & Storage Locations

1. **Python 3.14 Transaction Handling**:
   - Under `autocommit=True`, transactions started with `BEGIN IMMEDIATE;` are committed with `con.execute("COMMIT;")` and `con.execute("ROLLBACK;")`. `src/course_tutor/storage/db.py` uses SQLite `SAVEPOINT`s for safe nested transactions.
2. **Authoritative SQLite**:
   - SQLite (`lumen.db`) is the sole authoritative store. JSON is strictly an interchange format.
3. **Workspace File Synchronization**:
   - Synchronization lock files are placed at `workspace.parent / f".{workspace.name}.sync"` to survive directory rename and swap operations during backup restoration.
   - `WorkspaceDetachedError` protects sessions whose underlying SQLite files were replaced or detached by an external process.
4. **Storage Hierarchy**:
   - `<workspace>/lumen.db`: SQLite database.
   - `<workspace>/originals/<hash[:16]>_<filename>`: Immutable source files and student attachments.
   - `<workspace>/staging/`: Upload quarantine directory.
   - `<workspace.parent>/.<workspace.name>.sync`: External synchronization lock file.
