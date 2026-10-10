# Lumen — Canonical Verification Checklist

**Date**: 2026-10-10  
**Environment**: Linux / Python 3.14.8 & 3.10–3.14 CI / SQLite 3.51.2 (WAL & FTS5)  
**Status**: Authoritative verification contract for Lumen correctness, reliability, and concurrency.

---

## 1. Verification Categorization & Precedence

1. **Confirmed Defects Reproduced by Codex**:
   - `DEFECT-A`: Zero score accepted without evaluated evidence.
   - `DEFECT-B`: Validation approves concurrently edited question/solution/rubric.
   - `DEFECT-C`: Reaffirming unchanged attempt link erases valid score and reopens assessment.
   - `DEFECT-D`: Migration fails on legacy schema-v4 workspace containing duplicate attempt links.
2. **Existing Regression Cases (Must Keep Passing)**:
   - `REG-01`: Multi-connection scoring vs retraction serialization (M6 Defect 1 / F31).
   - `REG-02`: Unlinked diagnostic item scoring rejection & attempt exclusivity index (M6 Defect 2 / F32).
   - `REG-03`: Strict check schema validation (rejecting 'false', 'failed', 'pending', numbers) (M6 Defect 3 / F33).
   - `REG-04`: Timeline assistance preservation (earlier submission remains independent) (M6 Defect 4 / F34).
   - `REG-05`: Atomic assessment item startup preserving unowned assessments on error (M6 Defect 5 / F35).
   - `REG-06`: Exception-safe `LumenCore` init with zero lock/FD leaks and clean restore (M6 Defect 6 / F36).
   - `REG-F01-F30`: Storage, ingestion, retrieval, tutoring, backup/restore, and CLI failure fixtures.
3. **Additional Boundary & Lifecycle Risks Investigated**:
   - `RISK-01`: Assessment lifecycle parameter boundaries (invalid item orders: bool, float, str, <=0; blank learner IDs).
   - `RISK-02`: Cross-course boundaries on diagnostic blueprints and selected exercise versions.
   - `RISK-03`: Duplicate exercise versions in assessment creation.
   - `RISK-04`: Optimistic concurrency with `expected_revision` on `update_exercise_version`.
   - `RISK-05`: Preserved pre-migration backup table (`backup_v4_assessment_items`) during legacy migration.
4. **Deferred Product Features (Out of Current Scope)**:
   - Live multi-device synchronization (deferred).
   - Custom graphical chat client (deferred).
   - Hosted multi-user service / fleet (deferred).
   - OCR for scans without text layers (flagged with limitation, deferred).
   - Calibrated pass prediction probabilities (deferred).

---

## 2. Detailed Requirement & Verification Checklist

| ID | Category | Requirement / Expected Behavior | Relevant Edge Cases | Verification Test Command / Method | Status | Actual Result & Limitations |
|---|---|---|---|---|---|---|
| **DEFECT-A** | Confirmed Defect | Every confirmed score, including zero, requires applicable completed evaluation grounded in submitted work. Unevaluated work stays pending. | • Zero with no evidence<br>• Zero with retracted evidence<br>• Zero with pending-review evidence<br>• Zero with another attempt's evidence<br>• Zero with evaluated incorrect answer<br>• Positive score with valid evidence<br>• Rollback preserves prior score and history | `pytest tests/test_final_verification.py -k test_defect_a` | Verified | Enforced in `record_assessment_item_score`: `if not valid_evidence:` raises `ValidationError`. Zero score with evaluated incorrect work accepted. |
| **DEFECT-B** | Confirmed Defect | Validation attestation must identify exact question, solution, and rubric revision checked; reject stale attestations. | • Question edited before validation commits<br>• Solution edited concurrently<br>• Rubric edited concurrently<br>• Outdated `expected_revision`<br>• Stale `update_exercise_version`<br>• Unchanged revision validates cleanly | `pytest tests/test_final_verification.py -k test_defect_b` | Verified | `validate_exercise_version` accepts `expected_revision` and content identity; verifies state inside transaction; raises `StaleRevisionError` on concurrent modification. |
| **DEFECT-C** | Confirmed Defect | Reaffirming an unchanged attempt link via `link_assessment_item_attempt` is an idempotent no-op preserving score, history, evidence, and status. | • Same link before submission<br>• Same link after evaluation<br>• Same link after scoring<br>• Same link after correction<br>• Repeated calls with/without request ID<br>• Genuinely different link clears score | `pytest tests/test_final_verification.py -k test_defect_c` | Verified | In `link_assessment_item_attempt`: `if item.attempt_id == attempt_id:` returns reaffirmed receipt without clearing score or reopening assessment. |
| **DEFECT-D** | Confirmed Defect | Upgrade/recovery policy for legacy schema-v4 workspaces with duplicate attempt links: back up, audit conflicting links, quarantine to `pending_review`, allow Migration 005. | • Schema-v4 populated with duplicate attempt links<br>• Automatic pre-migration backup table<br>• Audit table `legacy_duplicate_attempt_links`<br>• Actionable structured error when requested<br>• Safe retry on interrupted migration<br>• `repair_legacy_duplicate_links` path | `pytest tests/test_final_verification.py -k test_defect_d` | Verified | `run_migrations` detects duplicates before Migration 005; backs up and quarantines active duplicates to `pending_review` with audit trail; creates unique index cleanly. |
| **REG-01** | Regression | Immediate write transaction serializes concurrent retractions and scoring; retractions revert scores to pending review. | Multi-connection SQLite with concurrent worker threads across Orderings A and B. | `pytest tests/test_boundary_repairs_concurrency.py -k test_defect1` | Verified | Passed (77/77 tests pass). |
| **REG-02** | Regression | Diagnostic item scoring strictly requires linked attempt; rejects foreign and practice attempts; enforces uniqueness. | Foreign attempt, practice attempt, unlinked item, relink audit trail. | `pytest tests/test_boundary_repairs_concurrency.py -k test_defect2` | Verified | Passed. |
| **REG-03** | Regression | Strict verification check schema: reject 'false', 'failed', 'pending', numbers; require boolean True or passing status enum. | String 'false', '0', 'pending', list of check names, dict with status enum. | `pytest tests/test_boundary_repairs_concurrency.py -k test_defect3` | Verified | Passed. |
| **REG-04** | Regression | Preceding assistance determines evaluation classification; subsequent assistance recorded as exposure without rewriting earlier score. | Submission event -> later hint request -> progress report. | `pytest tests/test_boundary_repairs_concurrency.py -k test_defect4` | Verified | Passed. |
| **REG-05** | Regression | Assessment item startup is atomic; validation precedes learner assignment; leaves unowned assessments unowned on failure. | Nonexistent item order (999) on unowned assessment followed by valid start by different learner. | `pytest tests/test_boundary_repairs_concurrency.py -k test_defect5` | Verified | Passed. |
| **REG-06** | Regression | `LumenCore` init releases lock and closes connections on failure; zero FD leaks; allows immediate forced restore. | Repeated corrupted workspace opens; file descriptor count tracking; restore activation. | `pytest tests/test_boundary_repairs_concurrency.py -k test_defect6` | Verified | Passed. |
| **RISK-01** | Risk / Invariant | Strict type validation for `item_order` (reject bool, float, str, <=0) and `learner_id` (reject empty, whitespace). | `item_order=True`, `item_order=-1`, `item_order=0`, `learner_id=""`. | `pytest tests/test_final_verification.py -k test_lifecycle_boundaries` | Verified | Explicit validation added in `start_assessment_item_attempt`, `link_assessment_item_attempt`, `record_assessment_item_score`. |
| **RISK-02** | Risk / Invariant | Cross-course boundaries enforced on assessment creation (blueprints and exercise versions). | Blueprint topics or exercise versions from Course B supplied to Course A. | `pytest tests/test_final_verification.py -k test_cross_course_and_duplicate` | Verified | `create_assessment` validates `blueprint["topic_ids"]` and `selected_exercise_version_ids` match course. |
| **RISK-03** | Risk / Invariant | Duplicate exercise versions rejected during assessment creation. | `selected_exercise_version_ids=[v1, v1]`. | `pytest tests/test_final_verification.py -k test_cross_course_and_duplicate` | Verified | Validated in `create_assessment`. |
| **RISK-04** | Risk / Invariant | Optimistic concurrency protection on `update_exercise_version` using `expected_revision`. | Mismatched `expected_revision` on exercise update. | `pytest tests/test_final_verification.py -k test_defect_b` | Verified | `update_exercise_version` checks `len(revision_history)+1 == expected_revision`. |
| **RISK-05** | Risk / Invariant | Migration backup preservation: raw snapshot preserved in SQLite table before legacy link repair. | Pre-migration table `backup_v4_assessment_items` populated before quarantine. | `pytest tests/test_final_verification.py -k test_defect_d` | Verified | Verified in pre-migration handler. |
