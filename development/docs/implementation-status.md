# Lumen — Implementation Status Report

**Status Date**: 2026-10-19
**Environment**: Linux / Python 3.14.8 / SQLite 3.51.2 (FTS5 enabled). Other Python versions have a CI configuration, not new run evidence from this audit.
**Current status**: The shared core is implemented. The latest local suite passed
**273 tests** on 2026-10-19; the prior CI/profile cleanup passed 205. See the
[current release tracker](release-readiness.md) for completed work, evidence and
remaining gates. Automatic local Codex collection has been exercised against
eight project-matched sessions; counters are host-reported and billed costs remain
unknown. Native Claude/Antigravity CLI callbacks and Claude transcript discovery
are implemented. Antigravity CLI 1.4.2 passed a real headless usage run and a
resumed TUI callback check; Claude fixtures pass but its executable is unavailable.
Usage JSONL logging, draft-only releases, a friend-ready Claude
protocol, and 16 generated reviewed educational cases are now implemented.

Earlier [Antigravity integration/fresh-session resume](reports/antigravity-integration-report.md)
and [real-course Codex visual review](reports/real-course-integration-report.md) have
bounded live evidence. The [organized extraction simulation](reports/course-extraction-simulation-report.md)
passed 197 tests at its audit: DOCX equations, independent visual gates, duplicate
aliases, source metadata/solution links, question history and grade corrections.
It retains 45 appearances across two courses, four reviewed algorithms questions,
and a visually checked three-question Hebrew/KaTeX practice PDF.

Live Claude execution, real cross-host handover, independent unseen educational
review and complete per-call usage/billing collection remain open. Preparation and local
fixtures do not close those gates. The new features do not have a new Antigravity
run. Milestone rows below retain historical test counts and implementation scope;
[release readiness](release-readiness.md) owns the current completion decision.

---

## 1. Milestone Matrix

| Milestone | Status | Key Deliverables & Code Artifacts | Test & Validation Evidence |
|---|---|---|---|
| **M0 — Shared Contract & Discovery** | **Complete** | • `pyproject.toml` (package `lumen`, Python `>=3.10`)<br>• Structured CLI `src/course_tutor/cli.py`<br>• Capability reporter `src/course_tutor/capabilities.py`<br>• Host loaders (`AGENTS.md`, `CLAUDE.md`, `.agents/skills/lumen/SKILL.md`, `.codex/`) | `tests/test_cli_and_e2e.py` (3 tests passing):<br>• capabilities, error envelopes, full CLI e2e workflow |
| **M1 — Reliable Storage & Originals** | **Complete** | • Recovered tracked storage implementation (`src/course_tutor/storage/`)<br>• Anchored `.gitignore` to track package sources<br>• Versioned migrations `src/course_tutor/storage/migrations.py` (v1 + v2 `source_sections`)<br>• SQLite connection manager `src/course_tutor/storage/db.py`<br>• Content-addressed file store `src/course_tutor/storage/file_store.py`<br>• Entity repositories `src/course_tutor/storage/repositories.py`<br>• Backup/Restore `src/course_tutor/backup/` with populated workspace protection and DB file audit | `tests/test_storage_and_integrity.py` (13 tests passing):<br>• F05, F06, F15, F16, F18, F19, F24, F25, restore fidelity, auto-cid retry, populated guard, DB file audit, full closure |
| **M2 — Ingestion & Retrieval** | **Complete** | • Format extractors `src/course_tutor/ingestion/extractors.py` (Text, PDF via `pypdf`, PPTX via `python-pptx`)<br>• File extraction executed outside DB transaction locks<br>• Preamble and surrounding condition preservation with assumption parsing<br>• Auto-extracted units defaulted to `pending_review`<br>• Agent enrichment workflow: `enrich_source_version` & `get_extracted_sections`<br>• Realistic PDF, PPTX, and Hebrew fixtures (`examples/synthetic_probability/materials/`)<br>• Complete cycle-safe dependency closure without depth truncation (`expansion.py`)<br>• Cross-course rejection & ambiguous title detection<br>• FTS5 search & BM25 with topic aliases | `tests/test_ingestion_and_retrieval.py` (8 tests passing):<br>• F01 (scanned page limitation)<br>• F02/F26 (assumption preservation)<br>• F03 (Hebrew/English aliases)<br>• F04 (source revisions)<br>• F23 (missing syllabus content)<br>• Preamble condition preservation & pending review default<br>• Raw section persistence & enrichment workflow<br>• Realistic PDF/PPTX/Hebrew fixtures |
| **M3 — Tutor Evidence & Corrections** | **Complete** | • Attempt lifecycle & revision tracking `src/course_tutor/learning/service.py`<br>• Event-anchored evaluation tied to committed submission event<br>• Assistance after submission does not downgrade prior independent work<br>• Strict boolean parsing (`parse_bool`) rejecting ambiguous representations<br>• Duplicate active evaluation rejection preventing inflation<br>• Tutor correction prohibited from awarding independent mastery if solution was revealed<br>• Evidence retraction & deterministic state rebuild | `tests/test_tutoring_and_evidence.py` (12 tests passing):<br>• F07 (assisted performance after solution)<br>• F08 (paused untouched subparts unassessed)<br>• F09/F13 (arithmetic partial progress)<br>• F10 (question family exposure)<br>• F11 (mistake retraction and rebuild)<br>• F12 (unvalidated question rejection)<br>• F20 (cross-session resume)<br>• Submission anchoring<br>• Strict booleans<br>• Duplicate rejection<br>• Solution correction boundary<br>• Diagnostic item attempt & scoring |
| **M4 — Diagnostics & Practice Selection** | **Complete** | • Blueprint-driven diagnostics `src/course_tutor/assessment/diagnostic.py`<br>• Validation enforcement (rejection of unvalidated/contradictory items)<br>• Public path for item attempts and scores: `start_assessment_item_attempt`, `record_assessment_item_score`<br>• Transparent denominators reporting observed rubric points on attempted items without penalizing unattempted items as failures<br>• Actionable recommendations in `course_brief` | `tests/test_tutoring_and_evidence.py::test_f12_diagnostic_rejects_unvalidated_questions`<br>`tests/test_tutoring_and_evidence.py::test_assessment_scoring_lifecycle_and_transparent_reporting`<br>`tests/test_scenarios_extended.py::test_f21_weak_topic_practice_does_not_mask_untested_coverage`<br>`tests/test_scenarios_extended.py::test_f22_exam_without_official_solution_flagged_pending_review` |
| **M5 — Conformance & Efficiency Verification** | **Partial: live-host and measured evaluation gates open** | • Three-host integration test suite in `tests/test_three_host_conformance.py` (4 tests passing)<br>• Sequential multi-host workspace handover: Antigravity -> Codex -> Claude Code<br>• Complete multi-turn task benchmark in `tests/test_efficiency.py` (brief, search, expansion, reading, attempt, receipt)<br>• Declared token estimator heuristic (~4 chars/token)<br>• Standalone synthetic probability course demo `demo.py`<br>• Static host-loader configuration checks for Codex, Claude, and Antigravity | All 103 tests pass cleanly in 3.47s.<br>`demo.py` executes all workflows cleanly.<br>Multi-turn benchmark confirms 71.4% context reduction across complete 6-turn task vs naive full-source re-injection.<br>Environment-marker conformance is simulated; live host verification remains separate. |
| **M6 — Correctness & Reliability Repair Pass** | **Complete** | • Concurrency serialization between scoring and retraction in `atomic_transaction`<br>• Attempt exclusivity: Migration 005 partial unique index on non-null `attempt_id`<br>• Explicit `link_assessment_item_attempt` and audit history on relinking<br>• Strict verification check schema (rejecting 'false', 'failed', 'pending', numbers)<br>• Finite points validation and strict boolean parsing<br>• Timeline-aware assistance classification (`assistance_after_submission` & mixed subparts)<br>• Atomic assessment item attempt startup preserving unowned assessments on error<br>• Exception-safe initialization in `LumenCore` with zero FD leaks and clean restore<br>• Safe `_check_db_not_locked` handling corrupt databases for forced restore<br>• GitHub Actions CI workflow matrix (`.github/workflows/ci.yml`) covering Python 3.10–3.14 | `tests/test_boundary_repairs_concurrency.py` (8 tests passing):<br>• Multi-connection scoring/retraction concurrency (Orderings A & B)<br>• Unlinked attempt rejection & attempt exclusivity<br>• Relink audit trail in score history<br>• Strict checks validation schema<br>• Finite score validation<br>• Timeline assistance and mixed subparts<br>• Atomic startup and unowned assessment preservation<br>• Exception-safe lock release, zero FD leaks, and restore recovery |
| **M7 — Final Verification & Defect Pass** | **Complete** | • Confirmed score requiring active evaluated evidence for any score, including zero (Defect A)<br>• Exercise validation identifies and checks exact revision and content hash identity (Defect B)<br>• Idempotent attempt link reaffirmation preserving points, evidence, and status (Defect C)<br>• Schema v4 pre-migration backup table (`backup_v4_assessment_items`), audit table (`legacy_duplicate_attempt_links`), quarantine to `pending_review`, and repair path (Defect D)<br>• Lifecycle boundary invariants: item order type checking, non-empty learner IDs, cross-course and duplicate assessment creation prevention | `tests/test_final_verification.py` (10 tests passing):<br>• Zero score with/without evidence<br>• Rollback state preservation<br>• Exact revision question/rubric validation<br>• Idempotent link reaffirmation<br>• Legacy schema v4 migration & quarantine<br>• Lifecycle boundaries (item_order, learner_id)<br>• Cross-course and duplicate assessments<br>• Assistance chronology and exposure preservation<br>• CLI update and repair commands |
| **M8 — Complete Reliability & Security Repair Pass** | **Complete** | • Strict evidence-level schema; observation levels excluded from confirmed scores (Defect 1)<br>• Persistent educational revision & content hash identity via Migration 006; rejection of outdated submission evaluation and item scoring (Defect 2)<br>• Mandatory caller-side validation identity (`expected_revision` or `expected_content_hash`) (Defect 3)<br>• Validation provenance recording final attested revision and hash (Defect 4)<br>• Strict verification check schema validation and conflict rejection (Defect 5)<br>• Caller-supplied learner ID ownership verification in attempt linking (Defect 6)<br>• Idempotent link reaffirmation and safe legacy repair (Defect 7)<br>• CLI argument forwarding and non-object JSON validation (exit code 1) (Defect 8)<br>• Sandboxed restore path resolution rejecting Zip Slip, symlinks, absolute paths, and traversal (Defect 9) | `tests/test_nine_defect_repairs.py` (10 tests passing):<br>• Defect 1: Observation levels rejected for scores; subpart completeness<br>• Defect 2: Outdated submission and evidence revision rejection<br>• Defect 3: Mandatory caller-side validation identity<br>• Defect 4: Final attested candidate revision and content hash in provenance<br>• Defect 5: Contradictory structured checks rejected<br>• Defect 6: Caller learner ID ownership verification<br>• Defect 7: Idempotent legacy repair reaffirmation<br>• Defect 8: CLI argument forwarding and exit code 1 validation<br>• Defect 9: Sandboxed restore rejecting Zip Slip and traversal<br>• Migration 006: Schema upgrade to v6 with revision & hash columns |
| **M9 — Underlying Invariants Repair Pass** | **Complete** | • Migration 007 legacy identity resolution on unedited questions, quarantine on modified questions (`backup_v6_*`, `resolve_and_quarantine_legacy_identities`) & strict commit rejection (Defect 1)<br>• Obsolete/unresolved evidence cannot revive to active for current performance; `correct_evidence` creates replacement with `pending_review` status; projections (`recompute_topic_state`, `course_brief`, progress reports) exclude obsolete evidence (Defect 2)<br>• Observation evidence (`unassessed`, `pending`, `uncertain`, `unreadable`) excluded from assessed coverage; only active, eligible, evaluated evidence sets topic coverage `assessed: true` (Defect 3)<br>• Incomplete subpart evaluation cannot complete an entire question (`score_status="scored"`); required subpart completeness strictly enforced; partial scores without complete subparts require `allow_partial=True`, receive `score_status="partially_scored"`, and leave assessment `status="open"` (Defect 4)<br>• Stale legacy repair on already-resolved quarantine records rejected with `ConflictError`; `expected_link_states` supported; overwriting active scored links without explicit expectation rejected with `ConflictError` (Defect 5)<br>• Finite numeric validation (numeric >= 0, reject booleans, NaN, Inf) in verification checks and metadata; CLI rejects non-standard JSON constants (`NaN`, `Infinity`) with exit code 1; CLI outputs strictly valid JSON (`allow_nan=False`) (Defect 6) | `tests/test_underlying_invariants_repairs.py` (6 tests passing):<br>• Defect 1: Legacy identity resolution, backup, and quarantine<br>• Defect 2: Corrections on obsolete evidence stay pending<br>• Defect 3: Observation evidence excluded from assessed coverage<br>• Defect 4: Subpart completeness and partial scoring lifecycle<br>• Defect 5: Stale legacy repair and expected link states<br>• Defect 6: Finite numeric checks and CLI payload enforcement |
| **M10 — Provenance Chain & Scoring Invariant Repairs** | **Complete** | • Evidence eligibility across entire provenance chain (evidence, attempt, submission event, learner ownership, current exercise version) via `check_evidence_eligibility_chain` applied consistently across scoring, corrections, projections, coverage, and reports<br>• Migration 008 (`backup_v7_*`, score revalidation, evidence quarantine, and inside-transaction projection rebuilding)<br>• Subpart completeness and strict boolean `allow_partial`<br>• Consistent zero-score enforcement (requires evaluated incorrect work, rejects zero with all-positive evidence)<br>• Stale attempt resumption rejection in `resume_attempt` and omission from `course_brief` recommendations<br>• Pre-execution non-finite numeric validation (`validate_all_finite_numbers`) and pre-commit response serialization validation (`allow_nan=False`) | `tests/test_provenance_and_scoring_invariants.py` (6 tests passing):<br>• Provenance chain eligibility across scoring, coverage, and projections<br>• Migration 008 score revalidation, subpart completeness, and reopening<br>• Migration 008 inside-transaction topic state projection rebuilding<br>• Strict scoring rules: non-bool rejection, full-credit subpart protection, zero-score enforcement<br>• Stale attempt resumption rejection and course brief filtering<br>• Non-finite JSON rejection before DB mutation or receipt creation |
---

## 2. Failure Scenarios Coverage (F01–F62)

| ID | Failure Fixture Scenario | Implemented Behavior & Verification | Test Case |
|---|---|---|---|
| **F01** | OCR drops symbol or page is scanned | Scanned page without text layer flagged with `uncertain_scanned`; limitation notes recorded; never claims silent success. | `test_f01_scanned_pdf_page_flagged_with_limitation` |
| **F02** | Summary omits independence condition | Retrieval returns full unit with all required mathematical assumptions, symbols, and dependencies. | `test_f02_f26_retrieval_preserves_full_mathematical_assumptions` |
| **F03** | Hebrew/English aliases differ | FTS5 + topic aliases table resolve queries in Hebrew ("הסתברות מותנית") and English. | `test_f03_multilingual_topic_alias_retrieval` |
| **F04** | Source answer or content changes | Increments version number; preserves immutable historical versions with full locators. | `test_f04_source_versioning_and_provenance` |
| **F05** | Identical bytes under different filename | Reuses content hash identity; avoids duplicate knowledge unit explosion. | `test_f05_identical_bytes_different_filename` |
| **F06** | Same filename with different bytes | Creates new immutable source version; preserves both historical versions and hashes. | `test_f06_same_filename_different_bytes` |
| **F07** | Correct answer follows revealed solution | Classified as `assisted_success`, never independent mastery. | `test_f07_correct_answer_after_solution_classified_as_assisted` |
| **F08** | Learner pauses after one subpart | Completed subpart evidence committed; untouched parts remain strictly unassessed. | `test_f08_pause_preserves_subpart_evidence_untouched_unassessed` |
| **F09** | Correct method, arithmetic mistake | Method evidence preserved as `partial_progress`; error category recorded as `arithmetic`. | `test_f09_f13_partial_credit_for_arithmetic_error` |
| **F10** | Repeated question variants attempted | Tracks `exposure_count` per exercise family; avoids fabricating diverse mastery. | `test_f10_repeated_family_exposure_tracked` |
| **F11** | Tutor marks valid solution wrong | `correct_evidence` supersedes invalid record and recomputes topic state without erasing history. | `test_f11_tutor_correction_retracts_and_recomputes_state` |
| **F12** | Contradictory question submitted | Diagnostic creation raises `UnvalidatedQuestionError`; state updates withheld. | `test_f12_diagnostic_rejects_unvalidated_questions` |
| **F13** | Multiple skills with mixed outcomes | Evidence committed per skill and subpart independently. | `test_f09_f13_partial_credit_for_arithmetic_error` |
| **F14** | Unreadable student submission | Ambiguous input flagged; evidence remains unassessed pending clarification. | `test_f14_unreadable_submission_remains_pending` |
| **F15** | Retry with same request ID | Returns previous receipt without duplicate database execution. | `test_f15_idempotent_retry_returns_prior_receipt` |
| **F16** | Same request ID with conflicting content | Raises explicit `IdempotencyConflictError`. | `test_f16_reusing_request_id_with_different_content_conflicts` |
| **F17** | Interrupted write / commit crash | Atomic transaction with immediate lock / savepoint rolls back on failure; mutation and receipt commit atomically. | `test_f17_transactional_rollback_preserves_consistency` |
| **F18** | Stale attempt revision submitted | Optimistic concurrency check raises `StaleRevisionError`. | `test_f18_stale_revision_conflict` |
| **F19** | Exercise ID belongs to another course | Cross-course boundary validation raises `CrossCourseViolationError`. | `test_f19_cross_course_violation` |
| **F20** | Session resume / host switch | `course_brief` loads open attempt and revision directly without full conversation history. | `test_f20_session_resume_without_full_transcript` |
| **F21** | Repeated practice on weak topics | Diagnostic blueprint and course brief expose untested topics clearly. | `test_f21_weak_topic_practice_does_not_mask_untested_coverage` |
| **F22** | Exam without official solution | Flagged as `pending_review`; cannot alter formal diagnostic assessment. | `test_f22_exam_without_official_solution_flagged_pending_review` |
| **F23** | Syllabus topic lacks materials | Reported as `topics_missing_materials` in course brief. | `test_f23_course_brief_exposes_missing_syllabus_content` |
| **F24** | Source hash mismatch | Tampered or modified source raises `SourceCorruptedError` during hash check. | `test_f24_source_corruption_detection` |
| **F25** | Backup archive omits source files | `restore_workspace` fails validation and raises `RestoreIntegrityError`. | `test_f25_backup_restore_missing_source_fails` |
| **F26** | Unit budget truncation probe | Complete mathematical unit assumptions and symbols preserved or expanded; never truncated. | `test_f02_f26_retrieval_preserves_full_mathematical_assumptions` |
| **F27** | Host instruction discovery | Native entry points verified for Codex (`AGENTS.md`), Claude (`CLAUDE.md`), Antigravity. | Verified in host configurations. |
| **F28** | Host cannot display images | Capability check explicitly advertises `ocr_scans: false`, `visual_source: host_dependent`. | `test_f28_visual_source_capability_advertised` |
| **F29** | Workspace recreated without data | New workspace initializes cleanly with zero fabricated prior progress. | `test_f29_empty_workspace_does_not_fabricate_prior_progress` |
| **F30** | Persistence unavailable | Operation receipts are only issued upon successful database commit. | Covered by `OperationReceipt` commit guarantees. |
| **F31** | Scoring races with evidence retraction | Protect checks and writes in immediate transaction; reject score if retracted, or revert score to pending review on subsequent retraction. | `test_defect1_concurrency_scoring_races_with_retraction` |
| **F32** | External/unlinked attempt supplied to scoring | Reject unlinked attempt; enforce item-to-attempt linkage, exercise version match, learner ownership, and attempt uniqueness (Migration 005). | `test_defect2_unlinked_items_and_attempt_exclusivity` |
| **F33** | Ambiguous strings or numbers passed as verification checks | Strictly reject 'false', 'failed', 'pending', numbers, and containers; require boolean True or passing structured check state enum. | `test_defect3_strict_verification_checks_and_points` |
| **F34** | Assistance requested after independent submission | Maintain independent classification for earlier evaluated submission; record subsequent assistance as exposure without rewriting score. | `test_defect4_assistance_timeline_and_subparts` |
| **F35** | Failed item startup on unowned assessment | Keep ownership assignment, validation, and linking atomic; leave assessment unowned when startup raises ValidationError. | `test_defect5_failed_startup_preserves_unowned_assessment` |
| **F36** | Initialization failure in workspace session | Exception-safe cleanup releases locks, closes connections, and leaves zero descriptor leaks, enabling immediate restore. | `test_defect6_failed_init_releases_lock_and_allows_restore`<br>`test_defect6_no_file_descriptor_leak_on_repeated_init_failures` |
| **F37** | Zero score without active evaluated evidence | Scoring strictly requires active evaluated evidence for any confirmed score, including zero; unevaluated work stays pending. | `test_defect_a_zero_score_requires_evaluated_evidence`<br>`test_defect_a_rejected_score_preserves_prior_state` |
| **F38** | Validation approves concurrently edited question | Validation attestation identifies exact question/solution/rubric revision and content identity; rejects stale attestations. | `test_defect_b_validation_rejects_concurrently_edited_question`<br>`test_defect_b_solution_and_rubric_changes_require_exact_revision` |
| **F39** | Reaffirming unchanged attempt link erases score | Reaffirming unchanged link is an idempotent no-op preserving points, evidence, history, and completion status. | `test_defect_c_reaffirming_link_preserves_score_and_completion` |
| **F40** | Migration on schema-v4 workspace with duplicate attempt links | Pre-migration detection backs up to `backup_v4_assessment_items`, audits duplicates into `legacy_duplicate_attempt_links`, quarantines to `pending_review`, and allows clean Migration 005. | `test_defect_d_legacy_migration_with_duplicate_attempt_links` |
| **F41** | Observation evidence level submitted for confirmed assessment score | Reject confirmed score; enforce strict evidence schema; require evaluated evidence; never report unassessed work as assisted. | `test_defect1_observation_levels_rejected_for_confirmed_scores` |
| **F42** | Submission evaluated after exercise replacement or content change | Persist revision/hash on attempts & evidence (Migration 006); reject evaluating old submission or scoring using outdated evidence. | `test_defect2_submission_reuse_rejected_after_exercise_replacement` |
| **F43** | Question validation called without caller-side identity | Reject validation without caller identity; mandate positive integer `expected_revision` or non-empty `expected_content_hash`. | `test_defect3_exact_revision_mandatory_in_validation` |
| **F44** | Question validation provenance records stale pre-update values | Provenance records final attested revision and content hash in provenance, atomically committed with snapshot history. | `test_defect4_validation_provenance_records_final_attested_content_and_history` |
| **F45** | Contradictory structured verification checks submitted | Strict schema: reject conflicting status/state, disallowed keys, duplicate check names, and failing/pending statuses. | `test_defect5_contradictory_and_invalid_structured_checks_rejected` |
| **F46** | Caller-supplied learner ID in linking mismatches attempt owner | Verify caller learner ID matches attempt owner; reject attempt ownership overrides. | `test_defect6_caller_supplied_learner_id_verified_against_attempt_owner` |
| **F47** | Repeated legacy repair reaffirms unchanged attempt link | Reaffirmation is an idempotent no-op preserving points, evidence, history, and completed assessment state. | `test_defect7_repeated_legacy_repair_idempotent_and_safe_relink` |
| **F48** | CLI operation omits API parameters or receives malformed payload | Forward `submission_event_id`; reject non-object JSON with code 1; detect conflicting CLI options vs payload parameters. | `test_defect8_cli_forwards_submission_event_id_and_validates_payload` |
| **F49** | Restore archive contains Zip Slip, symlink, absolute path, or traversal | Sandboxed path resolution strictly rejects traversal, symlinks, absolute paths in archive and manifest. | `test_defect9_restore_path_traversal_and_zip_slip_rejection` |
| **F50** | Legacy workspace contains NULL identity attempts/evidence | Migration 007 resolves unedited questions, creates `backup_v6_*`, quarantines modified question items to `pending_review`, and reopens assessments. | `test_defect1_legacy_identity_resolution_and_quarantine` |
| **F51** | Correction attempted on obsolete or unresolved evidence | Replacement is stamped `pending_review` with historical rationale; topic state recomputation and brief exclude obsolete evidence. | `test_defect2_correction_on_obsolete_evidence_stays_pending` |
| **F52** | Observation evidence submitted for topic coverage | Observation evidence excluded from assessed coverage; topic state and course brief retain `assessed: false` / unassessed status. | `test_defect3_observation_evidence_excluded_from_assessed_coverage` |
| **F53** | Incomplete subpart evaluation submitted for full scoring | Reject scoring without complete subparts; with `allow_partial=True`, assign `partially_scored` and leave assessment status `open`. | `test_defect4_subpart_completeness_and_partial_scoring` |
| **F54** | Stale legacy repair or uncoordinated link overwrites | Reject already-resolved quarantine repairs with `ConflictError`; reject overwriting active scored links without explicit `expected_link_states`. | `test_defect5_stale_legacy_repair_and_expected_link_states` |
| **F55** | Non-finite numbers or JSON constants in checks or CLI | Reject NaN, Inf, booleans in check score; reject non-finite nested metadata; CLI rejects `NaN`/`Infinity` constants with exit code 1. | `test_defect6_finite_numeric_checks_and_cli_payload` |
| **F56** | Outdated or ineligible provenance chain submitted for scoring, classification, coverage, or recommendations | Verify entire chain (evidence, attempt, submission event, learner ownership, current exercise version); exclude ineligible evidence from classification, coverage, and course brief. | `test_reproduction_1_evidence_eligibility_across_provenance_chain` |
| **F57** | Historical workspace has invalid scores from earlier schema versions | Migration 008 creates `backup_v7_*` tables, revalidates historical scores against complete current policy, quarantines invalid scores to `pending_review` with audit history, and reopens affected assessments. | `test_reproduction_2_historical_subpart_and_observation_scores_quarantined` |
| **F58** | Historical workspace has outdated topic projections after upgrade | Migration 008 rebuilds all `topic_state` projections inside the migration transaction using the shared eligibility policy so coverage and briefs agree immediately. | `test_reproduction_3_projections_rebuilt_during_migration` |
| **F59** | Non-boolean `allow_partial`, full credit awarded with missing subparts, or zero score with positive evidence | Strict boolean `allow_partial` enforced; disallow full credit when required subparts are missing; require evaluated incorrect work for confirmed zero scores. | `test_reproduction_4_scoring_bypasses_prevented` |
| **F60** | Resuming attempt on outdated exercise revision | `resume_attempt` enforces educational identity resolution and rejects outdated attempts; `course_brief` omits stale attempts from resume recommendations. | `test_reproduction_5_stale_attempt_resumption_and_brief` |
| **F61** | Non-finite numbers or exponent overflow in payloads | `validate_all_finite_numbers` rejects NaN, Inf, exponent overflow before mutations; responses tested with `allow_nan=False` before committing receipts. | `test_reproduction_6_reject_non_finite_json_before_commit` |
| **F62** | Multi-host workspace handover and cross-host resume across Antigravity, Codex, and Claude Code | Cross-host conformance smoke test executes sequential handover: Host A (Antigravity) initializes, ingests with assumptions and pauses attempt; Host B (Codex) resumes, records hint, commits assisted evidence, verifies write idempotency, and scores item; Host C (Claude Code) inspects source region, corrects tutor mistake with preserved audit trail, and verifies byte-for-byte backup/restore. | `test_three_host_cross_resume_conformance_smoke_test` |

---

## 3. Synthetic Task Benchmark: Heuristic Context Payload Reduction

> [!NOTE]
> This benchmark measures context payload reduction in raw transferred bytes and character-based heuristic token estimates (~4 chars/token) on synthetic course tasks. It does not measure provider-billed total monetary costs or real model tokenizer token savings.

### A. Single Operation Payload Comparison
Measured against synthetic probability course materials (`lecture_bayes.txt` + `slides_random_variables.txt`):

| Context / Operation | Measured Payload (Bytes) | Estimated Tokens (~4 chars/token) | Payload Reduction vs Full Injection |
|---|---|---|---|
| **Naive Baseline (All Sources)** | 2,807 B | ~701 tokens | 0% (baseline) |
| **Lumen Session Startup (`course_brief`)** | 931 B | ~232 tokens | **66.8% reduction** |
| **Lumen Compact Search (`search`)** | 979 B | ~244 tokens | **65.1% reduction** |
| **Targeted Unit Reading (`read_units`)** | 891 B | ~222 tokens | **68.2% reduction** |

### B. Historical Synthetic Payload Benchmark (6 Turns)
These historical payload figures are not actual model tokens, billed costs, or a controlled correctness evaluation; they are not a current savings claim. Simulates: (1) Session Brief -> (2) Concept Search -> (3) Dependency Expansion & Read -> (4) Start Attempt + Receipt -> (5) Submission Event -> (6) Evidence Commit + Receipt:

| Metric | Naive Full-Materials Baseline | Lumen Structured Operations | Payload Reduction |
|---|---|---|---|
| **Total Transferred Bytes** | 16,842 bytes | 4,815 bytes | **71.4% reduction** |
| **Estimated Tokens (~4 chars/token)** | 4,206 tokens | 1,200 tokens | **71.5% reduction** |

---

## 4. Host Integration Verification Status

| Host | Evidence available in this audit | Remaining gate |
|---|---|---|
| Codex | Canonical instructions/skill read; CLI workflows and tests run; original user-uploaded solution PNG and rendered Hebrew lecture pages visually reviewed; 42-call real-course workflow with evidence, feedback, pause/resume and restore verified. See [real-course report](reports/real-course-integration-report.md). Installed CLI reports 0.163.0. | Fresh Codex conversation and actual cross-host resume not exercised; broader educational evaluation remains open. |
| Claude Code | Loader/pointer paths inspected; verified Claude skill relative links resolve; shared core/CLI simulated marker tests pass | No Claude executable available; actual native discovery, invocation, and images require a recorded session |
| Antigravity | Live integration verified in host executable `/workspace/.local/bin/agy` (v1.4.2); native rule & skill discovery, full test suite (145 passed), e2e course walkthrough (98 CLI calls), visual PDF inspection, ambiguous solution image handling, and fresh-session resume verified (see [development/docs/reports/antigravity-integration-report.md](reports/antigravity-integration-report.md)). | Cross-host multi-client handover with Claude Code / Codex remains open. |

`tests/test_three_host_conformance.py` changes environment markers. It does not launch three hosts or establish their versions, instruction loading, or image display. After the user enabled full filesystem access, the canonical skill update was applied successfully. The runnable workflow is in `docs/lumen-workflow.md`; `development/docs/reports/lumen-skill-audit.patch` retains that historical change for review and predates the generalized skill revision.

---

## 5. Traceable Repair Checklist: Confirmed Defects & Audit Items

### Defect 1: Scoring Race with Evidence Retraction
- **Priority**: High (P1)
- **Reproduction**: Multi-connection race where Connection 2 retracts evidence while Connection 1 validates and scores item.
- **Violated Requirement**: Goal §Non-negotiable decisions & Guarantees #1, #2 (scoring requires active evidence; atomic serialization).
- **Implementation Location**: `src/course_tutor/assessment/diagnostic.py` (`record_assessment_item_score`) & `src/course_tutor/learning/service.py` (`correct_evidence`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_defect1_concurrency_scoring_races_with_retraction`
- **Migration/API Impact**: Authoritative active evidence verification inside write transaction (`atomic_transaction`); retractions immediately invalidate scores with audit trail.
- **Verification Result**: Passed (tested under real SQLite connections with immediate lock serialization).
- **Status**: **Verified**

### Defect 2: Unlinked Items Accept External Diagnostic Attempts
- **Priority**: High (P1)
- **Reproduction**: Creating an assessment item, starting a disconnected diagnostic attempt via `start_attempt`, and passing its ID directly to `record_assessment_item_score`.
- **Violated Requirement**: Goal §Non-negotiable decisions & Guarantees #1 (scores require explicitly linked, owned attempts).
- **Implementation Location**: `src/course_tutor/assessment/diagnostic.py` (`record_assessment_item_score`, `link_assessment_item_attempt`) & `src/course_tutor/storage/migrations.py` (Migration 005 partial unique index `idx_assessment_items_unique_attempt`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_defect2_unlinked_items_and_attempt_exclusivity`
- **Migration/API Impact**: Migration 005 (`CREATE UNIQUE INDEX idx_assessment_items_unique_attempt ON assessment_items(attempt_id) WHERE attempt_id IS NOT NULL;`); new API method `link_assessment_item_attempt`.
- **Verification Result**: Passed (foreign attempt rejected, unlinked items rejected, attempt exclusivity enforced, relink audit verified).
- **Status**: **Verified**

### Defect 3: Failed-Check Strings Validate Questions
- **Priority**: High (P1)
- **Reproduction**: Passing `"false"`, `"failed"`, `"pending"`, `0`, or `1` in `checks` dict during `validate_exercise_version` which evaluated truthy under `bool(value)`.
- **Violated Requirement**: Goal Guarantees #5 (verification checks require explicit types and passing states).
- **Implementation Location**: `src/course_tutor/storage/repositories.py` (`validate_exercise_version`), `src/course_tutor/models.py` (`parse_bool`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_defect3_strict_verification_checks_and_points`
- **Migration/API Impact**: Strict check schema enforcement; non-boolean/non-passing values raise `ValidationError`; points awarded validated as finite numeric.
- **Verification Result**: Passed (invalid values rejected, failed validation leaves DB state untouched).
- **Status**: **Verified**

### Defect 4: Later Assistance Alters Diagnostic Report
- **Priority**: Medium (P2)
- **Reproduction**: Learner submits independent work, evidence is committed as `independent_mastery`, then later requests a hint. Progress report counted item as assisted.
- **Violated Requirement**: Goal Guarantees #4 (earlier independent work remains independent despite later assistance).
- **Implementation Location**: `src/course_tutor/assessment/diagnostic.py` (`get_progress`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_defect4_assistance_timeline_and_subparts`
- **Migration/API Impact**: Timeline comparison using `event_index`; reporting distinguishes item performance (`independent`, `assisted`, `solution_revealed`, `mixed`) from subsequent attempt exposure (`assistance_after_submission`).
- **Verification Result**: Passed (submission before later hint remains independent; mixed subparts reported transparently).
- **Status**: **Verified**

### Defect 5: Failed Item Startup Commits Learner Ownership
- **Priority**: Medium (P2)
- **Reproduction**: Calling `start_assessment_item_attempt` for nonexistent item order with learner Alice set `assessment.learner_id` to Alice before raising `ValidationError`, permanently locking out other learners.
- **Violated Requirement**: Goal Guarantees #3 (failed mutations leave authoritative state unchanged).
- **Implementation Location**: `src/course_tutor/assessment/diagnostic.py` (`start_assessment_item_attempt`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_defect5_failed_startup_preserves_unowned_assessment`
- **Migration/API Impact**: Atomicity within `atomic_transaction`; validation of existence and eligibility strictly precedes ownership assignment.
- **Verification Result**: Passed (unowned assessment preserved upon failed item startup; subsequent learner start succeeds).
- **Status**: **Verified**

### Defect 6: Failed Initialization Leaks Workspace Lock
- **Priority**: High (P1)
- **Reproduction**: Opening `LumenCore` on corrupted SQLite database acquires lock, raises `DatabaseError`, and leaves lock and file descriptors leaked, preventing recovery via restore.
- **Violated Requirement**: Goal Guarantees #6 (initialization failures release resources and permit recovery).
- **Implementation Location**: `src/course_tutor/api.py` (`LumenCore.__init__`, `close`), `src/course_tutor/storage/db.py` (`get_connection`), `src/course_tutor/storage/sync.py` (`WorkspaceSync.release`), `src/course_tutor/backup/restore.py` (`_check_db_not_locked`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_defect6_failed_init_releases_lock_and_allows_restore`, `test_defect6_no_file_descriptor_leak_on_repeated_init_failures`.
- **Migration/API Impact**: Exception-safe `__init__` rolls back/closes lock and connection; safe `_check_db_not_locked` ignores corrupt DB headers on forced restore.
- **Verification Result**: Passed (immediate restore succeeds after failed initialization in same process; zero FD leaks across repeated failures).
- **Status**: **Verified**

### Audit 1: Transactions and Concurrency
- **Priority**: Medium (P2)
- **Scope**: Authoritative checks inside write transactions, multi-connection SQLite isolation, migration atomicity without `executescript` transaction abortion.
- **Implementation Location**: `src/course_tutor/storage/migrations.py` (`_execute_sql_script`), `src/course_tutor/storage/db.py` (`atomic_transaction` `BEGIN IMMEDIATE`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_defect1_concurrency_scoring_races_with_retraction`
- **Verification Result**: Passed.
- **Status**: **Verified**

### Audit 2: Idempotency and Receipts
- **Priority**: Medium (P2)
- **Scope**: Intent hashing before mutation, rechecking idempotency inside write transaction, duplicate mutation prevention.
- **Implementation Location**: `src/course_tutor/api.py` (`_execute_idempotent`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_audit_idempotency_and_revision_integrity`
- **Verification Result**: Passed (idempotent replay returns prior response; conflicting intent raises `IdempotencyConflictError`).
- **Status**: **Verified**

### Audit 3: Revision Guards
- **Priority**: Medium (P2)
- **Scope**: Optimistic revision checks on entity updates preventing stale overwrites.
- **Implementation Location**: `src/course_tutor/storage/repositories.py` (`update_course`, `update_attempt`).
- **Regression Test**: `tests/test_boundary_repairs_concurrency.py::test_audit_idempotency_and_revision_integrity`
- **Verification Result**: Passed (`StaleRevisionError` raised on mismatched revision).
- **Status**: **Verified**

### Underlying Invariant 1: Legacy NULL Identity Resolution & Quarantine (Migration 007)
- **Priority**: High (P1)
- **Reproduction**: Legacy schema-v6 workspace having attempts or evidence with NULL revision/hash; attempts on modified questions scored without identity resolution.
- **Implementation Location**: `src/course_tutor/storage/migrations.py` (`resolve_and_quarantine_legacy_identities`), `src/course_tutor/learning/service.py` (`commit_evidence`).
- **Regression Test**: `tests/test_underlying_invariants_repairs.py::test_defect1_legacy_identity_resolution_and_quarantine`
- **Verification Result**: Passed (pre-migration backups `backup_v6_*` populated, unedited questions resolved, modified questions quarantined with audit history, assessment reopened, `commit_evidence` rejects unresolved/mismatched identity).
- **Status**: **Verified**

### Underlying Invariant 2: Corrections on Obsolete Evidence Retain Pending Review
- **Priority**: High (P1)
- **Reproduction**: Correcting evidence on an obsolete exercise revision or unresolved identity promoted the replacement evidence to active status, inflating topic performance.
- **Implementation Location**: `src/course_tutor/learning/service.py` (`correct_evidence`), `src/course_tutor/learning/policy.py` (`is_evidence_currently_applicable`), `src/course_tutor/storage/repositories.py` (`recompute_topic_state`).
- **Regression Test**: `tests/test_underlying_invariants_repairs.py::test_defect2_correction_on_obsolete_evidence_stays_pending`
- **Verification Result**: Passed (replacement created with `status="pending_review"` and historical rationale; recomputed topic state and course brief exclude obsolete evidence).
- **Status**: **Verified**

### Underlying Invariant 3: Observation Evidence Excluded from Assessed Coverage
- **Priority**: High (P1)
- **Reproduction**: Committing observation-level evidence (`unassessed`, `pending`, `uncertain`, `unreadable`) set topic coverage `assessed: true` in diagnostics and topic state.
- **Implementation Location**: `src/course_tutor/assessment/diagnostic.py` (`get_progress`), `src/course_tutor/storage/repositories.py` (`recompute_topic_state`).
- **Regression Test**: `tests/test_underlying_invariants_repairs.py::test_defect3_observation_evidence_excluded_from_assessed_coverage`
- **Verification Result**: Passed (only active, eligible, evaluated evidence sets `assessed: true`; observation evidence preserves `assessed: false` and `unassessed_flag: true`).
- **Status**: **Verified**

### Underlying Invariant 4: Subpart Completeness & Partial Scoring Lifecycle
- **Priority**: High (P1)
- **Reproduction**: Evaluating only one subpart of a multi-part exercise allowed marking the assessment item as `score_status="scored"` and completing the assessment.
- **Implementation Location**: `src/course_tutor/assessment/diagnostic.py` (`record_assessment_item_score`), `src/course_tutor/learning/policy.py` (`are_all_required_subparts_evaluated`, `get_required_subparts`).
- **Regression Test**: `tests/test_underlying_invariants_repairs.py::test_defect4_subpart_completeness_and_partial_scoring`
- **Verification Result**: Passed (scoring without required subparts raises `ValidationError`; `allow_partial=True` marks `partially_scored` and keeps assessment `open`; all subparts evaluated marks `scored` and completes assessment).
- **Status**: **Verified**

### Underlying Invariant 5: Stale Legacy Repair & Expected Link States
- **Priority**: Medium (P2)
- **Reproduction**: Re-running legacy repair on already-resolved quarantine records or silently overwriting active scored links.
- **Implementation Location**: `src/course_tutor/storage/migrations.py` (`repair_legacy_duplicate_links`), `src/course_tutor/errors.py` (`ConflictError`).
- **Regression Test**: `tests/test_underlying_invariants_repairs.py::test_defect5_stale_legacy_repair_and_expected_link_states`
- **Verification Result**: Passed (stale repairs on resolved records raise `ConflictError`; overwriting active scored links without explicit expectation raises `ConflictError`; matching expectation succeeds).
- **Status**: **Verified**

### Underlying Invariant 6: Finite Numeric Validation (Checks & CLI)
- **Priority**: High (P1)
- **Reproduction**: `validate_exercise_version` accepted NaN, Inf, booleans, negative numbers in check `score`, and non-strings in `reason`/`notes`; CLI accepted non-standard JSON constants (`NaN`, `Infinity`).
- **Implementation Location**: `src/course_tutor/storage/repositories.py` (`validate_exercise_version`), `src/course_tutor/models.py` (`validate_finite_number`, `validate_finite_metadata`), `src/course_tutor/cli.py` (`_reject_json_constants`, `parse_json_payload`, `output_json`).
- **Regression Test**: `tests/test_underlying_invariants_repairs.py::test_defect6_finite_numeric_checks_and_cli_payload`
- **Verification Result**: Passed (finite numbers >= 0 enforced; booleans and NaN/Inf rejected; nested metadata validated; CLI exits 1 on `NaN`/`Infinity`; output JSON formatted with `allow_nan=False`).
- **Status**: **Verified**
