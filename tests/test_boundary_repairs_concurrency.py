"""Deterministic tests for the 6 confirmed defects and concurrency boundaries in Lumen.

Covers:
- Defect 1: Multi-connection concurrency between scoring and evidence retraction
- Defect 2: Strict linking requirements, foreign attempt rejection, attempt exclusivity, and audit relinking
- Defect 3: Strict verification check schema (rejecting strings 'false', 'failed', 'pending', numbers), finite points validation
- Defect 4: Timeline-aware assistance classification (submission before later hints remains independent, mixed subparts)
- Defect 5: Atomic item attempt startup preserving unowned assessment on validation failure
- Defect 6: Exception-safe LumenCore initialization releasing locks and file descriptors for clean recovery
- Audit: Idempotency hashing, revision guards, and multi-connection isolation
"""

import math
import os
from pathlib import Path
import sqlite3
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import (
    IdempotencyConflictError,
    StaleRevisionError,
    UnvalidatedQuestionError,
    ValidationError,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ==============================================================================
# DEFECT 1: Multi-connection scoring races with evidence retraction
# ==============================================================================

def test_defect1_concurrency_scoring_races_with_retraction(temp_workspace):
    """Test multi-connection concurrency between scoring and evidence retraction."""
    core1 = LumenCore(temp_workspace)
    core2 = LumenCore(temp_workspace)
    try:
        core1.create_course("Probability", course_id="prob-c1")
        t = core1.create_topic("prob-c1", name="Bayes", slug="bayes")

        ex = core1.create_exercise("prob-c1", "bayes_q", "Calculate P(A|B)")
        core1.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="0.4",
            rubric={"max_points": 10},
            checks={"math_check": True},
            expected_revision=1,
        )

        diag = core1.create_assessment(
            "prob-c1",
            "Midterm",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # 1. Start item attempt and submit work
        item_att = core1.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = item_att["attempt"]["id"]
        core1.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="P(A|B) = 0.4")
        ev_res = core1.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "bayes", "correct": True}],
        )["data"]
        ev_id = ev_res["evidence_created"][0]["id"]

        # Ordering A: Retraction commits on Core 2 before scoring on Core 1
        core2.correct_evidence(
            evidence_id=ev_id,
            correction_reason="Grading rubric error in prompt",
        )

        # Core 1 attempts to score item with retracted evidence -> must fail
        with pytest.raises(ValidationError, match="has no active evaluated evidence"):
            core1.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)

        # Item must remain unassessed / pending_review
        prog = core1.assessment_progress(diag_id)
        assert prog["completed_items"] == 0
        assert prog["total_awarded_points"] == 0.0

        # Ordering B: Scoring on Core 1 succeeds with new active evidence, then retraction on Core 2
        core1.record_attempt_event(att_id, expected_revision=2, event_type="work_submission", content="Revised answer 0.4")
        ev_res2 = core1.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "bayes", "correct": True}],
        )["data"]
        ev_id2 = ev_res2["evidence_created"][0]["id"]

        score_res = core1.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)
        assert score_res["points_awarded"] == 10.0
        assert score_res["score_status"] == "scored"

        # Now Core 2 retracts that evidence
        core2.correct_evidence(
            evidence_id=ev_id2,
            correction_reason="Retracting after scoring audit",
        )

        # Verify Core 1 sees the item reverted to pending_review with audit history
        prog2 = core1.assessment_progress(diag_id)
        assert prog2["completed_items"] == 0
        assert prog2["status"] == "open"
        assert len(prog2["pending_work"]["pending_review_items"]) == 1
        hist = prog2["pending_work"]["pending_review_items"][0]["score_history"]
        assert len(hist) >= 2
        assert hist[-1]["action"] == "retracted_to_pending_review"
    finally:
        core1.close()
        core2.close()


# ==============================================================================
# DEFECT 2: Unlinked items reject foreign attempts & attempt exclusivity
# ==============================================================================

def test_defect2_unlinked_items_and_attempt_exclusivity(temp_workspace):
    """Test unlinked item scoring rejection, cross-attempt isolation, and relink audit."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c2")
        t = core.create_topic("prob-c2", name="Combinatorics", slug="comb")

        ex1 = core.create_exercise("prob-c2", "perm", "Permutations")
        core.validate_exercise_version(
            ex1["exercise_version_id"],
            reference_solution="120",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )
        ex2 = core.create_exercise("prob-c2", "comb", "Combinations")
        core.validate_exercise_version(
            ex2["exercise_version_id"],
            reference_solution="10",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-c2",
            "Exam",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex1["exercise_version_id"], ex2["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # 1. Unlinked item rejects score when no attempt is linked
        with pytest.raises(ValidationError, match="without an active, linked attempt"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0)

        # 2. Reject foreign attempt from practice mode
        prac_att = core.start_attempt("prob-c2", ex1["exercise_version_id"], learner_id="alice")["data"]
        with pytest.raises(ValidationError, match="does not match assessment item"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=prac_att["id"])

        # 3. Start attempt legitimately on Item 1 for Alice
        item1_res = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="alice")
        item1_att_id = item1_res["attempt"]["id"]
        core.record_attempt_event(item1_att_id, expected_revision=1, event_type="work_submission", content="120")
        core.commit_evidence(item1_att_id, evaluations=[{"topic_id": t["id"], "skill_id": "perm", "correct": True}])
        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=item1_att_id)

        # 4. Attempt exclusivity: Cannot link Alice's attempt from Item 1 to Item 2
        with pytest.raises(ValidationError, match="does not match assessment item"):
            core.record_assessment_item_score(diag_id, item_order=2, points_awarded=10.0, attempt_id=item1_att_id)

        with pytest.raises(ValidationError, match="does not match assessment item"):
            core.link_assessment_item_attempt(diag_id, item_order=2, attempt_id=item1_att_id, learner_id="alice")

        # 5. Relinking Item 1 to a fresh diagnostic attempt invalidates previous score
        item1_fresh = core.start_attempt("prob-c2", ex1["exercise_version_id"], learner_id="alice", mode="diagnostic")["data"]
        relink_res = core.link_assessment_item_attempt(diag_id, item_order=1, attempt_id=item1_fresh["id"], learner_id="alice")
        assert relink_res["attempt_id"] == item1_fresh["id"]

        prog = core.assessment_progress(diag_id)
        item1_prog = prog["pending_work"]["pending_review_items"][0]
        assert item1_prog["points_awarded"] is None
        assert item1_prog["score_status"] == "pending_review"
        assert any(h["action"] == "relinked_to_pending_review" for h in item1_prog["score_history"])
    finally:
        core.close()


# ==============================================================================
# DEFECT 3: Strict verification checks schema & finite numeric validation
# ==============================================================================

def test_defect3_strict_verification_checks_and_points(temp_workspace):
    """Test rejection of 'false', 'failed', 'pending', numbers as checks and strict points validation."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c3")
        ex = core.create_exercise("prob-c3", "algebra", "Solve for x")
        ver_id = ex["exercise_version_id"]

        # Ambiguous string check values must be rejected
        for bad_check_val in ["false", "failed", "pending", "0", "None"]:
            with pytest.raises(ValidationError, match="Invalid check value type"):
                core.validate_exercise_version(
                    ver_id,
                    reference_solution="x = 5",
                    rubric={"max_points": 5},
                    checks={"math": bad_check_val},
                    expected_revision=1,
                )

        # Numeric check values must be rejected
        for bad_num in [0, 1, 0.0, -1]:
            with pytest.raises(ValidationError, match="Invalid check value type"):
                core.validate_exercise_version(
                    ver_id,
                    reference_solution="x = 5",
                    rubric={"max_points": 5},
                    checks={"math": bad_num},
                    expected_revision=1,
                )

        # Containers must be rejected
        with pytest.raises(ValidationError, match="Invalid check value type"):
            core.validate_exercise_version(
                ver_id,
                reference_solution="x = 5",
                rubric={"max_points": 5},
                checks={"math": ["step1"]},
                expected_revision=1,
            )

        # Structured check with status 'failed' or 'pending' must raise error
        with pytest.raises(ValidationError, match="must pass, but found failed check"):
            core.validate_exercise_version(
                ver_id,
                reference_solution="x = 5",
                rubric={"max_points": 5},
                checks={"math": {"status": "failed"}},
                expected_revision=1,
            )
        with pytest.raises(ValidationError, match="must pass, but found failed check"):
            core.validate_exercise_version(
                ver_id,
                reference_solution="x = 5",
                rubric={"max_points": 5},
                checks={"math": {"status": "pending"}},
                expected_revision=1,
            )

        # Boolean False must be rejected
        with pytest.raises(ValidationError, match="must pass, but found failed check"):
            core.validate_exercise_version(
                ver_id,
                reference_solution="x = 5",
                rubric={"max_points": 5},
                checks={"math": False},
                expected_revision=1,
            )

        # Verify database was NOT changed by failed validation attempts
        ex_ver = core.exercise_repo.get_exercise_version(ver_id)
        assert ex_ver.validation_state == "pending_review"

        # Valid boolean True and structured passing checks succeed
        core.validate_exercise_version(
            ver_id,
            reference_solution="x = 5",
            rubric={"max_points": 5},
            checks={"reviewer_verified": True, "syntax": {"status": "passed"}},
            expected_revision=1,
        )
        ex_ver_valid = core.exercise_repo.get_exercise_version(ver_id)
        assert ex_ver_valid.validation_state == "validated"

        # Check strict points validation in scoring
        t = core.create_topic("prob-c3", name="Algebra", slug="alg")
        diag = core.create_assessment(
            "prob-c3",
            "Algebra Diag",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ver_id],
        )["data"]
        diag_id = diag["assessment_id"]

        att = core.start_assessment_item_attempt(diag_id, item_order=1)["attempt"]
        core.record_attempt_event(att["id"], expected_revision=1, event_type="work_submission", content="x = 5")
        core.commit_evidence(att["id"], evaluations=[{"topic_id": t["id"], "skill_id": "alg", "correct": True}])

        # Boolean as points awarded must be rejected
        with pytest.raises(ValidationError, match="Points awarded must be a finite numeric value"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=True, attempt_id=att["id"])

        # NaN / Inf must be rejected
        with pytest.raises(ValidationError, match="Points awarded must be a finite numeric value"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=float("nan"), attempt_id=att["id"])
        with pytest.raises(ValidationError, match="Points awarded must be a finite numeric value"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=float("inf"), attempt_id=att["id"])
    finally:
        core.close()


# ==============================================================================
# DEFECT 4: Assistance timeline and subparts
# ==============================================================================

def test_defect4_assistance_timeline_and_subparts(temp_workspace):
    """Test that later assistance does not downgrade earlier independent submission, and mixed subparts."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c4")
        t = core.create_topic("prob-c4", name="Stats", slug="stats")

        # Multi-subpart exercise (Part A and Part B)
        ex = core.create_exercise(
            "prob-c4",
            "stats_2part",
            "Mean and Variance",
            subparts=[{"subpart_key": "a", "prompt": "Mean"}, {"subpart_key": "b", "prompt": "Variance"}],
        )
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="Mean=10, Var=2",
            rubric={"max_points": 10},
            checks={"verified": True},
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-c4",
            "Stats Diag",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # Case 1: Independent submission followed by later hint request
        att_res = core.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = att_res["attempt"]["id"]

        # Student submits Part A independently
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Part A: Mean = 10")
        core.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "mean", "subpart_key": "a", "correct": True}],
        )

        # Later: Student asks for a hint on Part B
        core.record_attempt_event(att_id, expected_revision=2, event_type="hint_given", content="Formula for variance is...")

        # Student submits Part B after hint
        core.record_attempt_event(att_id, expected_revision=3, event_type="work_submission", content="Part B: Var = 2")
        core.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "var", "subpart_key": "b", "correct": True}],
        )

        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=9.0, attempt_id=att_id)

        prog = core.assessment_progress(diag_id)
        item_d = prog["items"][0]
        # Mixed classification: Part A was independent, Part B was assisted
        assert item_d["performance_classification"] == "mixed"
        assert item_d["subpart_evaluations"]["a"] == "independent_mastery"
        assert item_d["subpart_evaluations"]["b"] == "assisted_success"
        assert item_d["exposure"]["hints"] == 1
        assert item_d["exposure"]["assistance_after_submission"] is True

        # Case 2: Pure independent item followed by later post-completion hint
        ex_single = core.create_exercise("prob-c4", "single", "Single question")
        core.validate_exercise_version(
            ex_single["exercise_version_id"],
            reference_solution="42",
            rubric={"max_points": 5},
            checks={"verified": True},
            expected_revision=1,
        )
        diag2 = core.create_assessment(
            "prob-c4",
            "Single Diag",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex_single["exercise_version_id"]],
        )["data"]
        diag2_id = diag2["assessment_id"]

        att2 = core.start_assessment_item_attempt(diag2_id, item_order=1)["attempt"]
        core.record_attempt_event(att2["id"], expected_revision=1, event_type="work_submission", content="42")
        core.commit_evidence(
            att2["id"],
            evaluations=[{"topic_id": t["id"], "skill_id": "calc", "correct": True}],
        )
        # Tutor gives supplemental note / hint AFTER submission
        core.record_attempt_event(att2["id"], expected_revision=2, event_type="hint_given", content="Good job, note that...")
        core.record_assessment_item_score(diag2_id, item_order=1, points_awarded=5.0, attempt_id=att2["id"])

        prog2 = core.assessment_progress(diag2_id)
        assert prog2["items"][0]["performance_classification"] == "independent"
        assert prog2["items"][0]["exposure"]["assistance_after_submission"] is True
    finally:
        core.close()


# ==============================================================================
# DEFECT 5: Failed item startup commits learner ownership
# ==============================================================================

def test_defect5_failed_startup_preserves_unowned_assessment(temp_workspace):
    """Test that failed item startup does not commit learner ownership to unowned assessment."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c5")
        t = core.create_topic("prob-c5", name="Topic", slug="top")
        ex = core.create_exercise("prob-c5", "ex_c5", "Question")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="1",
            rubric={"max_points": 10},
            checks={"verified": True},
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-c5",
            "Unowned Diagnostic",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # Verify initial assessment has no learner_id
        asmt = core.assessment_repo.get_assessment(diag_id)
        assert asmt.learner_id is None

        # Call start_assessment_item_attempt for nonexistent item 999 with learner Alice
        with pytest.raises(ValidationError, match="Item 999 not found"):
            core.start_assessment_item_attempt(diag_id, item_order=999, learner_id="alice")

        # Verify assessment is STILL unowned
        asmt_after = core.assessment_repo.get_assessment(diag_id)
        assert asmt_after.learner_id is None

        # Verify Bob can now legitimately start item 1 without learner conflict
        bob_att = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="bob")
        assert bob_att["attempt"]["learner_id"] == "bob"

        # Verify assessment is now owned by Bob
        asmt_bob = core.assessment_repo.get_assessment(diag_id)
        assert asmt_bob.learner_id == "bob"

        # Calling start again for Bob returns existing attempt idempotently
        bob_att_retry = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="bob")
        assert bob_att_retry["attempt"]["id"] == bob_att["attempt"]["id"]
        assert bob_att_retry.get("resumed") is True
    finally:
        core.close()


# ==============================================================================
# DEFECT 6: Failed initialization releases workspace lock allowing clean recovery
# ==============================================================================

def test_defect6_failed_init_releases_lock_and_allows_restore(temp_workspace):
    """Test that failed LumenCore initialization releases the lock immediately, enabling restore."""
    # 1. Create a valid backup from a good workspace
    with tempfile.TemporaryDirectory() as td_good:
        good_ws = Path(td_good)
        c_good = LumenCore(good_ws)
        c_good.create_course("Good Course", course_id="good-c")
        backup_path = good_ws / "backup.zip"
        c_good.backup(backup_path)
        c_good.close()

        # 2. Corrupt the target workspace database
        db_path = temp_workspace / "lumen.db"
        temp_workspace.mkdir(parents=True, exist_ok=True)
        with open(db_path, "wb") as f:
            f.write(b"NOT A VALID SQLITE DATABASE FILE - CORRUPTED HEADER")

        # 3. Instantiate LumenCore on the corrupted workspace -> must raise error
        with pytest.raises(Exception):
            LumenCore(temp_workspace)

        # 4. In the exact same process, restore from the backup into target workspace
        # If lock was leaked, restore_workspace would raise ActiveWorkspaceSessionError
        restore_res = LumenCore.restore(backup_path, temp_workspace, force=True)
        assert restore_res["status"] == "success"

        # 5. Open restored workspace and verify it functions cleanly
        core_restored = LumenCore(temp_workspace)
        course = core_restored.course_repo.get_course("good-c")
        assert course.name == "Good Course"
        core_restored.close()


def test_defect6_no_file_descriptor_leak_on_repeated_init_failures(temp_workspace):
    """Verify that repeated failed initializations do not leak file descriptors."""
    db_path = temp_workspace / "lumen.db"
    temp_workspace.mkdir(parents=True, exist_ok=True)
    with open(db_path, "wb") as f:
        f.write(b"CORRUPT DB BYTES")

    fd_dir = Path("/proc/self/fd")
    initial_fds = len(os.listdir(fd_dir)) if fd_dir.exists() else 0

    import gc
    for _ in range(15):
        try:
            LumenCore(temp_workspace)
        except Exception:
            pass
        gc.collect()

    if fd_dir.exists():
        final_fds = len(os.listdir(fd_dir))
        # Allow at most 2 descriptor differences for temporary iteration handles
        assert abs(final_fds - initial_fds) <= 2


# ==============================================================================
# AUDIT: Idempotency replay, conflicting intents, and revision protection
# ==============================================================================

def test_audit_idempotency_and_revision_integrity(temp_workspace):
    """Test idempotency replaying, intent mismatch conflict detection, and revision tracking."""
    core = LumenCore(temp_workspace)
    try:
        # Create course with explicit request_id
        req_id = "req-course-001"
        res1 = core.create_course("Probability 101", course_id="prob-audit", request_id=req_id)
        assert res1["status"] == "success"
        assert res1["data"]["id"] == "prob-audit"

        # Replaying same request_id with exact same parameters returns identical result
        res2 = core.create_course("Probability 101", course_id="prob-audit", request_id=req_id)
        assert res2["status"] == "success"
        assert res2.get("idempotent_replay") is True
        assert res2["data"]["id"] == "prob-audit"

        # Replaying same request_id with DIFFERENT parameters raises IdempotencyConflictError
        with pytest.raises(IdempotencyConflictError):
            core.create_course("Different Course Name", course_id="prob-audit", request_id=req_id)

        # Revision check on course update
        c = core.course_repo.get_course("prob-audit")
        c.name = "Advanced Probability"
        # Stale revision update must fail
        with pytest.raises(StaleRevisionError):
            core.course_repo.update_course(c, expected_revision=999)

        # Correct revision update succeeds
        updated_c = core.course_repo.update_course(c, expected_revision=c.revision)
        assert updated_c.name == "Advanced Probability"
        assert updated_c.revision == 2
    finally:
        core.close()
