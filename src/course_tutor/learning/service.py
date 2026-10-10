"""Learner attempts, assistance tracking, evidence commitment, and state recomputation."""

import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from ..errors import (
    CrossCourseViolationError,
    StaleRevisionError,
    UnvalidatedQuestionError,
    ValidationError,
)
from ..models import (
    Attempt,
    AttemptEvent,
    EvidenceRecord,
    parse_bool,
    utc_now_iso,
)
from ..storage.db import atomic_transaction
from ..storage.repositories import (
    AssessmentRepository,
    AttemptRepository,
    EvidenceRepository,
    ExerciseRepository,
    TopicRepository,
)
from .policy import determine_demonstrated_level


class LearningService:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.assessment_repo = AssessmentRepository(con)
        self.attempt_repo = AttemptRepository(con)
        self.exercise_repo = ExerciseRepository(con)
        self.evidence_repo = EvidenceRepository(con)
        self.topic_repo = TopicRepository(con)

    def start_attempt(
        self,
        course_id: str,
        exercise_version_id: str,
        learner_id: str,
        mode: str = "practice",
    ) -> Attempt:
        """Start a new learner attempt with validation and cross-course enforcement."""
        ex_ver = self.exercise_repo.get_exercise_version(exercise_version_id)
        if not ex_ver:
            raise ValidationError(f"Exercise version '{exercise_version_id}' not found.")

        # F19: Cross-course isolation check
        if ex_ver.course_id != course_id:
            raise CrossCourseViolationError("ExerciseVersion", exercise_version_id, course_id, ex_ver.course_id)

        # F12: If diagnostic, require validated status
        if mode == "diagnostic" and ex_ver.validation_state != "validated":
            raise UnvalidatedQuestionError(exercise_version_id, ex_ver.validation_state)

        attempt = Attempt(
            id=str(uuid.uuid4()),
            course_id=course_id,
            exercise_version_id=exercise_version_id,
            learner_id=learner_id,
            mode=mode,
            status="open",
            current_revision=1,
        )
        return self.attempt_repo.create_attempt(attempt)

    def record_attempt_event(
        self,
        attempt_id: str,
        expected_revision: int,
        event_type: str,
        subpart_key: Optional[str] = None,
        content: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[AttemptEvent, int]:
        """Record an attempt event (submission, hint, solution exposure, pause) with revision control."""
        with atomic_transaction(self.con):
            attempt = self.attempt_repo.get_attempt(attempt_id)
            if not attempt:
                raise ValidationError(f"Attempt '{attempt_id}' not found.")

            # F18: Reject stale revisions
            if attempt.current_revision != expected_revision:
                raise StaleRevisionError("Attempt", attempt_id, expected_revision, attempt.current_revision)

            if event_type == "work_submission" and (not content or not content.strip()):
                raise ValidationError("work_submission event requires non-empty content.")

            existing_events = self.attempt_repo.list_events(attempt_id)
            next_idx = len(existing_events) + 1

            event = AttemptEvent(
                id=str(uuid.uuid4()),
                attempt_id=attempt_id,
                course_id=attempt.course_id,
                event_index=next_idx,
                event_type=event_type,
                subpart_key=subpart_key,
                content=content,
                metadata=metadata or {},
            )
            self.attempt_repo.add_event(event)

            # Update revision
            updated_attempt = self.attempt_repo.update_attempt(attempt, expected_revision)
            return event, updated_attempt.current_revision

    def pause_attempt(self, attempt_id: str, expected_revision: int) -> Attempt:
        """Pause open attempt without treating it as knowledge failure (F08)."""
        with atomic_transaction(self.con):
            attempt = self.attempt_repo.get_attempt(attempt_id)
            if not attempt:
                raise ValidationError(f"Attempt '{attempt_id}' not found.")
            attempt.status = "paused"
            return self.attempt_repo.update_attempt(attempt, expected_revision)

    def resume_attempt(self, attempt_id: str, expected_revision: int) -> Attempt:
        """Resume an open or paused attempt without creating a new independent attempt (F20)."""
        with atomic_transaction(self.con):
            attempt = self.attempt_repo.get_attempt(attempt_id)
            if not attempt:
                raise ValidationError(f"Attempt '{attempt_id}' not found.")
            attempt.status = "open"
            return self.attempt_repo.update_attempt(attempt, expected_revision)

    def commit_evidence(
        self,
        attempt_id: str,
        evaluations: List[Dict[str, Any]],
        complete_attempt: bool = False,
        submission_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Commit evidence for observed subparts and recompute topic projections deterministically.

        Respects assistance ordering (F07), partial credit (F09), and untouched subparts (F08).
        Ties each evaluation to a committed submission event and parses booleans strictly.
        Rejects duplicate evaluation without correction to prevent score inflation.
        """
        with atomic_transaction(self.con):
            attempt = self.attempt_repo.get_attempt(attempt_id)
            if not attempt:
                raise ValidationError(f"Attempt '{attempt_id}' not found.")

            all_events = self.attempt_repo.list_events(attempt_id)
            created_evidence: List[EvidenceRecord] = []
            affected_topic_ids: set[str] = set()

            for ev_data in evaluations:
                subpart_key = ev_data.get("subpart_key", "default")
                topic_id = ev_data["topic_id"]
                skill_id = ev_data["skill_id"]

                # Strict boolean parsing
                try:
                    is_correct = parse_bool(ev_data.get("correct", False))
                    is_partial = parse_bool(ev_data.get("partial", False))
                except ValueError as err:
                    raise ValidationError(f"Invalid boolean in evaluation: {err}")

                error_category = ev_data.get("error_category")
                rationale = ev_data.get("rationale", "")

                # Tie evaluation to a specific committed submission event
                submission_event = None
                sub_id = ev_data.get("submission_event_id") or submission_event_id
                if sub_id:
                    submission_event = next((e for e in all_events if e.id == sub_id), None)
                    if not submission_event:
                        raise ValidationError(f"Specified submission event '{sub_id}' not found in attempt.")
                    if submission_event.event_type != "work_submission":
                        raise ValidationError(
                            f"Event '{sub_id}' has type '{submission_event.event_type}', expected 'work_submission'."
                        )
                    if submission_event.attempt_id != attempt_id:
                        raise ValidationError(f"Event '{sub_id}' does not belong to attempt '{attempt_id}'.")
                    if submission_event.course_id != attempt.course_id:
                        raise CrossCourseViolationError("AttemptEvent", sub_id, attempt.course_id, submission_event.course_id)
                    if not submission_event.content or not submission_event.content.strip():
                        raise ValidationError(f"Submission event '{sub_id}' contains no observed work content.")
                    if submission_event.subpart_key and subpart_key != "default" and submission_event.subpart_key != subpart_key:
                        raise ValidationError(
                            f"Submission event subpart '{submission_event.subpart_key}' does not match evaluation subpart '{subpart_key}'."
                        )
                else:
                    # Find last work_submission for this subpart with observed content
                    matching_submissions = [
                        e for e in all_events
                        if e.event_type == "work_submission"
                        and (e.subpart_key == subpart_key or (not e.subpart_key and subpart_key == "default") or not e.subpart_key)
                        and e.content.strip()
                    ]
                    if matching_submissions:
                        submission_event = matching_submissions[-1]
                    else:
                        raise ValidationError(f"No committed work submission found for subpart '{subpart_key}' in attempt '{attempt_id}'.")

                # Reject duplicate active evaluation for the same (subpart_key, skill_id, submission_event)
                existing_active = [
                    e for e in self.evidence_repo.list_evidence(attempt.course_id, attempt_id=attempt_id, status="active")
                    if e.subpart_key == subpart_key and e.skill_id == skill_id and e.event_id == submission_event.id
                ]
                if existing_active:
                    raise ValidationError(
                        f"Active evidence already exists for attempt '{attempt_id}', subpart '{subpart_key}', skill '{skill_id}', event '{submission_event.id}'. "
                        "Use correct_evidence to supersede or retract existing evaluation."
                    )

                # Assistance events MUST be prior to or at the submission event!
                # Events after submission must NOT downgrade work submitted prior to assistance.
                subpart_assistance_events = [
                    e for e in all_events
                    if (e.subpart_key == subpart_key or not e.subpart_key or not submission_event.subpart_key)
                    and e.event_index <= submission_event.event_index
                ]

                requested_level = ev_data.get("demonstrated_level")
                has_solution = any(e.event_type == "solution_revealed" for e in subpart_assistance_events)
                has_hint = any(e.event_type == "hint_given" for e in subpart_assistance_events)

                if requested_level == "independent_mastery":
                    if has_solution:
                        raise ValidationError("Cannot award 'independent_mastery' when solution was revealed before submission.")
                    if has_hint:
                        raise ValidationError("Cannot award 'independent_mastery' when hint was given before submission.")

                has_arithmetic_only = (error_category == "arithmetic" and is_partial)
                auto_level = determine_demonstrated_level(
                    submitted_correct=is_correct,
                    events_for_subpart=subpart_assistance_events,
                    is_partial_progress=is_partial,
                    has_arithmetic_error_only=has_arithmetic_only,
                )
                demonstrated_level = requested_level or auto_level

                ev_rec = EvidenceRecord(
                    id=str(uuid.uuid4()),
                    course_id=attempt.course_id,
                    attempt_id=attempt.id,
                    event_id=submission_event.id,
                    exercise_version_id=attempt.exercise_version_id,
                    topic_id=topic_id,
                    skill_id=skill_id,
                    subpart_key=subpart_key,
                    demonstrated_level=demonstrated_level,
                    error_category=error_category,
                    rationale=rationale,
                    status="active",
                )
                self.evidence_repo.create_evidence(ev_rec)
                created_evidence.append(ev_rec)
                affected_topic_ids.add(topic_id)

            # Recompute topic states deterministically
            updated_states = {}
            for tid in affected_topic_ids:
                state = self.evidence_repo.recompute_topic_state(attempt.course_id, tid)
                updated_states[tid] = state.to_dict()

            if complete_attempt:
                attempt.status = "completed"
                attempt.completed_at = utc_now_iso()
                self.attempt_repo.update_attempt(attempt, attempt.current_revision)

            return {
                "attempt_id": attempt_id,
                "evidence_created": [e.to_dict() for e in created_evidence],
                "affected_topic_states": updated_states,
            }

    def correct_evidence(
        self,
        evidence_id: str,
        correction_reason: str,
        replacement: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Retract or supersede evidence when tutor or rubric was wrong (F11).

        Maintains full audit trail while recomputing active topic states deterministically.
        Ensures tutor corrections cannot bypass assistance history.
        Updates linked assessment scores according to documented policy.
        """
        with atomic_transaction(self.con):
            old_ev = self.evidence_repo.get_evidence(evidence_id)
            if not old_ev:
                raise ValidationError(f"Evidence record '{evidence_id}' not found.")

            if replacement:
                rep_level = replacement.get("demonstrated_level")
                attempt_events = self.attempt_repo.list_events(old_ev.attempt_id)
                sub_event = next((e for e in attempt_events if e.id == old_ev.event_id), None)
                if not sub_event or sub_event.event_type != "work_submission":
                    raise ValidationError("Underlying evidence event is not a valid committed work_submission.")

                max_idx = sub_event.event_index
                rep_subpart = replacement.get("subpart_key", old_ev.subpart_key)

                # Prevent evading assistance checks by changing subpart metadata
                prior_events = [
                    e for e in attempt_events
                    if (e.subpart_key in (old_ev.subpart_key, rep_subpart, sub_event.subpart_key) or not e.subpart_key)
                    and e.event_index <= max_idx
                ]
                has_solution = any(e.event_type == "solution_revealed" for e in prior_events)
                has_hint = any(e.event_type == "hint_given" for e in prior_events)

                if rep_level == "independent_mastery":
                    if has_solution:
                        raise ValidationError("Cannot assign 'independent_mastery' via correction when solution was revealed before submission.")
                    if has_hint:
                        raise ValidationError("Cannot assign 'independent_mastery' via correction when hint was given before submission.")

                new_rec = EvidenceRecord(
                    id=str(uuid.uuid4()),
                    course_id=old_ev.course_id,
                    attempt_id=old_ev.attempt_id,
                    event_id=old_ev.event_id,
                    exercise_version_id=old_ev.exercise_version_id,
                    topic_id=replacement.get("topic_id", old_ev.topic_id),
                    skill_id=replacement.get("skill_id", old_ev.skill_id),
                    subpart_key=rep_subpart,
                    demonstrated_level=replacement["demonstrated_level"],
                    error_category=replacement.get("error_category"),
                    rationale=replacement.get("rationale", f"Correction: {correction_reason}"),
                    status="active",
                )
                resulting_ev = self.evidence_repo.supersede_evidence(evidence_id, new_rec, correction_reason)
            else:
                resulting_ev = self.evidence_repo.retract_evidence(evidence_id, correction_reason)

            # Recompute affected topic projections
            affected_topics = {old_ev.topic_id}
            if replacement and replacement.get("topic_id"):
                affected_topics.add(replacement["topic_id"])

            recomputed_states = {}
            for tid in affected_topics:
                state = self.evidence_repo.recompute_topic_state(old_ev.course_id, tid)
                recomputed_states[tid] = state.to_dict()

            # Follow corrections and retractions into linked assessment items (Defect 2)
            item = self.assessment_repo.get_item_by_attempt(old_ev.attempt_id)
            if item and item.points_awarded is not None:
                history_entry = {
                    "points_awarded": None,
                    "previous_points": item.points_awarded,
                    "attempt_id": old_ev.attempt_id,
                    "evidence_id": evidence_id,
                    "action": "retracted_to_pending_review" if not replacement else "superseded_to_pending_review",
                    "reason": correction_reason,
                    "recorded_at": utc_now_iso(),
                }
                score_history = list(item.score_history) + [history_entry]
                self.assessment_repo.update_item_progress(
                    item.id,
                    attempt_id=item.attempt_id,
                    points_awarded=None,
                    score_status="pending_review",
                    score_history=score_history,
                    evidence_ids=[],
                )
                self.assessment_repo.update_assessment_status(item.assessment_id, "open")

            return {
                "status": "success",
                "original_evidence_id": evidence_id,
                "action": "superseded" if replacement else "retracted",
                "correction_reason": correction_reason,
                "resulting_evidence": resulting_ev.to_dict(),
                "recomputed_topic_states": recomputed_states,
            }

