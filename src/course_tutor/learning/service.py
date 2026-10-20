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
    ALLOWED_DEMONSTRATED_LEVELS,
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
    compute_exercise_version_hash,
)
from .policy import (
    check_evidence_eligibility_chain,
    determine_demonstrated_level,
    is_identity_resolved,
)



class LearningService:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.assessment_repo = AssessmentRepository(con)
        self.attempt_repo = AttemptRepository(con)
        self.exercise_repo = ExerciseRepository(con)
        self.evidence_repo = EvidenceRepository(con)
        self.topic_repo = TopicRepository(con)

    def _prior_family_assistance(self, attempt: Attempt, submission: AttemptEvent, subparts: set) -> set:
        """Earlier exposure survives retries and equivalent questions for this learner.

        The submission timestamp bounds the history, so later help cannot
        retroactively downgrade previously submitted independent work.
        """
        rows = self.con.execute(
            """SELECT e.event_type, e.subpart_key FROM attempt_events e
               JOIN attempts a ON a.id = e.attempt_id
               JOIN exercise_versions v ON v.id = a.exercise_version_id
               JOIN exercises x ON x.id = v.exercise_id
               WHERE a.course_id = ? AND a.learner_id = ? AND a.id != ?
                 AND e.created_at <= ? AND e.event_type IN ('hint_given', 'solution_revealed')
                 AND x.exercise_family = (
                     SELECT x2.exercise_family FROM exercise_versions v2
                     JOIN exercises x2 ON x2.id = v2.exercise_id WHERE v2.id = ?
                 )""",
            (attempt.course_id, attempt.learner_id, attempt.id, submission.created_at, attempt.exercise_version_id),
        ).fetchall()
        global_scope = not submission.subpart_key or "default" in subparts
        return {r["event_type"] for r in rows if global_scope or not r["subpart_key"]
                or r["subpart_key"] == "default" or r["subpart_key"] in subparts}

    def start_attempt(
        self,
        course_id: str,
        exercise_version_id: str,
        learner_id: str,
        mode: str = "practice",
    ) -> Attempt:
        """Start a new learner attempt with validation and cross-course enforcement."""
        if not isinstance(learner_id, str) or not learner_id.strip():
            raise ValidationError("learner_id must be a non-empty string.")
        if mode not in {"practice", "diagnostic"}:
            raise ValidationError("Attempt mode must be 'practice' or 'diagnostic'.")
        ex_ver = self.exercise_repo.get_exercise_version(exercise_version_id)
        if not ex_ver:
            raise ValidationError(f"Exercise version '{exercise_version_id}' not found.")

        # F19: Cross-course isolation check
        if ex_ver.course_id != course_id:
            raise CrossCourseViolationError("ExerciseVersion", exercise_version_id, course_id, ex_ver.course_id)

        # F12: If diagnostic, require validated status
        if mode == "diagnostic" and ex_ver.validation_state != "validated":
            raise UnvalidatedQuestionError(exercise_version_id, ex_ver.validation_state)

        current_revision = len(ex_ver.revision_history) + 1
        content_hash = compute_exercise_version_hash(
            ex_ver.question_text,
            ex_ver.reference_solution,
            ex_ver.rubric,
            ex_ver.subparts,
        )

        attempt = Attempt(
            id=str(uuid.uuid4()),
            course_id=course_id,
            exercise_version_id=exercise_version_id,
            learner_id=learner_id,
            mode=mode,
            status="open",
            current_revision=1,
            exercise_revision=current_revision,
            exercise_content_hash=content_hash,
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

            event_meta = dict(metadata or {})
            if event_type == "work_submission":
                # Authoritative educational identity derived from attempt; caller metadata cannot override
                event_meta["exercise_revision"] = attempt.exercise_revision
                event_meta["exercise_content_hash"] = attempt.exercise_content_hash


            event = AttemptEvent(
                id=str(uuid.uuid4()),
                attempt_id=attempt_id,
                course_id=attempt.course_id,
                event_index=next_idx,
                event_type=event_type,
                subpart_key=subpart_key,
                content=content,
                metadata=event_meta,
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

            ex_ver = self.exercise_repo.get_exercise_version(attempt.exercise_version_id)
            if not ex_ver:
                raise ValidationError(f"Exercise version '{attempt.exercise_version_id}' not found.")

            current_rev = len(ex_ver.revision_history) + 1
            current_hash = compute_exercise_version_hash(
                ex_ver.question_text,
                ex_ver.reference_solution,
                ex_ver.rubric,
                ex_ver.subparts,
            )

            if not is_identity_resolved(attempt.exercise_revision, attempt.exercise_content_hash):
                raise ValidationError(
                    f"Attempt '{attempt_id}' has unresolved educational identity. "
                    "Cannot resume attempt on exercise with unconfirmed identity. Start a fresh attempt."
                )

            if attempt.exercise_revision != current_rev or attempt.exercise_content_hash != current_hash:
                raise ValidationError(
                    f"Cannot resume stale attempt '{attempt_id}': attempt is for exercise revision {attempt.exercise_revision}, "
                    f"which does not match current revision {current_rev}. Start a fresh attempt for the updated exercise version."
                )

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
        if type(complete_attempt) is not bool:
            raise ValidationError("complete_attempt must be a boolean.")
        if not isinstance(evaluations, list) or any(not isinstance(e, dict) for e in evaluations):
            raise ValidationError("evaluations must be a list of objects.")
        with atomic_transaction(self.con):
            attempt = self.attempt_repo.get_attempt(attempt_id)
            if not attempt:
                raise ValidationError(f"Attempt '{attempt_id}' not found.")

            ex_ver = self.exercise_repo.get_exercise_version(attempt.exercise_version_id)
            if not ex_ver:
                raise ValidationError(f"Exercise version '{attempt.exercise_version_id}' not found.")
            current_rev = len(ex_ver.revision_history) + 1
            current_hash = compute_exercise_version_hash(
                ex_ver.question_text,
                ex_ver.reference_solution,
                ex_ver.rubric,
                ex_ver.subparts,
            )

            all_events = self.attempt_repo.list_events(attempt_id)
            created_evidence: List[EvidenceRecord] = []
            affected_topic_ids: set[str] = set()

            for ev_data in evaluations:
                provided_subpart = ev_data.get("subpart_key")
                topic_id = ev_data["topic_id"]
                skill_id = ev_data["skill_id"]
                self.topic_repo.require_course_topic(attempt.course_id, topic_id)

                # Defect 1: Validate demonstrated_level schema
                requested_level = ev_data.get("demonstrated_level")
                if requested_level is not None:
                    if requested_level not in ALLOWED_DEMONSTRATED_LEVELS:
                        raise ValidationError(
                            f"Invalid demonstrated_level '{requested_level}'. Allowed levels: {sorted(ALLOWED_DEMONSTRATED_LEVELS)}."
                        )

                # Strict boolean parsing
                try:
                    is_correct = parse_bool(ev_data.get("correct", False))
                    is_partial = parse_bool(ev_data.get("partial", False))
                except ValueError as err:
                    raise ValidationError(f"Invalid boolean in evaluation: {err}")

                if requested_level in {"independent_mastery", "assisted_success"} and not is_correct:
                    raise ValidationError("Positive demonstrated_level conflicts with correct=False.")
                if requested_level == "incorrect" and is_correct:
                    raise ValidationError("demonstrated_level='incorrect' conflicts with correct=True.")

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

                    if provided_subpart and provided_subpart != "default":
                        if submission_event.subpart_key and submission_event.subpart_key != "default" and submission_event.subpart_key != provided_subpart:
                            raise ValidationError(
                                f"Submission event subpart '{submission_event.subpart_key}' does not match evaluation subpart '{provided_subpart}'."
                            )
                        subpart_key = provided_subpart
                    else:
                        subpart_key = submission_event.subpart_key or "default"
                else:
                    if provided_subpart and provided_subpart != "default":
                        matching_submissions = [
                            e for e in all_events
                            if e.event_type == "work_submission"
                            and (e.subpart_key == provided_subpart or not e.subpart_key)
                            and e.content.strip()
                        ]
                        if not matching_submissions:
                            raise ValidationError(f"No committed work submission found for subpart '{provided_subpart}' in attempt '{attempt_id}'.")
                        submission_event = matching_submissions[-1]
                        subpart_key = provided_subpart
                    else:
                        matching_submissions = [
                            e for e in all_events
                            if e.event_type == "work_submission"
                            and e.content.strip()
                        ]
                        if not matching_submissions:
                            raise ValidationError(f"No committed work submission found in attempt '{attempt_id}'.")
                        submission_event = matching_submissions[-1]
                        subpart_key = submission_event.subpart_key or "default"

                # Defect 1 & 2: Reject evaluating submissions with unresolved or outdated identity
                sub_meta = submission_event.metadata or {}
                sub_rev = sub_meta.get("exercise_revision") if sub_meta.get("exercise_revision") is not None else attempt.exercise_revision
                sub_hash = sub_meta.get("exercise_content_hash") if sub_meta.get("exercise_content_hash") is not None else attempt.exercise_content_hash

                if not is_identity_resolved(sub_rev, sub_hash):
                    raise ValidationError(
                        f"Cannot evaluate submission with unresolved educational identity (revision={sub_rev}, content_hash={sub_hash}) against current exercise version."
                    )

                if sub_rev != current_rev:
                    raise ValidationError(
                        f"Cannot evaluate submission against outdated exercise revision: submission was for revision {sub_rev}, current revision is {current_rev}."
                    )
                if sub_hash != current_hash:
                    raise ValidationError(
                        "Cannot evaluate submission against outdated exercise content: submission content hash does not match current exercise version."
                    )


                caller_rev = ev_data.get("exercise_revision") or ev_data.get("expected_revision")
                if caller_rev is not None and caller_rev != current_rev:
                    raise ValidationError(
                        f"Evaluation expected revision {caller_rev} does not match current exercise revision {current_rev}."
                    )
                caller_hash = ev_data.get("exercise_content_hash") or ev_data.get("expected_content_hash")
                if caller_hash is not None and caller_hash != current_hash:
                    raise ValidationError(
                        "Evaluation expected content hash does not match current exercise version."
                    )

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
                    if (
                        subpart_key in (None, "", "default")
                        or not submission_event.subpart_key
                        or e.subpart_key in (subpart_key, submission_event.subpart_key)
                        or not e.subpart_key
                        or e.subpart_key in ("", "default")
                    )
                    and e.event_index <= submission_event.event_index
                ]

                prior = self._prior_family_assistance(attempt, submission_event, {subpart_key})
                has_solution = "solution_revealed" in prior or any(e.event_type == "solution_revealed" for e in subpart_assistance_events)
                has_hint = "hint_given" in prior or any(e.event_type == "hint_given" for e in subpart_assistance_events)

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
                    prior_assistance=bool(prior),
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
                    exercise_revision=sub_rev,
                    exercise_content_hash=sub_hash,
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
                if rep_level not in ALLOWED_DEMONSTRATED_LEVELS:
                    raise ValidationError(
                        f"Invalid demonstrated_level '{rep_level}'. Allowed levels: {sorted(ALLOWED_DEMONSTRATED_LEVELS)}."
                    )
                attempt_events = self.attempt_repo.list_events(old_ev.attempt_id)
                sub_event = next((e for e in attempt_events if e.id == old_ev.event_id), None)
                if not sub_event or sub_event.event_type != "work_submission":
                    raise ValidationError("Underlying evidence event is not a valid committed work_submission.")

                max_idx = sub_event.event_index
                rep_subpart = replacement.get("subpart_key")
                if not rep_subpart or rep_subpart == "default":
                    rep_subpart = sub_event.subpart_key or old_ev.subpart_key or "default"

                if (
                    sub_event.subpart_key
                    and sub_event.subpart_key != "default"
                    and rep_subpart != "default"
                    and rep_subpart != sub_event.subpart_key
                ):
                    raise ValidationError(
                        f"Replacement subpart '{rep_subpart}' does not match underlying submission subpart '{sub_event.subpart_key}'."
                    )

                # Prevent evading assistance checks by changing subpart metadata
                relevant_subparts = {old_ev.subpart_key, rep_subpart, sub_event.subpart_key}
                relevant_subparts.discard(None)
                relevant_subparts.discard("")
                has_default_subpart = "default" in relevant_subparts or not sub_event.subpart_key

                prior_events = [
                    e for e in attempt_events
                    if (
                        has_default_subpart
                        or e.subpart_key in relevant_subparts
                        or not e.subpart_key
                        or e.subpart_key in ("", "default")
                    )
                    and e.event_index <= max_idx
                ]
                has_solution = any(e.event_type == "solution_revealed" for e in prior_events)
                has_hint = any(e.event_type == "hint_given" for e in prior_events)
                attempt = self.attempt_repo.get_attempt(old_ev.attempt_id)
                prior = self._prior_family_assistance(attempt, sub_event, relevant_subparts) if attempt else set()
                has_solution = has_solution or "solution_revealed" in prior
                has_hint = has_hint or "hint_given" in prior

                if rep_level == "independent_mastery":
                    if has_solution:
                        raise ValidationError("Cannot assign 'independent_mastery' via correction when solution was revealed before submission.")
                    if has_hint:
                        raise ValidationError("Cannot assign 'independent_mastery' via correction when hint was given before submission.")

                ex_ver = self.exercise_repo.get_exercise_version(old_ev.exercise_version_id)
                current_rev = len(ex_ver.revision_history) + 1 if ex_ver else None
                current_hash = (
                    compute_exercise_version_hash(
                        ex_ver.question_text,
                        ex_ver.reference_solution,
                        ex_ver.rubric,
                        ex_ver.subparts,
                    )
                    if ex_ver
                    else None
                )
                if ex_ver is not None and current_rev is not None and current_hash is not None:
                    is_currently_applicable, _ = check_evidence_eligibility_chain(
                        self.con,
                        old_ev,
                        current_rev,
                        current_hash,
                    )
                else:
                    is_currently_applicable = False

                if is_currently_applicable:
                    target_status = "active"
                    target_rationale = replacement.get("rationale", f"Correction: {correction_reason}")
                else:
                    # Defect 2: A correction cannot make obsolete or unresolved evidence eligible for current performance!
                    target_status = "pending_review"
                    target_rationale = replacement.get(
                        "rationale",
                        f"Historical correction on obsolete/pending revision {old_ev.exercise_revision}: {correction_reason}",
                    )

                if replacement.get("topic_id"):
                    rep_t = self.topic_repo.get_topic(replacement["topic_id"])
                    if not rep_t or rep_t.course_id != old_ev.course_id:
                        raise CrossCourseViolationError(
                            "Topic",
                            replacement["topic_id"],
                            old_ev.course_id,
                            rep_t.course_id if rep_t else "unknown",
                        )

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
                    rationale=target_rationale,
                    status=target_status,
                    exercise_revision=old_ev.exercise_revision,
                    exercise_content_hash=old_ev.exercise_content_hash,
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

            # Follow corrections and retractions into linked assessment items (Defect 1 & Defect 2)
            affected_items = self.assessment_repo.get_items_by_attempt(old_ev.attempt_id)
            for item in affected_items:
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

