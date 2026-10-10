"""Tests for attempts, assistance ordering, evidence commitments, corrections, and diagnostics.

Covers failure scenarios: F07, F08, F09, F10, F11, F12, F13, F20, F21.
"""

from pathlib import Path
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import UnvalidatedQuestionError


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
