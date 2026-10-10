"""Tests for attempts, assistance ordering, evidence commitments, corrections, and diagnostics.

Covers failure scenarios: F07, F08, F09, F10, F11, F12, F13, F20, F21.
"""

from pathlib import Path
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import UnvalidatedQuestionError, ValidationError


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_f07_correct_answer_after_solution_classified_as_assisted(temp_workspace):
    """F07: A correct answer submitted after solution exposure is classified as assisted, not independent mastery."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f07")
        t = core.create_topic("prob-f07", name="Bayes Rule", slug="bayes")
        topic_id = t["id"]

        ex = core.create_exercise("prob-f07", "bayes_family_1", "Calculate P(Disease | Positive test)")
        ex_ver_id = ex["exercise_version_id"]

        att = core.start_attempt("prob-f07", ex_ver_id)["data"]
        att_id = att["id"]

        # Step 1: Learner requests and receives solution
        core.record_attempt_event(att_id, expected_revision=1, event_type="solution_request")
        core.record_attempt_event(att_id, expected_revision=2, event_type="solution_revealed", content="P = 0.08")

        # Step 2: Learner submits correct answer
        core.record_attempt_event(att_id, expected_revision=3, event_type="work_submission", content="Final answer is 0.08")

        # Step 3: Tutor evaluates as correct
        eval_res = core.commit_evidence(att_id, evaluations=[{
            "subpart_key": "default",
            "topic_id": topic_id,
            "skill_id": "bayes_calculation",
            "correct": True,
            "partial": False,
        }])["data"]

        ev = eval_res["evidence_created"][0]
        # F07: Must be assisted_success, NEVER independent_mastery!
        assert ev["demonstrated_level"] == "assisted_success"

        # Topic state must increment assisted count, NOT independent count
        state = eval_res["affected_topic_states"][topic_id]
        assert state["independent_success_count"] == 0
        assert state["assisted_success_count"] == 1
    finally:
        core.close()


def test_f08_pause_preserves_subpart_evidence_untouched_unassessed(temp_workspace):
    """F08: Pausing after one correct subpart preserves its evidence; untouched parts remain unassessed."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f08")
        t1 = core.create_topic("prob-f08", name="Expectation", slug="expectation")
        t2 = core.create_topic("prob-f08", name="Variance", slug="variance")

        ex = core.create_exercise(
            "prob-f08",
            "exp_var_family",
            "Problem: (a) Find E[X]; (b) Find Var(X)",
            subparts=[{"key": "a", "prompt": "E[X]"}, {"key": "b", "prompt": "Var(X)"}],
        )
        att = core.start_attempt("prob-f08", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        # Learner submits subpart (a) independently and correctly
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", subpart_key="a", content="E[X] = 3.5")
        core.commit_evidence(att_id, evaluations=[{
            "subpart_key": "a",
            "topic_id": t1["id"],
            "skill_id": "expectation_calc",
            "correct": True,
        }])

        # Learner pauses due to fatigue
        pause_res = core.pause_attempt(att_id, expected_revision=2)["data"]
        assert pause_res["status"] == "paused"

        # Check topic states
        brief = core.course_brief("prob-f08")
        # Topic 1 has active evidence
        t1_state = [t for t in brief["coverage"]["assessed_topics"] if t["name"] == "Expectation"]
        assert len(t1_state) == 1
        assert t1_state[0]["independent"] == 1

        # Topic 2 (subpart b) was not touched and must remain in unassessed_topics!
        assert "Variance" in brief["coverage"]["unassessed_topics"]
    finally:
        core.close()


def test_f09_f13_partial_credit_for_arithmetic_error(temp_workspace):
    """F09 & F13: Correct method with arithmetic mistake is recorded as partial progress, not failure."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f09")
        t = core.create_topic("prob-f09", name="Total Probability", slug="total-prob")
        topic_id = t["id"]

        ex = core.create_exercise("prob-f09", "law_total_prob", "Calculate P(B)")
        att = core.start_attempt("prob-f09", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        # Method is completely correct: 0.3 * 0.5 + 0.7 * 0.2, but student computes 0.15 + 0.14 = 0.31 instead of 0.29
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="P(B) = 0.3*0.5 + 0.7*0.2 = 0.31")

        eval_res = core.commit_evidence(att_id, evaluations=[{
            "subpart_key": "default",
            "topic_id": topic_id,
            "skill_id": "law_of_total_probability",
            "correct": False,
            "partial": True,
            "error_category": "arithmetic",
            "rationale": "Correct application of law of total probability, but 0.15 + 0.14 arithmetic sum was miscalculated.",
        }])["data"]

        ev = eval_res["evidence_created"][0]
        assert ev["demonstrated_level"] == "partial_progress"
        assert ev["error_category"] == "arithmetic"

        # Topic projection reflects partial progress and error breakdown
        state = eval_res["affected_topic_states"][topic_id]
        assert state["partial_progress_count"] == 1
        assert state["summary_data"]["error_breakdown"]["arithmetic"] == 1
    finally:
        core.close()


def test_f10_repeated_family_exposure_tracked(temp_workspace):
    """F10: Repeated question family attempts track exposure count."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f10")
        t = core.create_topic("prob-f10", name="Poisson", slug="poisson")

        # Two exercises in the same family
        ex1 = core.create_exercise("prob-f10", "poisson_call_center", "Poisson lambda=3, P(X=1)")
        ex2 = core.create_exercise("prob-f10", "poisson_call_center", "Poisson lambda=3, P(X=2)")

        # Attempt first variant
        att1 = core.start_attempt("prob-f10", ex1["exercise_version_id"])["data"]
        core.record_attempt_event(att1["id"], expected_revision=1, event_type="work_submission", content="0.149")
        core.commit_evidence(att1["id"], evaluations=[{"topic_id": t["id"], "skill_id": "poisson_pmf", "correct": True}])

        # Create diagnostic containing second variant
        diag = core.create_assessment("prob-f10", "Poisson Test", blueprint={"topic_ids": [t["id"]]}, selected_exercise_version_ids=[ex2["exercise_version_id"]])["data"]
        prog = core.assessment_progress(diag["assessment_id"])

        # Prior exposure for family 'poisson_call_center' must be >= 1
        assert prog["items"][0]["prior_exposure_count"] >= 1
    finally:
        core.close()


def test_f11_tutor_correction_retracts_and_recomputes_state(temp_workspace):
    """F11: Tutor error correction retracts invalid evidence and recomputes topic state without erasing history."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f11")
        t = core.create_topic("prob-f11", name="Bayes", slug="bayes")
        topic_id = t["id"]

        ex = core.create_exercise("prob-f11", "bayes_1", "Calculate P(A|B)")
        att = core.start_attempt("prob-f11", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        # Student gave a correct alternate form: 1 - P(A^c | B)
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="1 - P(A^c | B)")

        # Tutor initially made a mistake and marked it incorrect
        eval_res = core.commit_evidence(att_id, evaluations=[{
            "subpart_key": "default",
            "topic_id": topic_id,
            "skill_id": "bayes_rule",
            "correct": False,
            "partial": False,
            "rationale": "Expected formula ratio.",
        }])["data"]
        ev_id = eval_res["evidence_created"][0]["id"]

        # Topic state initially reflects error
        state1 = eval_res["affected_topic_states"][topic_id]
        assert state1["error_count"] == 1
        assert state1["independent_success_count"] == 0

        # Tutor realizes student's answer was mathematically valid; issue correction
        corr_res = core.correct_evidence(
            evidence_id=ev_id,
            correction_reason="Complement rule 1 - P(A^c|B) is mathematically equivalent to P(A|B).",
            replacement={
                "topic_id": topic_id,
                "skill_id": "bayes_rule",
                "demonstrated_level": "independent_mastery",
                "rationale": "Complement rule is valid.",
            },
        )["data"]

        assert corr_res["action"] == "superseded"

        # Topic state is recomputed deterministically: error count drops to 0, independent success increments to 1
        recomputed = corr_res["recomputed_topic_states"][topic_id]
        assert recomputed["error_count"] == 0
        assert recomputed["independent_success_count"] == 1
    finally:
        core.close()


def test_f12_diagnostic_rejects_unvalidated_questions(temp_workspace):
    """F12: Diagnostic creation rejects unvalidated or contradictory questions."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f12")
        t = core.create_topic("prob-f12", name="Independence", slug="independence")

        # Create question marked as contradictory / pending review
        bad_ex = core.create_exercise(
            "prob-f12",
            "bad_indep",
            "P(A)=0.8, P(B)=0.7, A and B disjoint and independent (contradiction!)",
            validation_state="contradictory",
        )

        with pytest.raises(UnvalidatedQuestionError) as exc_info:
            core.create_assessment(
                "prob-f12",
                "Diagnostic",
                blueprint={"topic_ids": [t["id"]]},
                selected_exercise_version_ids=[bad_ex["exercise_version_id"]],
            )

        assert exc_info.value.error_code == "UNVALIDATED_QUESTION"
    finally:
        core.close()


def test_f20_session_resume_without_full_transcript(temp_workspace):
    """F20: Reopening workspace retrieves open attempt directly without reloading full transcript."""
    core1 = LumenCore(temp_workspace)
    try:
        core1.create_course("Probability", course_id="prob-f20")
        ex = core1.create_exercise("prob-f20", "coin_toss", "Toss coin 3 times")
        att = core1.start_attempt("prob-f20", ex["exercise_version_id"], learner_id="student_42")["data"]
        att_id = att["id"]

        core1.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Sample space has 8 outcomes")
        core1.pause_attempt(att_id, expected_revision=2)
    finally:
        core1.close()

    # Brand new session / agent instance opens workspace
    core2 = LumenCore(temp_workspace)
    try:
        brief = core2.course_brief("prob-f20", learner_id="student_42")
        open_att = brief["open_attempt"]
        assert open_att is not None
        assert open_att["attempt_id"] == att_id
        assert open_att["status"] == "paused"
        assert open_att["revision"] == 3

        # Immediate resume
        resume_res = core2.resume_attempt(att_id, expected_revision=open_att["revision"])["data"]
        assert resume_res["status"] == "open"
        assert resume_res["current_revision"] == 4
    finally:
        core2.close()


def test_evidence_committed_submission_anchoring(temp_workspace):
    """Verify evaluations tie to committed submissions: assistance after submission does not downgrade prior work."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-anchor")
        t = core.create_topic("prob-anchor", name="Independence", slug="indep")

        ex = core.create_exercise("prob-anchor", "indep_ex", "Prove A and B independent", validation_state="validated")
        att = core.start_attempt("prob-anchor", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        # Step 1: Student submits independent work
        sub1 = core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="P(A∩B)=P(A)P(B)")["data"]
        sub1_id = sub1["event"]["id"]

        # Step 2: Later, tutor gives a general hint or solution for something else
        core.record_attempt_event(att_id, expected_revision=2, event_type="hint_given", content="Hint for followup")

        # Step 3: Evaluate sub1. Because the hint occurred AFTER sub1, sub1 remains independent_mastery!
        res = core.commit_evidence(att_id, evaluations=[{
            "submission_event_id": sub1_id,
            "topic_id": t["id"],
            "skill_id": "indep_proof",
            "correct": "true",
        }])["data"]

        ev = res["evidence_created"][0]
        assert ev["demonstrated_level"] == "independent_mastery"
        assert res["affected_topic_states"][t["id"]]["independent_success_count"] == 1
    finally:
        core.close()


def test_strict_boolean_parsing(temp_workspace):
    """Verify parse_bool accepts clean booleans and rejects ambiguous string representations."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-bool")
        t = core.create_topic("prob-bool", name="Bayes", slug="bayes")
        ex = core.create_exercise("prob-bool", "bayes_bool", "Question")
        att = core.start_attempt("prob-bool", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Answer")

        # Rejects ambiguous string like "maybe"
        with pytest.raises(ValidationError):
            core.commit_evidence(att_id, evaluations=[{
                "topic_id": t["id"],
                "skill_id": "skill_1",
                "correct": "maybe",
            }])

        # Accepts "true" string
        eval_res = core.commit_evidence(att_id, evaluations=[{
            "topic_id": t["id"],
            "skill_id": "skill_1",
            "correct": "true",
            "partial": "false",
        }])["data"]
        assert eval_res["evidence_created"][0]["demonstrated_level"] == "independent_mastery"
    finally:
        core.close()


def test_duplicate_evaluation_rejection_prevents_inflation(temp_workspace):
    """Verify re-evaluating the same attempt item without correction is rejected to prevent score inflation."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-dup")
        t = core.create_topic("prob-dup", name="Bayes", slug="bayes")
        ex = core.create_exercise("prob-dup", "bayes_dup", "Question")
        att = core.start_attempt("prob-dup", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Answer")

        # First evaluation succeeds
        core.commit_evidence(att_id, evaluations=[{
            "topic_id": t["id"],
            "skill_id": "bayes_skill",
            "correct": True,
        }])

        # Second evaluation on the same attempt/skill/subpart without correction raises ValidationError
        with pytest.raises(ValidationError) as exc_info:
            core.commit_evidence(att_id, evaluations=[{
                "topic_id": t["id"],
                "skill_id": "bayes_skill",
                "correct": True,
            }])
        assert "active evidence already exists" in str(exc_info.value).lower()
    finally:
        core.close()


def test_tutor_correction_cannot_bypass_assistance_history(temp_workspace):
    """Verify tutor correction cannot award independent mastery if a solution was revealed before submission."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-corr")
        t = core.create_topic("prob-corr", name="Bayes", slug="bayes")
        ex = core.create_exercise("prob-corr", "bayes_corr", "Question")
        att = core.start_attempt("prob-corr", ex["exercise_version_id"])["data"]
        att_id = att["id"]

        # Solution revealed before submission
        core.record_attempt_event(att_id, expected_revision=1, event_type="solution_revealed", content="Answer is 0.5")
        core.record_attempt_event(att_id, expected_revision=2, event_type="work_submission", content="Answer is 0.5")

        eval_res = core.commit_evidence(att_id, evaluations=[{
            "topic_id": t["id"],
            "skill_id": "bayes_rule",
            "correct": True,
        }])["data"]
        ev_id = eval_res["evidence_created"][0]["id"]
        assert eval_res["evidence_created"][0]["demonstrated_level"] == "assisted_success"

        # Attempt to correct to independent_mastery must fail
        with pytest.raises(ValidationError) as exc_info:
            core.correct_evidence(
                evidence_id=ev_id,
                correction_reason="Tutor wants to mark as independent",
                replacement={
                    "topic_id": t["id"],
                    "skill_id": "bayes_rule",
                    "demonstrated_level": "independent_mastery",
                },
            )
        assert "cannot assign 'independent_mastery'" in str(exc_info.value).lower()
    finally:
        core.close()


def test_assessment_scoring_lifecycle_and_transparent_reporting(temp_workspace):
    """Verify complete diagnostic lifecycle: item attempt, submission, scoring, and non-penalizing denominators."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-diag-flow")
        t = core.create_topic("prob-diag-flow", name="Expectation", slug="exp")

        ex1 = core.create_exercise("prob-diag-flow", "exp_1", "Compute E[X] for fair die", validation_state="validated")
        ex2 = core.create_exercise("prob-diag-flow", "exp_2", "Compute E[X^2] for fair die", validation_state="validated")

        diag = core.create_assessment(
            "prob-diag-flow",
            "Expectation Diagnostic",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex1["exercise_version_id"], ex2["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # Item 1: Start item attempt via diagnostic service
        item1_att = core.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = item1_att["attempt"]["id"]
        assert item1_att["attempt"]["mode"] == "diagnostic"

        # Submit work and evaluate item 1
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="E[X] = 3.5")
        core.commit_evidence(att_id, evaluations=[{
            "topic_id": t["id"],
            "skill_id": "expected_value",
            "correct": True,
        }])

        # Record rubric score (8.5 out of 10.0 points)
        score_res = core.record_assessment_item_score(diag_id, item_order=1, points_awarded=8.5, attempt_id=att_id)
        assert score_res["points_awarded"] == 8.5

        # Check progress: 1 of 2 items completed.
        # Observed percentage on attempted items is 85% (8.5 / 10.0), NOT 42.5% (8.5 / 20.0)!
        prog = core.assessment_progress(diag_id)
        assert prog["total_items"] == 2
        assert prog["completed_items"] == 1
        assert prog["items_unattempted"] == 1
        assert prog["total_awarded_points"] == 8.5
        assert prog["attempted_possible_points"] == 10.0
        assert prog["total_possible_points"] == 20.0
        assert prog["observed_percentage"] == 85.0
        assert prog["completion_percentage"] == 50.0
    finally:
        core.close()
