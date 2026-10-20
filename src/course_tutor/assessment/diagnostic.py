"""Diagnostic assessments with blueprints, exposure tracking, and transparent reporting."""

import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from ..errors import CourseNotFoundError, CrossCourseViolationError, UnvalidatedQuestionError, ValidationError
from ..models import (
    Assessment,
    AssessmentItem,
    EVALUATED_DEMONSTRATED_LEVELS,
    OBSERVATION_DEMONSTRATED_LEVELS,
    utc_now_iso,
)
from ..storage.db import atomic_transaction
from ..storage.repositories import (
    AssessmentRepository,
    AttemptRepository,
    CourseRepository,
    EvidenceRepository,
    ExerciseRepository,
    TopicRepository,
    compute_exercise_version_hash,
)
from ..learning.policy import (
    are_all_required_subparts_evaluated,
    check_evidence_eligibility_chain,
    get_required_subparts,
    is_identity_resolved,
    validate_finite_number,
)
from ..learning.service import LearningService



class DiagnosticService:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.course_repo = CourseRepository(con)
        self.assessment_repo = AssessmentRepository(con)
        self.attempt_repo = AttemptRepository(con)
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
        learner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a diagnostic assessment adhering to a topic blueprint and validated materials."""
        course = self.course_repo.get_course(course_id)
        if not course:
            raise CourseNotFoundError(course_id)
        if blueprint is not None and not isinstance(blueprint, dict):
            raise ValidationError("Assessment blueprint must be an object.")
        if learner_id is not None and (not isinstance(learner_id, str) or not learner_id.strip()):
            raise ValidationError("learner_id must be a non-empty string.")

        assessment_id = str(uuid.uuid4())
        assessment = Assessment(
            id=assessment_id,
            course_id=course_id,
            title=title,
            blueprint=blueprint,
            learner_id=learner_id,
            status="open",
        )

        if blueprint and isinstance(blueprint, dict) and "topic_ids" in blueprint:
            for tid in blueprint.get("topic_ids", []):
                self.topic_repo.require_course_topic(course_id, tid)

        items: List[AssessmentItem] = []
        item_order = 1

        if selected_exercise_version_ids:
            if len(selected_exercise_version_ids) != len(set(selected_exercise_version_ids)):
                raise ValidationError("Duplicate exercise versions in selected_exercise_version_ids are not allowed.")

            for ex_ver_id in selected_exercise_version_ids:
                ex_ver = self.exercise_repo.get_exercise_version(ex_ver_id)
                if not ex_ver:
                    raise ValidationError(f"Exercise version '{ex_ver_id}' not found.")
                if ex_ver.course_id != course_id:
                    raise CrossCourseViolationError("ExerciseVersion", ex_ver_id, course_id, ex_ver.course_id)
                # F12: strictly disallow unvalidated or contradictory questions in diagnostic
                if ex_ver.validation_state != "validated":
                    raise UnvalidatedQuestionError(ex_ver_id, ex_ver.validation_state)
                review = self.con.execute('SELECT review_status,visual_review_status FROM question_occurrences WHERE exercise_version_id=?', (ex_ver_id,)).fetchone()
                if review and (review['review_status'] != 'accepted' or review['visual_review_status'] not in ('verified','not_required')):
                    raise ValidationError('Review source extraction and visual content before selecting this question for a diagnostic.')

                # Prior exposure count
                ex_rec = self.exercise_repo.get_exercise(ex_ver.exercise_id)
                family = ex_rec.exercise_family if ex_rec else ex_ver_id
                exposure_count = self._get_family_exposure(course_id, family)
                max_points = validate_finite_number(ex_ver.rubric.get("max_points", 10.0), "Rubric max_points", min_val=0.0)
                if max_points <= 0:
                    raise ValidationError("Rubric max_points must be positive.")

                item = AssessmentItem(
                    id=str(uuid.uuid4()),
                    assessment_id=assessment_id,
                    exercise_version_id=ex_ver_id,
                    item_order=item_order,
                    learner_id=learner_id,
                    weight=1.0,
                    max_points=max_points,
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
        """Start a diagnostic attempt for a specific item in the assessment and link them atomically (Defect 5)."""
        if not learner_id or not isinstance(learner_id, str) or not learner_id.strip():
            raise ValidationError(f"Invalid learner_id: {learner_id!r}")
        learner_id = learner_id.strip()

        if isinstance(item_order, bool) or not isinstance(item_order, int) or item_order < 1:
            raise ValidationError(f"Invalid item_order: {item_order!r}")

        with atomic_transaction(self.con):
            assessment = self.assessment_repo.get_assessment(assessment_id)
            if not assessment:
                raise ValidationError(f"Assessment '{assessment_id}' not found.")

            if assessment.learner_id and assessment.learner_id != learner_id:
                raise ValidationError(
                    f"Assessment '{assessment_id}' belongs to learner '{assessment.learner_id}', cannot start attempt for '{learner_id}'."
                )

            item = self.assessment_repo.get_item_by_order(assessment_id, item_order)
            if not item:
                raise ValidationError(f"Item {item_order} not found in assessment '{assessment_id}'.")

            if item.learner_id and item.learner_id != learner_id:
                raise ValidationError(
                    f"Assessment item {item_order} belongs to learner '{item.learner_id}', cannot start attempt for '{learner_id}'."
                )

            # Check that exercise version exists and is validated
            ex_ver = self.exercise_repo.get_exercise_version(item.exercise_version_id)
            if not ex_ver:
                raise ValidationError(f"Exercise version '{item.exercise_version_id}' not found.")
            if ex_ver.validation_state != "validated":
                raise UnvalidatedQuestionError(
                    item.exercise_version_id,
                    ex_ver.validation_state,
                    details={"reason": "Cannot start assessment item attempt for an exercise version that is pending review or unvalidated."},
                )

            source_review = self.con.execute(
                'SELECT review_status,visual_review_status FROM question_occurrences WHERE exercise_version_id=?',
                (item.exercise_version_id,),
            ).fetchone()
            if source_review and (source_review['review_status'] != 'accepted' or source_review['visual_review_status'] not in ('verified', 'not_required')):
                raise ValidationError('Source question extraction/visual review is pending; cannot start a diagnostic item.')

            current_rev = len(ex_ver.revision_history) + 1
            current_hash = compute_exercise_version_hash(
                ex_ver.question_text,
                ex_ver.reference_solution,
                ex_ver.rubric,
                ex_ver.subparts,
            )

            # Handle existing linked attempt (retry / resume / idempotency)
            if item.attempt_id:
                existing_attempt = self.attempt_repo.get_attempt(item.attempt_id)
                if (
                    existing_attempt
                    and existing_attempt.learner_id == learner_id
                    and (existing_attempt.exercise_revision is None or existing_attempt.exercise_revision == current_rev)
                    and (existing_attempt.exercise_content_hash is None or existing_attempt.exercise_content_hash == current_hash)
                ):
                    return {
                        "assessment_id": assessment_id,
                        "item_order": item_order,
                        "attempt": existing_attempt.to_dict(),
                        "resumed": True,
                    }

            # Atomically establish ownership on assessment if unset
            if not assessment.learner_id:
                self.assessment_repo.update_assessment_learner(assessment_id, learner_id)

            # Start attempt in diagnostic mode
            attempt = self.learning_service.start_attempt(
                course_id=assessment.course_id,
                exercise_version_id=item.exercise_version_id,
                learner_id=learner_id,
                mode="diagnostic",
            )

            # Link attempt to assessment item and record learner_id
            self.assessment_repo.update_item_progress(item.id, attempt_id=attempt.id, learner_id=learner_id)

            return {
                "assessment_id": assessment_id,
                "item_order": item_order,
                "attempt": attempt.to_dict(),
            }

    def link_assessment_item_attempt(
        self,
        assessment_id: str,
        item_order: int,
        attempt_id: str,
        learner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Explicitly and safely link or relink an attempt to an assessment item with full validation and audit tracking."""
        if isinstance(item_order, bool) or not isinstance(item_order, int) or item_order < 1:
            raise ValidationError(f"Invalid item order: {item_order!r}.")

        if learner_id is not None and (not isinstance(learner_id, str) or not learner_id.strip()):
            raise ValidationError(f"Learner ID must be a non-empty string, got {learner_id!r}.")

        with atomic_transaction(self.con):
            assessment = self.assessment_repo.get_assessment(assessment_id)
            if not assessment:
                raise ValidationError(f"Assessment '{assessment_id}' not found.")

            item = self.assessment_repo.get_item_by_order(assessment_id, item_order)
            if not item:
                raise ValidationError(f"Item {item_order} not found in assessment '{assessment_id}'.")

            attempt = self.attempt_repo.get_attempt(attempt_id)
            if not attempt:
                raise ValidationError(f"Attempt '{attempt_id}' not found.")

            if attempt.course_id != assessment.course_id:
                raise CrossCourseViolationError("Attempt", attempt_id, assessment.course_id, attempt.course_id)

            if attempt.exercise_version_id != item.exercise_version_id:
                raise ValidationError(
                    f"Attempt '{attempt_id}' exercise version '{attempt.exercise_version_id}' does not match assessment item {item_order} version '{item.exercise_version_id}'."
                )

            if attempt.mode != "diagnostic":
                raise ValidationError(f"Attempt '{attempt_id}' has mode '{attempt.mode}', expected 'diagnostic'.")

            # Defect 6: Check learner ownership - caller-supplied learner is an assertion, not an override
            if learner_id is not None:
                cleaned_caller_learner = learner_id.strip()
                if cleaned_caller_learner != attempt.learner_id:
                    raise ValidationError(
                        f"Caller-supplied learner '{cleaned_caller_learner}' does not match attempt owner '{attempt.learner_id}'."
                    )
            resolved_learner = attempt.learner_id
            if assessment.learner_id and assessment.learner_id != resolved_learner:
                raise ValidationError(f"Learner mismatch: assessment '{assessment.learner_id}' vs attempt '{resolved_learner}'.")
            if item.learner_id and item.learner_id != resolved_learner:
                raise ValidationError(f"Learner mismatch: item '{item.learner_id}' vs attempt '{resolved_learner}'.")

            # Ensure attempt is not linked to any other assessment item
            other = self.con.execute(
                "SELECT id FROM assessment_items WHERE attempt_id = ? AND id != ?",
                (attempt_id, item.id),
            ).fetchall()
            if other:
                raise ValidationError(f"Attempt '{attempt_id}' is already linked to another assessment item ({other[0]['id']}).")

            # Defect C: Reaffirming an unchanged link is an idempotent no-op.
            # Preserve score, history, evidence references, ownership, and status.
            if item.attempt_id == attempt_id:
                if not assessment.learner_id:
                    self.assessment_repo.update_assessment_learner(assessment_id, resolved_learner)
                return {
                    "assessment_id": assessment_id,
                    "item_order": item_order,
                    "attempt_id": attempt_id,
                    "learner_id": resolved_learner,
                    "reaffirmed": True,
                    "score_status": item.score_status,
                    "points_awarded": item.points_awarded,
                    "score_history": item.score_history,
                    "evidence_ids": item.evidence_ids,
                }

            # If item was scored, relinking invalidates the previous score
            score_history = list(item.score_history)
            if item.points_awarded is not None:
                history_entry = {
                    "points_awarded": None,
                    "previous_points": item.points_awarded,
                    "attempt_id": attempt_id,
                    "previous_attempt_id": item.attempt_id,
                    "action": "relinked_to_pending_review",
                    "reason": f"Item relinked from {item.attempt_id} to {attempt_id}",
                    "recorded_at": utc_now_iso(),
                }
                score_history.append(history_entry)

            if not assessment.learner_id:
                self.assessment_repo.update_assessment_learner(assessment_id, resolved_learner)

            self.assessment_repo.update_item_progress(
                item.id,
                attempt_id=attempt_id,
                points_awarded=None if item.points_awarded is not None else item.points_awarded,
                score_status="pending_review" if item.points_awarded is not None else item.score_status,
                score_history=score_history,
                evidence_ids=[] if item.points_awarded is not None else item.evidence_ids,
                learner_id=resolved_learner,
            )

            if item.points_awarded is not None:
                self.assessment_repo.update_assessment_status(assessment_id, "open")

            return {
                "assessment_id": assessment_id,
                "item_order": item_order,
                "attempt_id": attempt_id,
                "learner_id": resolved_learner,
            }

    def record_assessment_item_score(
        self,
        assessment_id: str,
        item_order: int,
        points_awarded: float,
        attempt_id: Optional[str] = None,
        allow_partial: bool = False,
    ) -> Dict[str, Any]:
        """Record rubric score for an assessment item requiring validated observed work and supporting evidence (Defect 1, 2, 4)."""
        points_num = validate_finite_number(points_awarded, "Points awarded", min_val=0.0)

        if not isinstance(allow_partial, bool):
            raise ValidationError(
                f"allow_partial must be a boolean (True or False), got {type(allow_partial).__name__} ({allow_partial!r})."
            )

        if isinstance(item_order, bool) or not isinstance(item_order, int) or item_order < 1:
            raise ValidationError(f"Invalid item order: {item_order!r}.")

        with atomic_transaction(self.con):
            assessment = self.assessment_repo.get_assessment(assessment_id)
            if not assessment:
                raise ValidationError(f"Assessment '{assessment_id}' not found.")

            item = self.assessment_repo.get_item_by_order(assessment_id, item_order)
            if not item:
                raise ValidationError(f"Item {item_order} not found in assessment '{assessment_id}'.")

            if points_num > item.max_points:
                raise ValidationError(
                    f"Points awarded {points_num} out of valid range [0, {item.max_points}]."
                )

            # If attempt_id is provided, it must match the persisted link
            if attempt_id is not None and attempt_id != item.attempt_id:
                raise ValidationError(
                    f"Attempt '{attempt_id}' does not match assessment item {item_order} linked attempt '{item.attempt_id}'."
                )

            # Defect 2: Require a persisted item-to-attempt link before scoring
            if not item.attempt_id:
                raise ValidationError(
                    f"Cannot award score for item {item_order} without an active, linked attempt. "
                    "Start and link an attempt via start_assessment_item_attempt before scoring."
                )

            linked_attempt_id = item.attempt_id

            # Verify no other assessment item is linked to this attempt
            conflict_rows = self.con.execute(
                "SELECT id, assessment_id, item_order FROM assessment_items WHERE attempt_id = ? AND id != ?",
                (linked_attempt_id, item.id),
            ).fetchall()
            if conflict_rows:
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' is already linked to another assessment item ({conflict_rows[0]['id']})."
                )

            attempt = self.attempt_repo.get_attempt(linked_attempt_id)
            if not attempt:
                raise ValidationError(f"Attempt '{linked_attempt_id}' not found.")

            # Validate course and exercise version
            if attempt.course_id != assessment.course_id:
                raise CrossCourseViolationError("Attempt", linked_attempt_id, assessment.course_id, attempt.course_id)

            if attempt.exercise_version_id != item.exercise_version_id:
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' exercise version '{attempt.exercise_version_id}' "
                    f"does not match assessment item {item_order} version '{item.exercise_version_id}'."
                )

            if attempt.mode != "diagnostic":
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' has mode '{attempt.mode}', expected 'diagnostic'."
                )

            # Defect 2: Require consistent, resolved learner ownership
            if not attempt.learner_id or not assessment.learner_id or not item.learner_id:
                raise ValidationError("Learner ownership must be resolved before scoring.")

            if attempt.learner_id != assessment.learner_id or attempt.learner_id != item.learner_id:
                raise ValidationError(
                    f"Learner mismatch: attempt learner '{attempt.learner_id}', assessment learner '{assessment.learner_id}', item learner '{item.learner_id}'."
                )

            # Recheck exercise version validation
            ex_ver = self.exercise_repo.get_exercise_version(item.exercise_version_id)
            if not ex_ver:
                raise ValidationError(f"Exercise version '{item.exercise_version_id}' not found.")
            if ex_ver.validation_state != "validated":
                raise UnvalidatedQuestionError(
                    item.exercise_version_id,
                    ex_ver.validation_state,
                    details={"reason": "Cannot record assessment score for an exercise version that is not validated."},
                )

            # Defect 2 & Defect 1: Educational identity check against current exercise version
            current_rev = len(ex_ver.revision_history) + 1
            current_hash = compute_exercise_version_hash(
                ex_ver.question_text,
                ex_ver.reference_solution,
                ex_ver.rubric,
                ex_ver.subparts,
            )

            if not is_identity_resolved(attempt.exercise_revision, attempt.exercise_content_hash):
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' has unresolved educational identity. Cannot score assessment item."
                )
            if attempt.exercise_revision != current_rev:
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' was performed on exercise revision {attempt.exercise_revision}, "
                    f"which does not match current revision {current_rev}."
                )
            if attempt.exercise_content_hash != current_hash:
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' content hash does not match current exercise version content hash."
                )

            # Require committed work submission
            events = self.attempt_repo.list_events(linked_attempt_id)
            work_submissions = [e for e in events if e.event_type == "work_submission" and e.content.strip()]
            if not work_submissions:
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' has no committed work submission with observed content. "
                    "Cannot award score without submitted learner work."
                )

            # Defect 1 & Defect 2: Authoritative active evaluated evidence check INSIDE transaction
            active_evidence = self.evidence_repo.list_evidence(
                course_id=assessment.course_id,
                attempt_id=linked_attempt_id,
                status="active",
            )
            submission_event_ids = {ws.id for ws in work_submissions}
            valid_evidence = [e for e in active_evidence if e.event_id in submission_event_ids]

            # Defect 1: Observation/unassessed evidence cannot support confirmed scores
            observation_evs = [e for e in valid_evidence if e.demonstrated_level in OBSERVATION_DEMONSTRATED_LEVELS]
            if observation_evs:
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' has evidence with unassessed/observation-only level: "
                    f"{[e.demonstrated_level for e in observation_evs]}. Confirmed scores cannot be supported by unassessed work."
                )

            # Defect A: Every confirmed score (including zero) requires active evaluated evidence
            evaluated_evidence = [e for e in valid_evidence if e.demonstrated_level in EVALUATED_DEMONSTRATED_LEVELS]
            if not evaluated_evidence:
                raise ValidationError(
                    f"Attempt '{linked_attempt_id}' has no active evaluated evidence linked to committed work submissions. "
                    "Cannot award score without valid active evaluated evidence."
                )

            for ev in evaluated_evidence:
                ok, reason = check_evidence_eligibility_chain(
                    self.con,
                    ev,
                    current_rev,
                    current_hash,
                    learner_id=attempt.learner_id,
                )
                if not ok:
                    raise ValidationError(
                        f"Evidence '{ev.id}' fails provenance eligibility chain: {reason}. Cannot support confirmed score."
                    )

            # Defect 1: Score vs evaluated evidence alignment
            has_positive_evidence = any(
                e.demonstrated_level in ("independent_mastery", "assisted_success", "partial_progress")
                for e in evaluated_evidence
            )
            has_incorrect_evidence = any(
                e.demonstrated_level == "incorrect"
                for e in evaluated_evidence
            )
            if points_num > 0 and not has_positive_evidence:
                raise ValidationError(
                    f"Cannot award positive points ({points_num}) when all evaluated evidence is incorrect."
                )

            if points_num == 0 and not has_incorrect_evidence:
                raise ValidationError(
                    "Cannot award zero points when all evaluated evidence is positive. Zero score requires evaluated incorrect work."
                )

            # Defect 4: Complete-item status requires all required rubric/subpart evaluation
            required_subparts = get_required_subparts(ex_ver.subparts)
            is_subparts_complete, missing_subparts = are_all_required_subparts_evaluated(required_subparts, evaluated_evidence)

            if not is_subparts_complete:
                if not allow_partial:
                    raise ValidationError(
                        f"Cannot score item: declared subparts missing evaluated evidence: {sorted(missing_subparts)}. "
                        "Complete all required subpart evaluations before recording score, or pass allow_partial=True for partial scoring."
                    )
                if points_num >= item.max_points and item.max_points > 0:
                    raise ValidationError(
                        f"Cannot award full credit ({points_num}/{item.max_points}) when required subparts are missing: {sorted(missing_subparts)}. "
                        "Full credit requires all required subparts to be completed and evaluated."
                    )
                score_status = "partially_scored"
            else:
                score_status = "scored"

            ev_ids = [e.id for e in evaluated_evidence]

            # Idempotent retry check
            if (
                item.score_status == score_status
                and item.points_awarded == float(points_num)
                and item.attempt_id == linked_attempt_id
                and set(item.evidence_ids) == set(ev_ids)
            ):
                return {
                    "assessment_id": assessment_id,
                    "item_order": item_order,
                    "points_awarded": float(points_num),
                    "max_points": item.max_points,
                    "score_status": score_status,
                    "completed": score_status == "scored",
                    "missing_subparts": sorted(missing_subparts) if not is_subparts_complete else [],
                    "score_history": item.score_history,
                    "attempt_id": linked_attempt_id,
                    "evidence_ids": item.evidence_ids,
                }

            # Build audit history entry
            history_entry = {
                "points_awarded": float(points_num),
                "previous_points": item.points_awarded,
                "attempt_id": linked_attempt_id,
                "evidence_ids": ev_ids,
                "score_status": score_status,
                "recorded_at": utc_now_iso(),
                "action": "score_recorded" if score_status == "scored" else "partial_score_recorded",
            }
            score_history = list(item.score_history) + [history_entry]

            self.assessment_repo.update_item_progress(
                item.id,
                attempt_id=linked_attempt_id,
                points_awarded=float(points_num),
                score_status=score_status,
                score_history=score_history,
                evidence_ids=ev_ids,
            )

            # Update assessment status: only completed when ALL items are fully scored
            all_items = self.assessment_repo.get_items(assessment_id)
            if all((it.points_awarded is not None and it.score_status == "scored") for it in all_items):
                self.assessment_repo.update_assessment_status(assessment_id, "completed")
            else:
                self.assessment_repo.update_assessment_status(assessment_id, "open")

            return {
                "assessment_id": assessment_id,
                "item_order": item_order,
                "points_awarded": float(points_num),
                "max_points": item.max_points,
                "score_status": score_status,
                "completed": score_status == "scored",
                "missing_subparts": sorted(missing_subparts) if not is_subparts_complete else [],
                "score_history": score_history,
                "attempt_id": linked_attempt_id,
                "evidence_ids": ev_ids,
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
        """Compute transparent progress report distinguishing observed score, coverage, assistance, and pending work.
        
        Preserves unanswered and unresolved items as unassessed without penalizing unattempted items as failures.
        """
        assessment = self.assessment_repo.get_assessment(assessment_id)
        if not assessment:
            raise ValidationError(f"Assessment '{assessment_id}' not found.")

        items = self.assessment_repo.get_items(assessment_id)
        total_items = len(items)

        items_scored = []
        items_pending = []
        items_unassessed = []

        total_awarded_points = 0.0
        attempted_possible_points = 0.0
        total_possible_points = sum(it.max_points for it in items)

        blueprint = assessment.blueprint or {}
        required_topic_ids = blueprint.get("topic_ids", [])
        course_topics = {t.id: t for t in self.topic_repo.list_topics(assessment.course_id)}
        topic_coverage = {}
        course_topic_coverage = {}

        # Collect active evidence specifically belonging to this assessment's attempted items (Defect 4, Defect 8)
        assessment_attempt_ids = {it.attempt_id for it in items if it.attempt_id}
        all_active_evs = self.evidence_repo.list_evidence(course_id=assessment.course_id, status="active")
        assessment_evs = [e for e in all_active_evs if e.attempt_id in assessment_attempt_ids]

        # Exercise version cache for identity validation (Defect 2 & Defect 3)
        ex_ver_cache: Dict[str, Optional[Tuple[int, str]]] = {}
        for it in items:
            if it.exercise_version_id not in ex_ver_cache:
                ex_row = self.exercise_repo.get_exercise_version(it.exercise_version_id)
                if ex_row:
                    c_rev = len(ex_row.revision_history) + 1
                    c_hash = compute_exercise_version_hash(
                        ex_row.question_text,
                        ex_row.reference_solution,
                        ex_row.rubric,
                        ex_row.subparts,
                    )
                    ex_ver_cache[it.exercise_version_id] = (c_rev, c_hash)
                else:
                    ex_ver_cache[it.exercise_version_id] = None

        items_summary = []
        for it in items:
            ex_ver = self.exercise_repo.get_exercise_version(it.exercise_version_id)
            is_scored = (it.score_status == "scored" and it.points_awarded is not None)

            classification = "unassessed"
            subpart_evals: Dict[str, str] = {}
            exposure_hints = 0
            exposure_solutions = 0
            assistance_after_submission = False

            if it.attempt_id:
                events = self.attempt_repo.list_events(it.attempt_id)
                exposure_hints = sum(1 for e in events if e.event_type == "hint_given")
                exposure_solutions = sum(1 for e in events if e.event_type == "solution_revealed")

                item_active_evs = [e for e in assessment_evs if e.attempt_id == it.attempt_id]
                if is_scored and it.evidence_ids:
                    item_active_evs = [e for e in item_active_evs if e.id in it.evidence_ids]

                ex_ident = ex_ver_cache.get(it.exercise_version_id)
                if ex_ident:
                    eligible_item_evs = []
                    for ev in item_active_evs:
                        ok, _ = check_evidence_eligibility_chain(
                            self.con,
                            ev,
                            ex_ident[0],
                            ex_ident[1],
                            learner_id=it.learner_id,
                        )
                        if ok:
                            eligible_item_evs.append(ev)
                    item_active_evs = eligible_item_evs
                else:
                    item_active_evs = []

                if item_active_evs:
                    subpart_levels = []
                    has_sol_before = False
                    for ev in item_active_evs:
                        sk = ev.subpart_key or "default"
                        subpart_evals[sk] = ev.demonstrated_level
                        subpart_levels.append(ev.demonstrated_level)

                        sub_ev = next((e for e in events if e.id == ev.event_id), None)
                        sub_idx = sub_ev.event_index if sub_ev else 999999
                        if any(e.event_type in ("hint_given", "solution_revealed") and e.event_index > sub_idx for e in events):
                            assistance_after_submission = True
                        if any(e.event_type == "solution_revealed" and e.event_index <= sub_idx for e in events):
                            has_sol_before = True

                    unique_levels = set(subpart_levels)
                    if not unique_levels or all(lvl in OBSERVATION_DEMONSTRATED_LEVELS for lvl in unique_levels):
                        classification = "unassessed"
                    elif unique_levels == {"independent_mastery"}:
                        classification = "independent"
                    elif unique_levels == {"assisted_success"}:
                        classification = "solution_revealed" if has_sol_before else "assisted"
                    elif "independent_mastery" in unique_levels and ("assisted_success" in unique_levels or "partial_progress" in unique_levels or "incorrect" in unique_levels):
                        classification = "mixed"
                    elif unique_levels == {"partial_progress"}:
                        classification = "partial_progress"
                    elif unique_levels == {"incorrect"}:
                        classification = "incorrect"
                    elif "assisted_success" in unique_levels:
                        classification = "solution_revealed" if has_sol_before else "assisted"
                    elif any(lvl in EVALUATED_DEMONSTRATED_LEVELS for lvl in unique_levels):
                        classification = "mixed"
                    else:
                        classification = "unassessed"
                else:
                    work_events = [e for e in events if e.event_type == "work_submission" and e.content.strip()]
                    if work_events:
                        classification = "unevaluated"
                    else:
                        classification = "unassessed"

            item_detail = {
                "item_order": it.item_order,
                "exercise_version_id": it.exercise_version_id,
                "attempt_id": it.attempt_id,
                "question_preview": ex_ver.question_text[:80] if ex_ver else "",
                "max_points": it.max_points,
                "points_awarded": it.points_awarded,
                "score_status": it.score_status,
                "score_history": it.score_history,
                "evidence_ids": it.evidence_ids,
                "completed": is_scored,
                "prior_exposure_count": it.exposure_count,
                "performance_classification": classification,
                "subpart_evaluations": subpart_evals,
                "exposure": {
                    "hints": exposure_hints,
                    "solutions": exposure_solutions,
                    "assistance_after_submission": assistance_after_submission,
                },
            }
            items_summary.append(item_detail)

            if is_scored:
                items_scored.append(item_detail)
                total_awarded_points += float(it.points_awarded)
                attempted_possible_points += it.max_points
            elif it.score_status in ("pending_review", "partially_scored"):
                items_pending.append(item_detail)
                if it.points_awarded is not None:
                    total_awarded_points += float(it.points_awarded)
                    attempted_possible_points += it.max_points
            else:
                items_unassessed.append(item_detail)

        # Assistance summary across attempts (Defect 4: derived from evaluated submissions)
        assistance_summary = {
            "independent_items_count": sum(1 for it_d in items_summary if it_d["performance_classification"] == "independent"),
            "assisted_items_count": sum(1 for it_d in items_summary if it_d["performance_classification"] == "assisted"),
            "solution_revealed_items_count": sum(1 for it_d in items_summary if it_d["performance_classification"] == "solution_revealed"),
            "mixed_items_count": sum(1 for it_d in items_summary if it_d["performance_classification"] == "mixed"),
            "unevaluated_items_count": sum(1 for it_d in items_summary if it_d["performance_classification"] == "unevaluated"),
            "unassessed_items_count": sum(1 for it_d in items_summary if it_d["performance_classification"] == "unassessed"),
        }

        for tid in required_topic_ids:
            t = course_topics.get(tid)
            t_name = t.name if t else tid

            # 1. Assessment-scoped topic coverage (Defect 3: active, evaluated, currently applicable evidence only)
            t_evaluated_evs = []
            for e in assessment_evs:
                if e.topic_id != tid:
                    continue
                if e.demonstrated_level not in EVALUATED_DEMONSTRATED_LEVELS:
                    continue
                if not is_identity_resolved(e.exercise_revision, e.exercise_content_hash):
                    continue
                ex_ident = ex_ver_cache.get(e.exercise_version_id)
                if ex_ident and e.exercise_revision == ex_ident[0] and e.exercise_content_hash == ex_ident[1]:
                    ok, _ = check_evidence_eligibility_chain(self.con, e, ex_ident[0], ex_ident[1])
                    if ok:
                        t_evaluated_evs.append(e)

            if t_evaluated_evs:
                topic_coverage[t_name] = {
                    "topic_id": tid,
                    "assessed": True,
                    "independent_successes": sum(1 for e in t_evaluated_evs if e.demonstrated_level == "independent_mastery"),
                    "assisted_successes": sum(1 for e in t_evaluated_evs if e.demonstrated_level == "assisted_success"),
                    "partial_progress": sum(1 for e in t_evaluated_evs if e.demonstrated_level == "partial_progress"),
                    "errors": sum(1 for e in t_evaluated_evs if e.demonstrated_level == "incorrect"),
                }
            else:
                topic_coverage[t_name] = {
                    "topic_id": tid,
                    "assessed": False,
                    "independent_successes": 0,
                    "assisted_successes": 0,
                    "partial_progress": 0,
                    "errors": 0,
                    "note": "Untested in this assessment / missing evidence",
                }

            # 2. Course-wide topic coverage
            state = self.evidence_repo.get_topic_state(assessment.course_id, tid)
            if state:
                course_topic_coverage[t_name] = {
                    "topic_id": tid,
                    "assessed": not state.unassessed_flag,
                    "independent_successes": state.independent_success_count,
                    "assisted_successes": state.assisted_success_count,
                    "partial_progress": state.partial_progress_count,
                    "errors": state.error_count,
                }
            else:
                course_topic_coverage[t_name] = {
                    "topic_id": tid,
                    "assessed": False,
                    "independent_successes": 0,
                    "assisted_successes": 0,
                    "partial_progress": 0,
                    "errors": 0,
                    "note": "Untested in course / missing evidence",
                }

        observed_percentage = (
            round((total_awarded_points / attempted_possible_points * 100), 1)
            if attempted_possible_points > 0
            else 0.0
        )
        completion_percentage = (
            round((len(items_scored) / total_items * 100), 1)
            if total_items > 0
            else 0.0
        )

        observed_scores = {
            "total_awarded_points": total_awarded_points,
            "attempted_possible_points": attempted_possible_points,
            "total_possible_points": total_possible_points,
            "observed_percentage": observed_percentage,
            "completed_items_count": len(items_scored),
        }

        pending_work = {
            "pending_review_items": items_pending,
            "unassessed_items": items_unassessed,
            "pending_count": len(items_pending),
            "unassessed_count": len(items_unassessed),
        }

        return {
            "assessment_id": assessment_id,
            "title": assessment.title,
            "status": assessment.status,
            "total_items": total_items,
            "completed_items": len(items_scored),
            "items_attempted": len(items_scored) + len(items_pending),
            "items_unattempted": len(items_unassessed),
            "total_possible_points": total_possible_points,
            "attempted_possible_points": attempted_possible_points,
            "total_awarded_points": total_awarded_points,
            "observed_percentage": observed_percentage,
            "completion_percentage": completion_percentage,
            "observed_scores": observed_scores,
            "coverage": topic_coverage,
            "topic_coverage": topic_coverage,
            "course_topic_coverage": course_topic_coverage,
            "assistance": assistance_summary,
            "pending_work": pending_work,
            "items": items_summary,
            "items_detail": items_summary,
            "caveats": [
                "Score reflects observed rubric points on attempted items; not an exam pass probability.",
                "Unattempted items and untested topics are reported as unassessed rather than penalized as failures.",
            ],
        }
