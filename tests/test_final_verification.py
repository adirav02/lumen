"""Comprehensive verification suite for final correctness and reliability pass.

Covers:
- Defect A: Zero scores require evaluated active evidence grounded in submitted work.
- Defect B: Exact revision and content identity in exercise validation; optimistic concurrency.
- Defect C: Reaffirming unchanged attempt link is an idempotent no-op preserving scores.
- Defect D: Legacy schema-v4 duplicate attempt link quarantine, backup, and actionable repair.
- Lifecycle boundaries: Item order types, blank learner IDs, cross-course checks, duplicate items.
- Assistance timeline, concurrency serialization, and idempotency guarantees.
"""

from datetime import datetime, timezone
import json
import sqlite3
import threading
from typing import Any, Dict
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import (
    CrossCourseViolationError,
    IdempotencyConflictError,
    LegacyDuplicateAttemptLinkError,
    StaleRevisionError,
    ValidationError,
)
from pathlib import Path
import tempfile
from course_tutor.storage.migrations import (
    MIGRATION_V1_SQL,
    MIGRATION_V2_SQL,
    MIGRATION_V3_SQL,
    MIGRATION_V4_SQL,
    MIGRATION_V5_SQL,
    _execute_sql_script,
    detect_legacy_duplicate_attempt_links,
    quarantine_legacy_duplicate_attempt_links,
    repair_legacy_duplicate_links,
    run_migrations,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ==============================================================================
# DEFECT A: Zero scores require active evaluated evidence
# ==============================================================================

def test_defect_a_zero_score_requires_evaluated_evidence(temp_workspace):
    """Test that zero score without evaluated evidence is rejected, but evaluated incorrect work is accepted."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-def-a")
        t = core.create_topic("prob-def-a", name="Bayes", slug="bayes")
        ex = core.create_exercise("prob-def-a", "b-ex", "Calculate posterior")
        v_id = ex["exercise_version_id"]
        core.validate_exercise_version(
            v_id,
            reference_solution="0.25",
            rubric={"criteria": "correct posterior", "max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-def-a",
            "Quiz",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[v_id],
        )["data"]
        diag_id = diag["assessment_id"]

        # 1. Start and link attempt
        start_res = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="bob")
        att_id = start_res["attempt"]["id"]

        # 2. Record nonempty work submission
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="My answer is 0.99")

        # 3. CASE A1: Record points_awarded=0 with NO evaluated evidence -> MUST BE REJECTED!
        with pytest.raises(ValidationError, match="no active evaluated evidence"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=0.0, attempt_id=att_id)

        # Verify item remains unscored and assessment remains open
        prog1 = core.assessment_progress(diag_id)
        assert prog1["completed_items"] == 0
        assert prog1["status"] == "open"
        item_prog1 = prog1["items"][0]
        assert item_prog1["score_status"] == "unassessed"
        assert item_prog1["points_awarded"] is None
        assert item_prog1["evidence_ids"] == []

        # 4. Commit evaluated evidence for an incorrect answer (demonstrated_level='incorrect')
        commit_res = core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "b-calc",
                "correct": False,
                "error_category": "conceptual",
                "rationale": "Used prior instead of posterior",
            }],
        )
        ev_id = commit_res["data"]["evidence_created"][0]["id"]

        # 5. CASE A2: Record points_awarded=0 supported by valid evaluation of incorrect answer -> MUST BE ACCEPTED!
        score_res = core.record_assessment_item_score(diag_id, item_order=1, points_awarded=0.0, attempt_id=att_id)
        assert score_res["points_awarded"] == 0.0
        assert score_res["score_status"] == "scored"
        assert ev_id in score_res["evidence_ids"]

        prog2 = core.assessment_progress(diag_id)
        assert prog2["completed_items"] == 1
        assert prog2["status"] == "completed"
        assert prog2["total_awarded_points"] == 0.0

        # 6. CASE A3: If evidence is retracted, subsequent scoring attempt must be rejected
        core.correct_evidence(evidence_id=ev_id, correction_reason="Rubric under re-evaluation")
        prog3 = core.assessment_progress(diag_id)
        assert prog3["status"] == "open"

        # Now attempting to score 0.0 with retracted evidence must fail
        with pytest.raises(ValidationError, match="no active evaluated evidence"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=0.0, attempt_id=att_id)

    finally:
        core.close()


def test_defect_a_rejected_score_preserves_prior_state(temp_workspace):
    """Test that a rejected scoring mutation leaves prior score, history, and receipts intact."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-def-a2")
        t = core.create_topic("prob-def-a2", name="Logic", slug="logic")
        ex = core.create_exercise("prob-def-a2", "l-ex", "Prove implication")
        v_id = ex["exercise_version_id"]
        core.validate_exercise_version(
            v_id,
            reference_solution="T -> T",
            rubric={"criteria": "truth table", "max_points": 10},
            checks={"proof": True},
            expected_revision=1,
        )
        diag = core.create_assessment("prob-def-a2", "Exam", selected_exercise_version_ids=[v_id])["data"]
        diag_id = diag["assessment_id"]

        start_res = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="charlie")
        att_id = start_res["attempt"]["id"]
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="step 1")
        core.commit_evidence(att_id, evaluations=[{"topic_id": t["id"], "skill_id": "logic_proof", "correct": True}])
        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=8.0, attempt_id=att_id)

        # Prior score is 8.0, status is completed
        prog_before = core.assessment_progress(diag_id)
        assert prog_before["total_awarded_points"] == 8.0

        # Now attempt invalid scoring with out-of-range points (e.g. 999.0)
        with pytest.raises(ValidationError, match="out of valid range"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=999.0, attempt_id=att_id)

        # Prior score and completed status must remain completely unchanged
        prog_after = core.assessment_progress(diag_id)
        assert prog_after["total_awarded_points"] == 8.0
        assert prog_after["status"] == "completed"
        assert len(prog_after["items"][0]["score_history"]) == 1
    finally:
        core.close()


# ==============================================================================
# DEFECT B: Validation attestation identifies exact revision and content
# ==============================================================================

def test_defect_b_validation_rejects_concurrently_edited_question(temp_workspace):
    """Test that validation detects concurrent content edits and rejects stale attestations."""
    core1 = LumenCore(temp_workspace)
    core2 = LumenCore(temp_workspace)
    try:
        core1.create_course("Calculus", course_id="calc-b")
        t = core1.create_topic("calc-b", name="Derivatives", slug="deriv")
        ex = core1.create_exercise("calc-b", "d1", "Find derivative of x^2")
        v_id = ex["exercise_version_id"]

        # Session 1 reads initial version
        initial_ver = core1.exercise_repo.get_exercise_version(v_id)
        assert initial_ver.validation_state == "pending_review"

        # Session 2 concurrently edits question text before Session 1 commits validation
        core2.update_exercise_version(
            version_id=v_id,
            question_text="Find derivative of x^3",
            expected_revision=1,
        )

        # Session 1 attempts to validate with expected_revision=1 (which is now stale)
        with pytest.raises(StaleRevisionError):
            core1.validate_exercise_version(
                version_id=v_id,
                reference_solution="2x",
                rubric={"max_points": 10},
                checks={"math": True},
                expected_revision=1,
            )

        # Session 1 attempts to validate specifying expected_question_text of old question
        with pytest.raises(ValidationError, match="question text mismatch"):
            core1.validate_exercise_version(
                version_id=v_id,
                reference_solution="2x",
                rubric={"max_points": 10},
                checks={"math": True},
                expected_revision=2,
                expected_question_text="Find derivative of x^2",
            )

        # Database remains pending_review with edited question
        current_ver = core1.exercise_repo.get_exercise_version(v_id)
        assert current_ver.validation_state == "pending_review"
        assert current_ver.question_text == "Find derivative of x^3"

        # Now validate the new revision 2 with matching question text and solution
        valid_res = core1.validate_exercise_version(
            version_id=v_id,
            reference_solution="3x^2",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=2,
            expected_question_text="Find derivative of x^3",
        )
        assert valid_res["validation_state"] == "validated"
        assert valid_res["reference_solution"] == "3x^2"
    finally:
        core1.close()
        core2.close()


def test_defect_b_solution_and_rubric_changes_require_exact_revision(temp_workspace):
    """Test that concurrent reference solution or rubric changes reject stale validations."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Physics", course_id="phys-b")
        ex = core.create_exercise("phys-b", "p1", "Kinematics problem")
        v_id = ex["exercise_version_id"]

        # Validate initial revision 1
        core.validate_exercise_version(
            v_id,
            reference_solution="v = at",
            rubric={"criteria": "formula", "max_points": 10},
            checks={"calc": True},
            expected_revision=1,
        )

        # Update reference solution to v = u + at (revision increments to 2)
        core.update_exercise_version(
            version_id=v_id,
            reference_solution="v = u + at",
            expected_revision=1,
        )

        # Stale validation using expected_revision=1 is rejected
        with pytest.raises(StaleRevisionError):
            core.validate_exercise_version(
                v_id,
                checks={"calc": True},
                expected_revision=1,
            )

        # Stale update using expected_revision=1 is rejected
        with pytest.raises(StaleRevisionError):
            core.update_exercise_version(
                version_id=v_id,
                question_text="Updated kinematics",
                expected_revision=1,
            )
    finally:
        core.close()


# ==============================================================================
# DEFECT C: Reaffirming an unchanged link is an idempotent no-op
# ==============================================================================

def test_defect_c_reaffirming_link_preserves_score_and_completion(temp_workspace):
    """Test that calling link_assessment_item_attempt with the same attempt is a no-op that preserves scores."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Statistics", course_id="stat-c")
        t = core.create_topic("stat-c", name="Normal Distribution", slug="norm")
        ex = core.create_exercise("stat-c", "n1", "Find Z-score")
        v_id = ex["exercise_version_id"]
        core.validate_exercise_version(
            v_id,
            reference_solution="1.96",
            rubric={"max_points": 10},
            checks={"stat": True},
            expected_revision=1,
        )
        diag = core.create_assessment("stat-c", "Exam", selected_exercise_version_ids=[v_id])["data"]
        diag_id = diag["assessment_id"]

        # 1. Start attempt and link
        start_res = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="dana")
        att_id = start_res["attempt"]["id"]

        # 2. Reaffirm link before submission -> preserved
        reaffirm_1 = core.link_assessment_item_attempt(diag_id, item_order=1, attempt_id=att_id, learner_id="dana")
        assert reaffirm_1.get("reaffirmed") is True

        # 3. Submit and evaluate
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Z = 1.96")
        core.commit_evidence(att_id, evaluations=[{"topic_id": t["id"], "skill_id": "z_calc", "correct": True}])

        # 4. Reaffirm link after evaluation -> preserved
        reaffirm_2 = core.link_assessment_item_attempt(diag_id, item_order=1, attempt_id=att_id, learner_id="dana")
        assert reaffirm_2.get("reaffirmed") is True

        # 5. Score item
        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)
        prog_before = core.assessment_progress(diag_id)
        assert prog_before["status"] == "completed"
        assert prog_before["total_awarded_points"] == 10.0

        # 6. Reaffirm link after scoring -> MUST BE PRESERVED! Score and completion MUST NOT be erased!
        reaffirm_3 = core.link_assessment_item_attempt(diag_id, item_order=1, attempt_id=att_id, learner_id="dana")
        assert reaffirm_3.get("reaffirmed") is True
        assert reaffirm_3["points_awarded"] == 10.0
        assert reaffirm_3["score_status"] == "scored"

        prog_after = core.assessment_progress(diag_id)
        assert prog_after["status"] == "completed"
        assert prog_after["total_awarded_points"] == 10.0
        assert len(prog_after["items"][0]["score_history"]) == 1

        # 7. Relinking to a genuinely DIFFERENT attempt clears the score with audit trail
        fresh_att = core.start_attempt("stat-c", v_id, learner_id="dana", mode="diagnostic")["data"]
        relink_res = core.link_assessment_item_attempt(diag_id, item_order=1, attempt_id=fresh_att["id"], learner_id="dana")
        assert relink_res.get("reaffirmed") is not True

        prog_relinked = core.assessment_progress(diag_id)
        assert prog_relinked["status"] == "open"
        assert prog_relinked["completed_items"] == 0
        hist = prog_relinked["items"][0]["score_history"]
        assert len(hist) == 2
        assert hist[-1]["action"] == "relinked_to_pending_review"
    finally:
        core.close()


# ==============================================================================
# DEFECT D: Legacy schema-v4 migration handles duplicate attempt links
# ==============================================================================

def test_defect_d_legacy_migration_with_duplicate_attempt_links(tmp_path):
    """Test that a schema-v4 database with duplicate attempt links successfully upgrades to v5."""
    ws = tmp_path / "legacy_v4_workspace"
    ws.mkdir()
    db_path = ws / "lumen.db"

    # 1. Build a legacy schema-v4 database directly
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        _execute_sql_script(con, MIGRATION_V1_SQL)
        con.execute("INSERT INTO schema_migrations VALUES (1, datetime('now'), 'v1');")
        _execute_sql_script(con, MIGRATION_V2_SQL)
        con.execute("INSERT INTO schema_migrations VALUES (2, datetime('now'), 'v2');")
        _execute_sql_script(con, MIGRATION_V3_SQL)
        con.execute("INSERT INTO schema_migrations VALUES (3, datetime('now'), 'v3');")
        _execute_sql_script(con, MIGRATION_V4_SQL)
        con.execute("INSERT INTO schema_migrations VALUES (4, datetime('now'), 'v4');")

        # Insert course, exercise, exercise_version, and attempt
        now = datetime.now(timezone.utc).isoformat()
        con.execute("INSERT INTO courses VALUES ('c1', 'Algorithms', '', 'en', '{}', 1, ?, ?)", (now, now))
        con.execute("INSERT INTO exercises VALUES ('ex1', 'c1', 'sort', '', ?)", (now,))
        con.execute(
            """
            INSERT INTO exercise_versions VALUES (
                'ev1', 'ex1', 'c1', 1, 'QuickSort runtime', '[]', '[]', '[]',
                'O(n log n)', '{"max_points": 10}', 'validated', 'notes', ?, '[]'
            )
            """,
            (now,),
        )
        con.execute(
            "INSERT INTO attempts VALUES ('att_shared', 'c1', 'ev1', 'alice', 'diagnostic', 'open', 1, ?, ?, NULL)",
            (now, now),
        )

        # Insert two assessments and link BOTH items to 'att_shared' (reproducing Defect D!)
        con.execute("INSERT INTO assessments VALUES ('as1', 'c1', 'Quiz 1', '{}', 'completed', ?, ?, 'alice')", (now, now))
        con.execute("INSERT INTO assessments VALUES ('as2', 'c1', 'Quiz 2', '{}', 'completed', ?, ?, 'alice')", (now, now))

        con.execute(
            """
            INSERT INTO assessment_items VALUES (
                'item_1', 'as1', 'ev1', 1, 'att_shared', 1.0, 10.0, 10.0, 0, ?,
                'scored', '[{"action": "scored", "points": 10.0}]', '["ev_1"]', 'alice'
            )
            """,
            (now,),
        )
        con.execute(
            """
            INSERT INTO assessment_items VALUES (
                'item_2', 'as2', 'ev1', 1, 'att_shared', 1.0, 10.0, 8.0, 0, ?,
                'scored', '[{"action": "scored", "points": 8.0}]', '["ev_2"]', 'alice'
            )
            """,
            (now,),
        )
        con.commit()

        # 2. Test pre-migration detection
        dups = detect_legacy_duplicate_attempt_links(con)
        assert len(dups) == 1
        assert dups[0]["attempt_id"] == "att_shared"
        assert dups[0]["count"] == 2
        assert len(dups[0]["items"]) == 2

        # 3. Test that run_migrations(con, auto_quarantine_duplicates=False) raises structured error
        with pytest.raises(LegacyDuplicateAttemptLinkError) as exc_info:
            run_migrations(con, auto_quarantine_duplicates=False)
        assert "att_shared" in exc_info.value.details["duplicate_attempt_ids"]

        # 4. Now run migrations with auto-quarantine (default for workspace startup)
        run_migrations(con, auto_quarantine_duplicates=True)

        # 5. Verify Migration 5 applied cleanly
        cursor = con.execute("SELECT version FROM schema_migrations WHERE version = 5")
        assert cursor.fetchone() is not None

        # 6. Verify pre-migration backup table exists and contains the historical duplicate rows
        backup_rows = con.execute("SELECT * FROM backup_v4_assessment_items WHERE attempt_id = 'att_shared'").fetchall()
        assert len(backup_rows) == 2

        # 7. Verify audit table legacy_duplicate_attempt_links contains both items
        audit_rows = con.execute("SELECT * FROM legacy_duplicate_attempt_links WHERE attempt_id = 'att_shared'").fetchall()
        assert len(audit_rows) == 2
        assert all(r["resolution_status"] == "quarantined" for r in audit_rows)

        # 8. Verify assessment_items rows were quarantined: attempt_id is NULL, score_status is pending_review
        items = con.execute("SELECT id, attempt_id, score_status, points_awarded, score_history_json FROM assessment_items").fetchall()
        for it in items:
            assert it["attempt_id"] is None
            assert it["score_status"] == "pending_review"
            assert it["points_awarded"] is None
            hist = json.loads(it["score_history_json"])
            assert any(entry.get("action") == "quarantined_legacy_duplicate_attempt_link" for entry in hist)

        # 9. Verify assessments were reopened
        as_rows = con.execute("SELECT status FROM assessments").fetchall()
        assert all(r["status"] == "open" for r in as_rows)

        # 10. Test repair_legacy_duplicate_links: assign att_shared to item_1
        repair_res = repair_legacy_duplicate_links(con, resolved_assignments={"att_shared": "item_1"})
        assert len(repair_res["resolved"]) == 1
        assert repair_res["resolved"][0]["assessment_item_id"] == "item_1"

        # Verify item_1 has attempt_id='att_shared', item_2 remains unlinked
        item1_row = con.execute("SELECT attempt_id, score_status FROM assessment_items WHERE id = 'item_1'").fetchone()
        assert item1_row["attempt_id"] == "att_shared"
        assert item1_row["score_status"] == "pending_review"

        item2_row = con.execute("SELECT attempt_id, score_status FROM assessment_items WHERE id = 'item_2'").fetchone()
        assert item2_row["attempt_id"] is None

        # 11. Verify unique index prevents any new duplicate attempt_id
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE assessment_items SET attempt_id = 'att_shared' WHERE id = 'item_2'")

    finally:
        con.close()

    # 12. Verify LumenCore opens the upgraded workspace cleanly
    core = LumenCore(ws)
    try:
        quarantined = core.get_quarantined_legacy_duplicate_links()
        assert len(quarantined) == 2
    finally:
        core.close()


# ==============================================================================
# LIFECYCLE, BOUNDARY & RISK TESTS (Sections 3-12)
# ==============================================================================

def test_lifecycle_boundaries_item_order_and_learner_id(temp_workspace):
    """Test strict validation of item_order and learner_id inputs across diagnostic methods."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Math", course_id="math-bound")
        ex = core.create_exercise("math-bound", "m1", "Add 1+1")
        v_id = ex["exercise_version_id"]
        core.validate_exercise_version(v_id, reference_solution="2", rubric={"max_points": 10}, checks={"c": True}, expected_revision=1)
        diag = core.create_assessment("math-bound", "Quiz", selected_exercise_version_ids=[v_id])["data"]
        diag_id = diag["assessment_id"]

        # Item order: reject boolean True, 0, negative, string, float
        for bad_order in [True, False, 0, -1, "1", 1.5]:
            with pytest.raises(ValidationError, match="Invalid item"):
                core.start_assessment_item_attempt(diag_id, item_order=bad_order, learner_id="alice")

            with pytest.raises(ValidationError, match="Invalid item"):
                core.link_assessment_item_attempt(diag_id, item_order=bad_order, attempt_id="att-x", learner_id="alice")

            with pytest.raises(ValidationError, match="Invalid item"):
                core.record_assessment_item_score(diag_id, item_order=bad_order, points_awarded=10.0)

        # Learner ID: reject empty or whitespace strings
        for bad_learner in ["", "   "]:
            with pytest.raises(ValidationError, match="Invalid learner_id"):
                core.start_assessment_item_attempt(diag_id, item_order=1, learner_id=bad_learner)

            with pytest.raises(ValidationError, match="Learner ID must be a non-empty string"):
                core.link_assessment_item_attempt(diag_id, item_order=1, attempt_id="att-x", learner_id=bad_learner)
    finally:
        core.close()


def test_cross_course_and_duplicate_assessment_creation(temp_workspace):
    """Test cross-course rejection on blueprints/exercises and duplicate exercise versions rejection."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Course A", course_id="course-a")
        core.create_course("Course B", course_id="course-b")

        t_b = core.create_topic("course-b", name="Foreign Topic", slug="foreign")
        ex_b = core.create_exercise("course-b", "ex-b", "Question B")
        v_b = ex_b["exercise_version_id"]
        core.validate_exercise_version(v_b, reference_solution="sol", rubric={"max_points": 10}, checks={"c": True}, expected_revision=1)

        ex_a = core.create_exercise("course-a", "ex-a", "Question A")
        v_a = ex_a["exercise_version_id"]
        core.validate_exercise_version(v_a, reference_solution="sol", rubric={"max_points": 10}, checks={"c": True}, expected_revision=1)

        # 1. Blueprint topics belonging to another course -> CrossCourseViolationError
        with pytest.raises(CrossCourseViolationError):
            core.create_assessment("course-a", "Test", blueprint={"topic_ids": [t_b["id"]]})

        # 2. Selected exercise version belonging to another course -> CrossCourseViolationError
        with pytest.raises(CrossCourseViolationError):
            core.create_assessment("course-a", "Test", selected_exercise_version_ids=[v_b])

        # 3. Duplicate selected exercise versions -> ValidationError
        with pytest.raises(ValidationError, match="Duplicate exercise versions"):
            core.create_assessment("course-a", "Test", selected_exercise_version_ids=[v_a, v_a])
    finally:
        core.close()


def test_assistance_chronology_and_exposure_preservation(temp_workspace):
    """Test that independent work followed by later assistance preserves independent classification."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Bio", course_id="bio-chron")
        t = core.create_topic("bio-chron", name="Genetics", slug="gen")
        ex = core.create_exercise("bio-chron", "g1", "Punnett square")
        v_id = ex["exercise_version_id"]
        core.validate_exercise_version(v_id, reference_solution="3:1", rubric={"max_points": 10}, checks={"c": True}, expected_revision=1)
        diag = core.create_assessment("bio-chron", "Exam", selected_exercise_version_ids=[v_id])["data"]
        diag_id = diag["assessment_id"]

        start_res = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="elena")
        att_id = start_res["attempt"]["id"]

        # Step 1: Elena submits independent work
        sub = core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Ratio is 3:1")

        # Step 2: Elena later requests a hint to double-check and receives hint_given
        core.record_attempt_event(att_id, expected_revision=2, event_type="hint_request", content="Is this correct?")
        core.record_attempt_event(att_id, expected_revision=3, event_type="hint_given", content="Review the homozygous recessive row.")

        # Step 3: Evaluate submission
        sub_event_id = sub["data"]["event"]["id"] if "data" in sub else sub["event"]["id"]
        core.commit_evidence(
            att_id,
            submission_event_id=sub_event_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "ratio", "correct": True}],
        )
        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)

        # Classification must remain "independent" because submission strictly preceded the hint!
        prog = core.assessment_progress(diag_id)
        assert prog["items"][0]["performance_classification"] == "independent"
        assert prog["items"][0]["exposure"]["assistance_after_submission"] is True
    finally:
        core.close()


def test_cli_update_and_repair_operations(temp_workspace):
    """Test CLI dispatch for exercise update and legacy link repair."""
    core = LumenCore(temp_workspace)
    core.create_course("CLI Course", course_id="cli-c")
    ex = core.create_exercise("cli-c", "cli-ex", "Original CLI Question")
    v_id = ex["exercise_version_id"]
    core.close()

    import subprocess
    import sys

    # Test update_exercise_version via CLI
    input_payload = json.dumps({
        "version_id": v_id,
        "question_text": "Updated CLI Question",
        "expected_revision": 1,
    })
    proc1 = subprocess.run(
        [sys.executable, "-m", "course_tutor.cli", "update_exercise_version", "--workspace", str(temp_workspace), "-j", input_payload],
        capture_output=True,
        text=True,
    )
    assert proc1.returncode == 0
    out1 = json.loads(proc1.stdout)
    assert out1["status"] == "success"
    assert out1["data"]["question_text"] == "Updated CLI Question"

    # Test repair_legacy_duplicate_links via CLI
    proc2 = subprocess.run(
        [sys.executable, "-m", "course_tutor.cli", "repair_legacy_duplicate_links", "--workspace", str(temp_workspace), "-j", "{}"],
        capture_output=True,
        text=True,
    )
    assert proc2.returncode == 0
    out2 = json.loads(proc2.stdout)
    assert out2["status"] == "success"
