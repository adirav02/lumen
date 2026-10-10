"""Diagnostic assessments with blueprints, exposure tracking, and transparent reporting."""

import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from ..errors import CourseNotFoundError, UnvalidatedQuestionError, ValidationError
from ..models import Assessment, AssessmentItem, ExerciseVersion, utc_now_iso
from ..storage.repositories import (
    AssessmentRepository,
    CourseRepository,
    EvidenceRepository,
    ExerciseRepository,
    TopicRepository,
)
from ..learning.service import LearningService


class DiagnosticService:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.course_repo = CourseRepository(con)
        self.assessment_repo = AssessmentRepository(con)
        self.exercise_repo = ExerciseRepository(con)
        self.evidence_repo = EvidenceRepository(con)
        self.topic_repo = TopicRepository(con)
        self.learning_service = LearningService(con)

    def create_assessment(
        self,
        course_id: str,
        title: str,
        blueprint: Dict[str, Any],
        selected_exercise_version_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a diagnostic assessment adhering to a topic blueprint and validated materials."""
        course = self.course_repo.get_course(course_id)
        if not course:
            raise CourseNotFoundError(course_id)

        assessment_id = str(uuid.uuid4())
        assessment = Assessment(
            id=assessment_id,
            course_id=course_id,
            title=title,
            blueprint=blueprint,
            status="open",
        )

        items: List[AssessmentItem] = []
        item_order = 1

        if selected_exercise_version_ids:
            for ex_ver_id in selected_exercise_version_ids:
                ex_ver = self.exercise_repo.get_exercise_version(ex_ver_id)
                if not ex_ver:
                    raise ValidationError(f"Exercise version '{ex_ver_id}' not found.")
                # F12: strictly disallow unvalidated or contradictory questions in diagnostic
                if ex_ver.validation_state != "validated":
                    raise UnvalidatedQuestionError(ex_ver_id, ex_ver.validation_state)

                # Prior exposure count
                ex_rec = self.exercise_repo.get_exercise(ex_ver.exercise_id)
                family = ex_rec.exercise_family if ex_rec else ex_ver_id
                exposure_count = self._get_family_exposure(course_id, family)

                item = AssessmentItem(
                    id=str(uuid.uuid4()),
                    assessment_id=assessment_id,
                    exercise_version_id=ex_ver_id,
                    item_order=item_order,
                    weight=1.0,
                    max_points=10.0,
                    exposure_count=exposure_count,
                )
                items.append(item)
                item_order += 1

        self.assessment_repo.create_assessment(assessment, items)

        return {
            "assessment_id": assessment_id,
            "title": title,
            "items_count": len(items),
            "blueprint": blueprint,
            "status": "open",
        }

    def start_assessment_item_attempt(
        self,
        assessment_id: str,
        item_order: int,
        learner_id: str = "default_learner",
    ) -> Dict[str, Any]:
        """Start a diagnostic attempt for a specific item in the assessment and link them."""
        assessment = self.assessment_repo.get_assessment(assessment_id)
        if not assessment:
            raise ValidationError(f"Assessment '{assessment_id}' not found.")

        item = self.assessment_repo.get_item_by_order(assessment_id, item_order)
        if not item:
            raise ValidationError(f"Item {item_order} not found in assessment '{assessment_id}'.")

        # Start attempt in diagnostic mode
        attempt = self.learning_service.start_attempt(
            course_id=assessment.course_id,
            exercise_version_id=item.exercise_version_id,
            learner_id=learner_id,
            mode="diagnostic",
        )

        # Link attempt to assessment item
        self.assessment_repo.update_item_progress(item.id, attempt_id=attempt.id)

        return {
            "assessment_id": assessment_id,
            "item_order": item_order,
            "attempt": attempt.to_dict(),
        }

    def record_assessment_item_score(
        self,
        assessment_id: str,
        item_order: int,
        points_awarded: float,
        attempt_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record rubric score for an assessment item without penalizing unattempted items as failures."""
        assessment = self.assessment_repo.get_assessment(assessment_id)
        if not assessment:
            raise ValidationError(f"Assessment '{assessment_id}' not found.")

        item = self.assessment_repo.get_item_by_order(assessment_id, item_order)
        if not item:
            raise ValidationError(f"Item {item_order} not found in assessment '{assessment_id}'.")

        if points_awarded < 0 or points_awarded > item.max_points:
            raise ValidationError(
                f"Points awarded {points_awarded} out of valid range [0, {item.max_points}]."
            )

        linked_attempt_id = attempt_id or item.attempt_id
        self.assessment_repo.update_item_progress(
            item.id,
            attempt_id=linked_attempt_id,
            points_awarded=points_awarded,
        )

        # Check if all items are completed
        all_items = self.assessment_repo.get_items(assessment_id)
        if all(it.points_awarded is not None or it.id == item.id for it in all_items):
            self.assessment_repo.update_assessment_status(assessment_id, "completed")

        return {
            "assessment_id": assessment_id,
            "item_order": item_order,
            "points_awarded": points_awarded,
            "max_points": item.max_points,
            "attempt_id": linked_attempt_id,
        }

    def _get_family_exposure(self, course_id: str, exercise_family: str) -> int:
        """Count how many attempts have occurred for this exercise family in the course."""
        row = self.con.execute(
            """
            SELECT COUNT(a.id) as cnt
            FROM attempts a
            JOIN exercise_versions ev ON a.exercise_version_id = ev.id
            JOIN exercises e ON ev.exercise_id = e.id
            WHERE a.course_id = ? AND e.exercise_family = ?
            """,
            (course_id, exercise_family),
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def get_progress(self, assessment_id: str) -> Dict[str, Any]:
        """Compute transparent progress report distinguishing observed score, coverage, and assistance.
        
        Reports transparent denominators without penalizing unattempted items as failures.
        """
        assessment = self.assessment_repo.get_assessment(assessment_id)
        if not assessment:
            raise ValidationError(f"Assessment '{assessment_id}' not found.")

        items = self.assessment_repo.get_items(assessment_id)
        total_items = len(items)
        items_scored = sum(1 for it in items if it.points_awarded is not None)
        items_attempted = sum(1 for it in items if it.points_awarded is not None or it.attempt_id is not None)
        items_unattempted = total_items - items_attempted

        total_possible_points = sum(it.max_points for it in items)
        attempted_possible_points = sum(it.max_points for it in items if it.points_awarded is not None)
        total_awarded_points = sum(it.points_awarded for it in items if it.points_awarded is not None)

        blueprint = assessment.blueprint
        required_topic_ids = blueprint.get("topic_ids", [])

        # Topic coverage analysis
        course_topics = {t.id: t for t in self.topic_repo.list_topics(assessment.course_id)}
        topic_coverage: Dict[str, Any] = {}

        for tid in required_topic_ids:
            t = course_topics.get(tid)
            t_name = t.name if t else tid
            state = self.evidence_repo.get_topic_state(assessment.course_id, tid)

            if state:
                topic_coverage[t_name] = {
                    "topic_id": tid,
                    "assessed": not state.unassessed_flag,
                    "independent_successes": state.independent_success_count,
                    "assisted_successes": state.assisted_success_count,
                    "partial_progress": state.partial_progress_count,
                    "errors": state.error_count,
                }
            else:
                topic_coverage[t_name] = {
                    "topic_id": tid,
                    "assessed": False,
                    "independent_successes": 0,
                    "assisted_successes": 0,
                    "partial_progress": 0,
                    "errors": 0,
                    "note": "Untested / missing evidence",
                }

        # Items details
        items_summary = []
        for it in items:
            ex_ver = self.exercise_repo.get_exercise_version(it.exercise_version_id)
            items_summary.append({
                "item_order": it.item_order,
                "exercise_version_id": it.exercise_version_id,
                "attempt_id": it.attempt_id,
                "question_preview": ex_ver.question_text[:80] if ex_ver else "",
                "max_points": it.max_points,
                "points_awarded": it.points_awarded,
                "completed": it.points_awarded is not None,
                "prior_exposure_count": it.exposure_count,
            })

        # Observed percentage is computed strictly on attempted/scored items to avoid treating unattempted items as failures
        observed_percentage = (
            round((total_awarded_points / attempted_possible_points * 100), 1)
            if attempted_possible_points > 0
            else 0.0
        )
        completion_percentage = (
            round((items_scored / total_items * 100), 1)
            if total_items > 0
            else 0.0
        )

        return {
            "assessment_id": assessment_id,
            "title": assessment.title,
            "status": assessment.status,
            "total_items": total_items,
            "completed_items": items_scored,
            "items_attempted": items_attempted,
            "items_unattempted": items_unattempted,
            "total_possible_points": total_possible_points,
            "attempted_possible_points": attempted_possible_points,
            "total_awarded_points": total_awarded_points,
            "observed_percentage": observed_percentage,
            "completion_percentage": completion_percentage,
            "topic_coverage": topic_coverage,
            "items": items_summary,
            "caveats": [
                "Score reflects observed rubric points on attempted items; not an exam pass probability.",
                "Unattempted items and untested topics are reported as unassessed rather than penalized as failures.",
            ],
        }
