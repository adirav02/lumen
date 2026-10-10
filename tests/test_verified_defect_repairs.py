"""Comprehensive regression tests verifying fixes for Defects 1 through 7 in Lumen."""

import importlib
import json
import math
from pathlib import Path
import pkgutil
import sqlite3
import tempfile
import types
import typing
import uuid
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import (
    RestoreIntegrityError,
    UnvalidatedQuestionError,
    ValidationError,
    WorkspaceDetachedError,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ==============================================================================
# DEFECT 1: Require observed, validated work before awarding assessment scores
# ==============================================================================

def test_defect1_require_observed_validated_work_for_scores(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d1")
        t = core.create_topic("prob-d1", name="Bayes", slug="bayes")

        ex1 = core.create_exercise("prob-d1", "bayes_1", "Calculate P(A|B)")
        core.validate_exercise_version(
            ex1["exercise_version_id"],
            reference_solution="0.4",
            rubric={"max_points": 10},
            checks=["math_checked"],
        )
        ex2 = core.create_exercise("prob-d1", "bayes_2", "Calculate P(B|A)")
        core.validate_exercise_version(
            ex2["exercise_version_id"],
            reference_solution="0.8",
            rubric={"max_points": 10},
            checks=["math_checked"],
        )

        diag = core.create_assessment(
            "prob-d1",
            "Bayes Diagnostic",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex1["exercise_version_id"], ex2["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # 1. Reject score without an attempt
        with pytest.raises(ValidationError, match="without an active, linked attempt"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0)

        # 2. Reject score with attempt for a completely different exercise
        foreign_ex = core.create_exercise("prob-d1", "other_family", "Different question")
        foreign_att = core.start_attempt("prob-d1", foreign_ex["exercise_version_id"])["data"]
        with pytest.raises(ValidationError, match="does not match assessment item"):
            core.record_assessment_item_score(
                diag_id, item_order=1, points_awarded=10.0, attempt_id=foreign_att["id"]
            )

        # 3. Start proper item attempt
        item1_att = core.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = item1_att["attempt"]["id"]

        # Attempt has no work submission yet -> Reject score
        with pytest.raises(ValidationError, match="no committed work submission"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)

        # 4. Reject empty work submission
        with pytest.raises(ValidationError, match="non-empty content"):
            core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="   ")

        # Record valid work submission
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="P(A|B) = 0.4")

        # Submission exists, but no evidence committed yet -> Reject score
        with pytest.raises(ValidationError, match="has no active evaluated evidence"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)

        # 5. Commit valid evidence
        core.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "bayes", "correct": True}],
        )

        # 6. Reject non-finite scores (NaN, Inf)
        with pytest.raises(ValidationError, match="finite numeric value"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=float("nan"), attempt_id=att_id)
        with pytest.raises(ValidationError, match="finite numeric value"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=float("inf"), attempt_id=att_id)

        # 7. Valid scoring succeeds
        score_res = core.record_assessment_item_score(
            diag_id, item_order=1, points_awarded=8.5, attempt_id=att_id
        )
        assert score_res["points_awarded"] == 8.5
        assert score_res["score_status"] == "scored"
        assert len(score_res["score_history"]) >= 1

        # 8. Check transparent reporting: unattempted items do not penalize observed score
        prog = core.assessment_progress(diag_id)
        assert prog["observed_scores"]["observed_percentage"] == 85.0
        assert prog["total_items"] == 2
        assert prog["completed_items"] == 1
        assert prog["pending_work"]["unassessed_count"] == 1
        assert "Bayes" in prog["coverage"]
        assert prog["coverage"]["Bayes"]["assessed"] is True
    finally:
        core.close()


# ==============================================================================
# DEFECT 2: Make assessment scores follow evidence corrections/retractions
# ==============================================================================

def test_defect2_assessment_scores_follow_evidence_retractions(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d2")
        t = core.create_topic("prob-d2", name="Expectation", slug="exp")

        ex1 = core.create_exercise("prob-d2", "exp_1", "Compute E[X]")
        core.validate_exercise_version(
            ex1["exercise_version_id"],
            reference_solution="3.5",
            rubric={"max_points": 10},
            checks=["verified"],
        )

        diag = core.create_assessment(
            "prob-d2",
            "Single Item Assessment",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex1["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        item_att = core.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = item_att["attempt"]["id"]

        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="3.5")
        ev_res = core.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "exp", "correct": True}],
        )["data"]
        ev_id = ev_res["evidence_created"][0]["id"]

        # Award score -> assessment becomes completed
        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)
        prog_before = core.assessment_progress(diag_id)
        assert prog_before["status"] == "completed"
        assert prog_before["items"][0]["points_awarded"] == 10.0

        # Now tutor discovers rubric error and retracts evidence
        core.correct_evidence(
            evidence_id=ev_id,
            correction_reason="Rubric ambiguity identified; score must be reviewed.",
        )

        # Progress must revert: item score_status is pending_review, assessment status is open
        prog_after = core.assessment_progress(diag_id)
        assert prog_after["status"] == "open"
        item_after = prog_after["items"][0]
        assert item_after["score_status"] == "pending_review"
        assert item_after["points_awarded"] is None
        assert len(item_after["score_history"]) >= 2
        last_history = item_after["score_history"][-1]
        assert last_history["action"] == "retracted_to_pending_review"
        assert "Rubric ambiguity identified" in last_history["reason"]
    finally:
        core.close()

    # Verify persistence survives close and reopen in SQLite
    core_reopened = LumenCore(temp_workspace)
    try:
        prog_reopened = core_reopened.assessment_progress(diag_id)
        assert prog_reopened["status"] == "open"
        assert prog_reopened["items"][0]["score_status"] == "pending_review"
        assert prog_reopened["items"][0]["points_awarded"] is None
    finally:
        core_reopened.close()


# ==============================================================================
# DEFECT 3: Remove automatic exercise validation throughout public interface
# ==============================================================================

def test_defect3_remove_automatic_exercise_validation(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d3")
        t = core.create_topic("prob-d3", name="Markov", slug="markov")

        # 1. create_exercise with validation_state="validated" is rejected down to pending_review
        ex = core.create_exercise(
            "prob-d3",
            "markov_trans",
            "Find stationary distribution",
            validation_state="validated",
        )
        assert ex["validation_state"] == "pending_review"

        # 2. Cannot use in diagnostic assessment while pending_review
        with pytest.raises(UnvalidatedQuestionError):
            core.create_assessment(
                "prob-d3",
                "Markov Test",
                blueprint={"topic_ids": [t["id"]]},
                selected_exercise_version_ids=[ex["exercise_version_id"]],
            )

        # 3. Cannot validate without reference solution, rubric, and recorded checks
        with pytest.raises(ValidationError, match="missing reference or verified solution"):
            core.validate_exercise_version(ex["exercise_version_id"])

        with pytest.raises(ValidationError, match="missing versioned rubric"):
            core.validate_exercise_version(
                ex["exercise_version_id"],
                reference_solution="pi = [0.5, 0.5]",
            )

        with pytest.raises(ValidationError, match="missing recorded verification checks"):
            core.validate_exercise_version(
                ex["exercise_version_id"],
                reference_solution="pi = [0.5, 0.5]",
                rubric={"max_points": 10},
            )

        # 4. Valid explicit validation succeeds
        val_res = core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="pi = [0.5, 0.5]",
            rubric={"max_points": 10},
            checks=["matrix_inversion_checked"],
        )
        assert val_res["validation_state"] == "validated"

        # 5. Question/rubric update invalidates validation state and active evaluations
        updated = core.update_exercise_version(
            ex["exercise_version_id"],
            question_text="Find unique stationary distribution for ergodic chain",
        )
        assert updated["validation_state"] == "pending_review"
    finally:
        core.close()


# ==============================================================================
# DEFECT 4: Close evidence/assistance bypasses in LearningService
# ==============================================================================

def test_defect4_close_evidence_and_assistance_bypasses(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d4")
        t = core.create_topic("prob-d4", name="Variance", slug="var")

        ex = core.create_exercise("prob-d4", "var_1", "Calculate Var(X)")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="Var(X) = 2.92",
            rubric={"max_points": 10},
            checks=["checked"],
        )

        att = core.start_attempt("prob-d4", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        # Learner requests and receives a hint
        core.record_attempt_event(att_id, expected_revision=1, event_type="hint_request")
        hint_ev = core.record_attempt_event(
            att_id, expected_revision=2, event_type="hint_given", content="Use Var(X) = E[X^2] - (E[X])^2"
        )

        # 1. Attempting to anchor evidence on hint event ID fails
        with pytest.raises(ValidationError, match="expected 'work_submission'"):
            core.learning_service.commit_evidence(
                att_id,
                submission_event_id=hint_ev["data"]["event"]["id"],
                evaluations=[{"topic_id": t["id"], "skill_id": "var", "correct": True}],
            )

        # 2. Learner submits correct work after hint
        core.record_attempt_event(
            att_id, expected_revision=3, event_type="work_submission", content="Var(X) = 2.92"
        )

        # 3. Cannot claim independent_mastery when hint preceded submission
        with pytest.raises(ValidationError, match="Cannot award 'independent_mastery'"):
            core.commit_evidence(
                att_id,
                evaluations=[{
                    "topic_id": t["id"],
                    "skill_id": "var",
                    "correct": True,
                    "demonstrated_level": "independent_mastery",
                }],
            )

        # Committing as assisted_success succeeds
        ev_res = core.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "var", "correct": True}],
        )["data"]
        ev = ev_res["evidence_created"][0]
        assert ev["demonstrated_level"] == "assisted_success"

        # 4. Cannot evade assistance check in correct_evidence by changing subpart
        with pytest.raises(ValidationError, match="Cannot assign 'independent_mastery'"):
            core.correct_evidence(
                evidence_id=ev["id"],
                correction_reason="Attempting to evade assistance check",
                replacement={
                    "topic_id": t["id"],
                    "skill_id": "var",
                    "subpart_key": "renamed_subpart",
                    "demonstrated_level": "independent_mastery",
                },
            )

        # 5. Work submitted BEFORE later assistance is preserved as independent
        att2 = core.start_attempt("prob-d4", ex["exercise_version_id"])["data"]
        att2_id = att2["id"]

        # Student submits subpart a independently at revision 1
        sub_a = core.record_attempt_event(
            att2_id, expected_revision=1, event_type="work_submission", subpart_key="part_a", content="E[X] = 3.5"
        )["data"]

        # Student asks for hint on subpart b at revision 2
        core.record_attempt_event(
            att2_id, expected_revision=2, event_type="hint_given", subpart_key="part_b", content="Hint for part b"
        )

        # Commit subpart a: it was submitted BEFORE any hint, so independent mastery is allowed!
        ev_a = core.learning_service.commit_evidence(
            att2_id,
            submission_event_id=sub_a["event"]["id"],
            evaluations=[{
                "subpart_key": "part_a",
                "topic_id": t["id"],
                "skill_id": "var_part_a",
                "correct": True,
                "demonstrated_level": "independent_mastery",
            }],
        )["evidence_created"][0]
        assert ev_a["demonstrated_level"] == "independent_mastery"
    finally:
        core.close()


# ==============================================================================
# DEFECT 5: Move source extraction outside outer transaction in ingest_source
# ==============================================================================

def test_defect5_source_extraction_outside_outer_transaction(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d5")

        test_file = temp_workspace / "sample_lecture.txt"
        test_file.write_text("Introduction to Probability.\nDef: Sample space S.\n", encoding="utf-8")

        # Ingestion executes with outside-of-transaction extraction
        # Verified inside IngestionPipeline: self.con.in_transaction is False during extraction
        res1 = core.ingest_source("prob-d5", test_file, logical_name="lecture1", request_id="req-ingest-1")
        assert res1["status"] in ("success", "existing_content_reused")
        assert len(res1["data"]["units_created"]) >= 1

        # Idempotent replay returns existing receipt
        res2 = core.ingest_source("prob-d5", test_file, logical_name="lecture1", request_id="req-ingest-1")
        assert res2["data"]["source_id"] == res1["data"]["source_id"]
    finally:
        core.close()


# ==============================================================================
# DEFECT 6: Report incomplete retrieval and preserve review status
# ==============================================================================

def test_defect6_report_incomplete_retrieval_and_review_status(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d6")

        # Ingest file creating units
        mat_file = temp_workspace / "prob_notes.txt"
        mat_file.write_text(
            "Conditional Probability\n\nDefinition: Conditional Probability\nFormula: P(A|B) = P(AB)/P(B)\n",
            encoding="utf-8",
        )
        ingest_res = core.ingest_source("prob-d6", mat_file, logical_name="notes")
        unit_id = ingest_res["data"]["units_created"][0]["id"]

        # Search preserves review status
        search_res = core.search("prob-d6", "Conditional")
        assert len(search_res["results"]) >= 1
        hit = search_res["results"][0]
        assert "status" in hit
        assert "is_pending_review" in hit
        assert hit["is_pending_review"] is True

        # Manually inject a dangling dependency to test closure_complete reporting
        core.con.execute(
            "UPDATE knowledge_units SET dependencies = ? WHERE id = ?",
            (json.dumps(["Missing Theorem XYZ"]), unit_id),
        )
        core.con.commit()

        read_res = core.read_units("prob-d6", [unit_id], expand_dependencies=True)
        assert read_res["expansion_requested"] is True
        assert read_res["closure_complete"] is False
        assert "Missing Theorem XYZ" in read_res["unresolved_dependencies"]
        unit_data = read_res["units"][0]
        assert unit_data["status"] == "pending_review"
        assert unit_data["is_pending_review"] is True
    finally:
        core.close()


# ==============================================================================
# DEFECT 7: Implement recoverable restore activation
# ==============================================================================

def test_defect7_recoverable_restore_activation(temp_workspace):
    # Setup source workspace and create backup
    src_ws = temp_workspace / "source_ws"
    core_src = LumenCore(src_ws)
    try:
        core_src.create_course("Probability Source", course_id="prob-source")
        backup_zip = temp_workspace / "backup.zip"
        core_src.backup(backup_zip)
    finally:
        core_src.close()

    # Target workspace with existing course
    dest_ws = temp_workspace / "dest_ws"
    core_dest = LumenCore(dest_ws)
    try:
        core_dest.create_course("Target Course Original", course_id="prob-dest")
    finally:
        core_dest.close()

    # 1. Active lock rejection
    lock_con = sqlite3.connect(dest_ws / "lumen.db", timeout=0.1)
    lock_con.execute("BEGIN IMMEDIATE;")
    try:
        with pytest.raises(RestoreIntegrityError, match="actively locked or in use"):
            LumenCore.restore(backup_zip, dest_ws, force=True)
    finally:
        lock_con.rollback()
        lock_con.close()

    # 2. Fault-injection rollback during activation swap
    import shutil
    orig_move = shutil.move

    def failing_move(src, dst, *args, **kwargs):
        # Simulate disk failure when moving candidate directory into target workspace
        if "candidate" in str(src):
            raise OSError("Simulated disk write failure during target activation")
        return orig_move(src, dst, *args, **kwargs)

    import course_tutor.backup.restore as restore_mod
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(restore_mod.shutil, "move", failing_move)

    try:
        with pytest.raises(RestoreIntegrityError, match="Restore activation failed"):
            LumenCore.restore(backup_zip, dest_ws, force=True)
    finally:
        monkeypatch.undo()

    # Target workspace MUST have rolled back to its original state completely!
    assert (dest_ws / "lumen.db").is_file()
    core_dest_verified = LumenCore(dest_ws)
    try:
        courses = core_dest_verified.course_repo.list_courses()
        course_ids = [c.id for c in courses]
        assert "prob-dest" in course_ids
        assert "prob-source" not in course_ids
    finally:
        core_dest_verified.close()

    # 3. Successful restore with force=True cleanly swaps in new workspace
    restore_res = LumenCore.restore(backup_zip, dest_ws, force=True)
    assert restore_res["status"] == "success"

    core_restored = LumenCore(dest_ws)
    try:
        courses = core_restored.course_repo.list_courses()
        course_ids = [c.id for c in courses]
        assert "prob-source" in course_ids
        assert "prob-dest" not in course_ids
    finally:
        core_restored.close()


# ==============================================================================
# CODEX DEFECT 1: Restore compatibility with supported Python versions
# ==============================================================================

def test_defect_codex_1_python_compatibility_type_hints():
    """Verify that type annotations evaluate cleanly across all classes and functions."""
    import course_tutor
    import course_tutor.storage.repositories as repos_mod
    import course_tutor.ingestion.pipeline as pipe_mod

    # Verify explicitly repaired imports
    assert hasattr(repos_mod, "Union")
    assert hasattr(pipe_mod, "ExtractedSection")

    # Verify typing.get_type_hints succeeds without NameError across entire package
    for module_info in pkgutil.walk_packages(course_tutor.__path__, course_tutor.__name__ + "."):
        mod = importlib.import_module(module_info.name)
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if isinstance(attr, type):
                typing.get_type_hints(attr)
            elif isinstance(attr, (types.FunctionType, types.MethodType)):
                typing.get_type_hints(attr)


# ==============================================================================
# CODEX DEFECT 2: Assistance bypass in commit_evidence & correct_evidence
# ==============================================================================

def test_defect_codex_2_subpart_assistance_bypass_prevention(temp_workspace):
    """Verify that omitted/default subparts adopt the submission's subpart and cannot evade hints."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c2")
        t = core.create_topic("prob-c2", name="Conditioning", slug="cond")
        ex = core.create_exercise("prob-c2", "cond_1", "Calculate P(A|B) and P(B|A)")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="0.4 and 0.8",
            rubric={"max_points": 10},
            checks=["checked"],
        )

        att = core.start_attempt("prob-c2", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        # Learner receives hint on subpart a
        core.record_attempt_event(
            att_id, expected_revision=1, event_type="hint_given", subpart_key="part_a", content="Use definition of P(A|B)"
        )

        # Learner submits work for subpart a
        sub_a = core.record_attempt_event(
            att_id, expected_revision=2, event_type="work_submission", subpart_key="part_a", content="P(A|B) = 0.4"
        )["data"]

        # Tutor attempts to commit evidence WITHOUT specifying subpart_key (or with 'default')
        # requesting 'independent_mastery'. This must NOT evade the hint on part_a!
        with pytest.raises(ValidationError, match="Cannot award 'independent_mastery' when hint was given"):
            core.commit_evidence(
                att_id,
                evaluations=[{
                    "topic_id": t["id"],
                    "skill_id": "cond_calc",
                    "correct": True,
                    "demonstrated_level": "independent_mastery",
                }],
            )

        # Committing with auto level must adopt 'part_a' and evaluate to 'assisted_success'
        ev_res = core.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "cond_calc", "correct": True}],
        )["data"]
        ev = ev_res["evidence_created"][0]
        assert ev["subpart_key"] == "part_a"
        assert ev["demonstrated_level"] == "assisted_success"

        # In correct_evidence, attempting to rename subpart to bypass assistance check is rejected
        with pytest.raises(ValidationError, match="does not match underlying submission subpart"):
            core.correct_evidence(
                evidence_id=ev["id"],
                correction_reason="Attempting to rename subpart to evade assistance",
                replacement={
                    "subpart_key": "renamed_subpart",
                    "demonstrated_level": "independent_mastery",
                },
            )

        # In correct_evidence, omitting subpart adopts 'part_a' and still blocks 'independent_mastery'
        with pytest.raises(ValidationError, match="Cannot assign 'independent_mastery' via correction when hint was given"):
            core.correct_evidence(
                evidence_id=ev["id"],
                correction_reason="Attempting to claim independent mastery",
                replacement={
                    "demonstrated_level": "independent_mastery",
                },
            )
    finally:
        core.close()


# ==============================================================================
# CODEX DEFECT 3: Assessment scoring binding and idempotent retries
# ==============================================================================

def test_defect_codex_3_assessment_scoring_binding_and_idempotency(temp_workspace):
    """Verify item attempt binding, mode checks, learner ownership, and deduplicated scoring history."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c3")
        t = core.create_topic("prob-c3", name="Expectation", slug="exp")
        ex = core.create_exercise("prob-c3", "exp_1", "Calculate E[X]")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="3.5",
            rubric={"max_points": 10},
            checks=["checked"],
        )

        diag = core.create_assessment(
            "prob-c3",
            "Expectation Diagnostic",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # Start attempt for Alice in diagnostic mode
        item_att = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="alice")
        alice_att_id = item_att["attempt"]["id"]

        # 1. Scoring with a different attempt ID must be rejected (cannot silently relink)
        foreign_att = core.learning_service.start_attempt("prob-c3", ex["exercise_version_id"], learner_id="alice", mode="diagnostic")
        with pytest.raises(ValidationError, match="does not match assessment item"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=foreign_att.id)

        # 2. Complete Alice's attempt
        core.record_attempt_event(alice_att_id, expected_revision=1, event_type="work_submission", content="E[X] = 3.5")
        core.commit_evidence(alice_att_id, evaluations=[{"topic_id": t["id"], "skill_id": "exp_calc", "correct": True}])

        # 3. Valid score recording succeeds
        score1 = core.record_assessment_item_score(diag_id, item_order=1, points_awarded=9.0, attempt_id=alice_att_id)
        assert score1["points_awarded"] == 9.0
        assert len(score1["score_history"]) == 1

        # 4. Idempotent retry must NOT append duplicate score_history entries
        score2 = core.record_assessment_item_score(diag_id, item_order=1, points_awarded=9.0, attempt_id=alice_att_id)
        assert score2["points_awarded"] == 9.0
        assert len(score2["score_history"]) == 1

        # Check persistence
        item = core.assessment_repo.get_item_by_order(diag_id, 1)
        assert len(item.score_history) == 1
    finally:
        core.close()


# ==============================================================================
# CODEX DEFECT 4: Recheck question validation when scoring
# ==============================================================================

def test_defect_codex_4_recheck_question_validation_when_scoring(temp_workspace):
    """Verify that editing question text blocks scoring if validation_state becomes pending_review."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c4")
        t = core.create_topic("prob-c4", name="Variance", slug="var")
        ex = core.create_exercise("prob-c4", "var_1", "Calculate Var(X)")
        val_ver = core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="2.5",
            rubric={"max_points": 10},
            checks=["checked"],
        )
        ex_ver_id = val_ver["id"]

        diag = core.create_assessment(
            "prob-c4",
            "Variance Diagnostic",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex_ver_id],
        )["data"]
        diag_id = diag["assessment_id"]

        item_att = core.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = item_att["attempt"]["id"]
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Var(X) = 2.5")
        core.commit_evidence(att_id, evaluations=[{"topic_id": t["id"], "skill_id": "var_calc", "correct": True}])

        # Question is edited, reverting to pending_review
        core.update_exercise_version(ex_ver_id, question_text="Calculate Var(X) for fair die")
        current_ver = core.exercise_repo.get_exercise_version(ex_ver_id)
        assert current_ver.validation_state == "pending_review"

        # Attempting to score must be blocked
        with pytest.raises(UnvalidatedQuestionError, match="not validated"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)

        # Re-validating the exercise allows scoring once active evidence is re-evaluated
        core.validate_exercise_version(
            ex_ver_id,
            reference_solution="2.5",
            rubric={"max_points": 10},
            checks=["re_checked"],
        )
        core.commit_evidence(att_id, evaluations=[{"topic_id": t["id"], "skill_id": "var_calc", "correct": True}])
        score_res = core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)
        assert score_res["points_awarded"] == 10.0
    finally:
        core.close()


# ==============================================================================
# CODEX DEFECT 5: Exercise validation checks enforcement & atomic snapshots
# ==============================================================================

def test_defect_codex_5_exercise_validation_atomic_checks_and_snapshots(temp_workspace):
    """Verify that failing checks are rejected and failed validation leaves DB content unchanged."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c5")
        ex = core.create_exercise("prob-c5", "ex_atom", "What is P(S)?")
        ver_id = ex["exercise_version_id"]

        # 1. Validation with failing checks is rejected
        with pytest.raises(ValidationError, match="verification checks must pass"):
            core.validate_exercise_version(
                ver_id,
                reference_solution="1.0",
                rubric={"max_points": 5},
                checks={"syntax_check": True, "math_check": False},
            )

        # Stored content must be completely unchanged in DB
        unmod_ver = core.exercise_repo.get_exercise_version(ver_id)
        assert unmod_ver.validation_state == "pending_review"
        assert unmod_ver.reference_solution == ""
        assert unmod_ver.rubric == {}

        # 2. Proper validation succeeds
        val_ver = core.validate_exercise_version(
            ver_id,
            reference_solution="1.0",
            rubric={"max_points": 5},
            checks={"syntax_check": True, "math_check": True},
        )
        assert val_ver["validation_state"] == "validated"

        # 3. Changing reference solution routes through revision snapshot
        reval_ver = core.validate_exercise_version(
            ver_id,
            reference_solution="P(S) is identically 1.0 by axiom",
            rubric={"max_points": 5},
            checks=["verified_axioms"],
        )
        ver_after = core.exercise_repo.get_exercise_version(ver_id)
        assert len(ver_after.revision_history) >= 1
        last_snap = ver_after.revision_history[-1]
        assert last_snap["reference_solution"] == "1.0"
    finally:
        core.close()


# ==============================================================================
# CODEX DEFECT 6: Topic-state recomputation from invalidated evidence
# ==============================================================================

def test_defect_codex_6_topic_state_recomputation_from_invalidated_evidence(temp_workspace):
    """Verify core.evidence_repo access and recomputation of topic states from invalidated evidence rows."""
    core = LumenCore(temp_workspace)
    try:
        assert hasattr(core, "evidence_repo")
        assert core.evidence_repo is not None

        core.create_course("Probability", course_id="prob-c6")
        t = core.create_topic("prob-c6", name="Axioms", slug="axioms")

        # Create exercise with empty topic_mappings
        ex = core.create_exercise("prob-c6", "unmapped_axiom", "State Kolmogorov axioms")
        ex_ver_id = ex["exercise_version_id"]
        assert ex["topic_mappings"] == []

        core.validate_exercise_version(
            ex_ver_id,
            reference_solution="Non-negativity, unit measure, countable additivity",
            rubric={"max_points": 10},
            checks=["checked"],
        )

        att = core.start_attempt("prob-c6", ex_ver_id)["data"]
        core.record_attempt_event(att["id"], expected_revision=1, event_type="work_submission", content="Axioms stated")
        core.commit_evidence(att["id"], evaluations=[{"topic_id": t["id"], "skill_id": "axiom_recall", "correct": True}])

        # Verify topic state has 1 success
        state_before = core.evidence_repo.get_topic_state("prob-c6", t["id"])
        assert state_before.independent_success_count == 1
        assert state_before.unassessed_flag is False

        # Now update exercise version question text -> invalidates evidence
        core.update_exercise_version(ex_ver_id, question_text="State all three Kolmogorov axioms clearly")

        # Topic state must be recomputed to 0 successes and unassessed_flag=True even though exercise topic_mappings was empty!
        state_after = core.evidence_repo.get_topic_state("prob-c6", t["id"])
        assert state_after.independent_success_count == 0
        assert state_after.unassessed_flag is True
    finally:
        core.close()


# ==============================================================================
# CODEX DEFECT 7: Restore synchronization & detached handle detection
# ==============================================================================

def test_defect_codex_7_restore_synchronization_and_detached_handles(temp_workspace):
    """Verify exclusive workspace sync prevents restore during active session, and detached handles are detected."""
    src_ws = temp_workspace / "src_ws"
    core_src = LumenCore(src_ws)
    try:
        core_src.create_course("Source Course", course_id="prob-sync-src")
        backup_zip = temp_workspace / "sync_backup.zip"
        core_src.backup(backup_zip)
    finally:
        core_src.close()

    dest_ws = temp_workspace / "dest_ws"
    core_dest = LumenCore(dest_ws)
    try:
        core_dest.create_course("Dest Course", course_id="prob-sync-dest")

        # 1. While core_dest is active, restore must be rejected by workspace sync lock
        with pytest.raises(RestoreIntegrityError, match="actively in use by an active session"):
            LumenCore.restore(backup_zip, dest_ws, force=True)

        # 2. Detached handle detection: replace database file under active core
        db_file = dest_ws / "lumen.db"
        db_file.unlink()
        db_file.write_bytes(b"corrupted or replaced")

        # Any operation on core_dest must detect that the handle is detached
        with pytest.raises(WorkspaceDetachedError, match="detached"):
            core_dest.create_course("Another Course")
    finally:
        core_dest.close()

    # 3. After core_dest is closed, restore succeeds cleanly
    restore_res = LumenCore.restore(backup_zip, dest_ws, force=True)
    assert restore_res["status"] == "success"


# ==============================================================================
# CODEX DEFECT 8: Assessment coverage separation
# ==============================================================================

def test_defect_codex_8_assessment_coverage_separation(temp_workspace):
    """Verify that assessment topic_coverage reflects only assessment items, not course-wide practice."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c8")
        t_bayes = core.create_topic("prob-c8", name="Bayes", slug="bayes")
        t_exp = core.create_topic("prob-c8", name="Expectation", slug="exp")

        # 1. Learner practices Bayes repeatedly in general practice
        ex_bayes = core.create_exercise("prob-c8", "bayes_prac", "Bayes Practice")
        core.validate_exercise_version(
            ex_bayes["exercise_version_id"],
            reference_solution="0.5",
            rubric={"max_points": 10},
            checks=["checked"],
        )
        for _ in range(2):
            att = core.start_attempt("prob-c8", ex_bayes["exercise_version_id"])["data"]
            core.record_attempt_event(att["id"], expected_revision=1, event_type="work_submission", content="0.5")
            core.commit_evidence(att["id"], evaluations=[{"topic_id": t_bayes["id"], "skill_id": "bayes_calc", "correct": True}])

        # 2. Create diagnostic covering BOTH Bayes and Expectation, but with an exercise ONLY for Expectation
        ex_exp = core.create_exercise("prob-c8", "exp_diag", "Expectation Diag")
        core.validate_exercise_version(
            ex_exp["exercise_version_id"],
            reference_solution="3.5",
            rubric={"max_points": 10},
            checks=["checked"],
        )

        diag = core.create_assessment(
            "prob-c8",
            "Midterm Diagnostic",
            blueprint={"topic_ids": [t_bayes["id"], t_exp["id"]]},
            selected_exercise_version_ids=[ex_exp["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # Learner attempts and scores Expectation item in the diagnostic
        item_att = core.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = item_att["attempt"]["id"]
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="3.5")
        core.commit_evidence(att_id, evaluations=[{"topic_id": t_exp["id"], "skill_id": "exp_calc", "correct": True}])
        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)

        # 3. Check progress
        prog = core.assessment_progress(diag_id)

        # Assessment-specific coverage:
        # Bayes was NOT assessed in this diagnostic (unattempted/no items for it)
        assert prog["topic_coverage"]["Bayes"]["assessed"] is False
        assert prog["topic_coverage"]["Bayes"]["independent_successes"] == 0

        # Expectation WAS assessed in this diagnostic
        assert prog["topic_coverage"]["Expectation"]["assessed"] is True
        assert prog["topic_coverage"]["Expectation"]["independent_successes"] == 1

        # Course-wide topic coverage:
        # Both Bayes and Expectation have active evidence across the course
        assert prog["course_topic_coverage"]["Bayes"]["assessed"] is True
        assert prog["course_topic_coverage"]["Bayes"]["independent_successes"] == 2
        assert prog["course_topic_coverage"]["Expectation"]["assessed"] is True
        assert prog["course_topic_coverage"]["Expectation"]["independent_successes"] == 1
    finally:
        core.close()

