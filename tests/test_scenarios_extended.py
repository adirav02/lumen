"""Additional failure scenarios from implementation plan: F14, F17, F21, F22, F28, F29, F30."""

from pathlib import Path
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import ValidationError


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_f14_unreadable_submission_remains_pending(temp_workspace):
    """F14: When a student submission is unreadable or ambiguous, do not invent symbols; leave evidence pending."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f14")
        t = core.create_topic("prob-f14", name="Combinatorics", slug="comb")
        ex = core.create_exercise("prob-f14", "perm_1", "Calculate permutations")
        att = core.start_attempt("prob-f14", ex["exercise_version_id"])["data"]

        # Student submits an unreadable symbol or illegible image
        core.record_attempt_event(
            att["id"],
            expected_revision=1,
            event_type="work_submission",
            content="[Image with smudged exponent: 10^?]",
            metadata={"clarification_needed": True, "unreadable_region": "exponent"},
        )

        # Do not record fabricated grading; untouched evidence remains unassessed
        brief = core.course_brief("prob-f14")
        assert "Combinatorics" in brief["coverage"]["unassessed_topics"]
    finally:
        core.close()


def test_f17_transactional_rollback_preserves_consistency(temp_workspace):
    """F17: Crash or error during commit rolls back completely without half-applied projection."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f17")
        t = core.create_topic("prob-f17", name="Events", slug="events")
        ex = core.create_exercise("prob-f17", "events_1", "Define event")
        att = core.start_attempt("prob-f17", ex["exercise_version_id"])["data"]
        core.record_attempt_event(att["id"], expected_revision=1, event_type="work_submission", content="Sample subset")

        # Intentionally cause a foreign-key or validation failure inside evaluations
        with pytest.raises(Exception):
            core.commit_evidence(
                att["id"],
                evaluations=[{
                    "subpart_key": "a",
                    "topic_id": "nonexistent-topic-id",  # Invalid topic ID triggers FK violation or error
                    "skill_id": "event_def",
                    "correct": True,
                }],
            )

        # Database state remains consistent; no corrupted partial evidence
        state = core.learning_service.evidence_repo.get_topic_state("prob-f17", t["id"])
        assert state is None or state.unassessed_flag is True
    finally:
        core.close()


def test_f21_weak_topic_practice_does_not_mask_untested_coverage(temp_workspace):
    """F21: Repeated practice on weak topics leaves untested topics visible in coverage reports."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f21")
        t_weak = core.create_topic("prob-f21", name="Bayes Theorem", slug="bayes")
        t_untested = core.create_topic("prob-f21", name="Continuous Random Variables", slug="continuous")

        # Practice weak topic multiple times
        for i in range(3):
            ex = core.create_exercise("prob-f21", f"bayes_{i}", f"Bayes problem {i}")
            att = core.start_attempt("prob-f21", ex["exercise_version_id"])["data"]
            core.record_attempt_event(att["id"], expected_revision=1, event_type="work_submission", content="Answer")
            core.commit_evidence(att["id"], evaluations=[{"topic_id": t_weak["id"], "skill_id": "bayes_calc", "correct": True}])

        # Diagnostic blueprint spanning both topics
        diag = core.create_assessment(
            "prob-f21",
            "Comprehensive Diagnostic",
            blueprint={"topic_ids": [t_weak["id"], t_untested["id"]]},
        )["data"]

        prog = core.assessment_progress(diag["assessment_id"])
        # Coverage must clearly flag Continuous Random Variables as unassessed
        assert prog["topic_coverage"]["Continuous Random Variables"]["assessed"] is False
        assert prog["topic_coverage"]["Bayes Theorem"]["assessed"] is True
    finally:
        core.close()


def test_f22_exam_without_official_solution_flagged_pending_review(temp_workspace):
    """F22: Exam without verified official solution is flagged pending review and cannot silently alter diagnostic."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f22")
        t = core.create_topic("prob-f22", name="Expectation", slug="expectation")

        # Create exam question where reference solution is unverified / pending review
        unverified_ex = core.create_exercise(
            "prob-f22",
            "exam_2025_q3",
            "Past exam question with student-contributed solution",
            reference_solution="Unverified student answer",
            validation_state="pending_review",
        )

        # Cannot be used directly in validated diagnostic
        from course_tutor.errors import UnvalidatedQuestionError
        with pytest.raises(UnvalidatedQuestionError):
            core.create_assessment(
                "prob-f22",
                "Official Diagnostic",
                blueprint={"topic_ids": [t["id"]]},
                selected_exercise_version_ids=[unverified_ex["exercise_version_id"]],
            )
    finally:
        core.close()


def test_f28_visual_source_capability_advertised(temp_workspace):
    """F28: Capabilities report advertises visual vs text capabilities truthfully."""
    core = LumenCore(temp_workspace)
    try:
        caps = core.capabilities()
        extract_caps = caps["extraction_capabilities"]
        assert extract_caps["text_markdown"] is True
        assert extract_caps["pdf_text"] is True
        # OCR for scans is explicitly reported as false / unavailable without local tesseract
        assert extract_caps["ocr_scans"] is False
    finally:
        core.close()


def test_f29_empty_workspace_does_not_fabricate_prior_progress(temp_workspace):
    """F29: A new or recreated workspace has zero courses and does not invent progress."""
    core = LumenCore(temp_workspace)
    try:
        courses = core.course_repo.list_courses()
        assert len(courses) == 0
    finally:
        core.close()
