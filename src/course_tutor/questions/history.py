"""Learner-scoped history and append-only grades grounded in existing evidence policy."""

import json
import uuid

from ..errors import ValidationError
from ..learning.policy import get_required_subparts, is_evidence_eligible_for_performance
from ..models import compute_exercise_version_hash, utc_now_iso, validate_finite_number
from ..storage.repositories import AttemptRepository, EvidenceRepository, ExerciseRepository
from .catalog import page_size, require_text

SUCCESS = {"independent_mastery", "assisted_success"}


class QuestionHistory:
    def __init__(self, con):
        self.con = con
        self.attempts = AttemptRepository(con)
        self.exercises = ExerciseRepository(con)
        self.evidence = EvidenceRepository(con)

    def require_attempt(self, course_id, learner_id, attempt_id):
        require_text(learner_id, "learner_id")
        att = self.attempts.get_attempt(attempt_id)
        if not att or att.course_id != course_id or att.learner_id != learner_id:
            raise ValidationError("Attempt not found for this course and learner.")
        return att

    def source_occurrence(self, version_id):
        row = self.con.execute("""SELECT q.id,q.source_version_id,q.question_key,q.source_spans_json,
            c.exam_label,s.source_id,s.version_num,s.file_hash FROM question_occurrences q
            JOIN exam_catalogs c ON c.source_version_id=q.source_version_id
            JOIN source_versions s ON s.id=q.source_version_id WHERE q.exercise_version_id=?""", (version_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["source_spans"] = json.loads(result.pop("source_spans_json"))
        return result

    def eligible(self, version, evidence, learner_id):
        occurrence = self.con.execute("SELECT review_status FROM question_occurrences WHERE exercise_version_id=?", (version.id,)).fetchone()
        if occurrence and occurrence[0] != "accepted":
            return False
        return is_evidence_eligible_for_performance(
            evidence, len(version.revision_history) + 1,
            compute_exercise_version_hash(version.question_text, version.reference_solution, version.rubric, version.subparts),
            con=self.con, learner_id=learner_id)

    def grade_attempt(self, course_id, learner_id, attempt_id, expected_grade_revision,
                      points_awarded, max_points, feedback, evidence_ids, correction_reason="", allow_partial=False):
        att = self.require_attempt(course_id, learner_id, attempt_id)
        if att.mode != "practice":
            raise ValidationError("Use record-assessment-item-score for diagnostic attempts.")
        if type(expected_grade_revision) is not int or expected_grade_revision < 0:
            raise ValidationError("expected_grade_revision must be a non-negative integer.")
        if type(allow_partial) is not bool:
            raise ValidationError("allow_partial must be a boolean.")
        current = self.con.execute("SELECT COALESCE(MAX(revision),0) FROM attempt_grades WHERE attempt_id=?", (attempt_id,)).fetchone()[0]
        if current != expected_grade_revision:
            raise ValidationError(f"Stale grade revision: expected {expected_grade_revision}, current {current}.")
        require_text(feedback, "feedback")
        if current:
            require_text(correction_reason, "correction_reason")
        elif not isinstance(correction_reason, str):
            raise ValidationError("correction_reason must be a string.")
        points = validate_finite_number(points_awarded, "points_awarded", min_val=0)
        maximum = validate_finite_number(max_points, "max_points", min_val=0)
        if maximum <= 0 or points > maximum:
            raise ValidationError("Require 0 <= points_awarded <= max_points and max_points > 0.")
        version = self.exercises.get_exercise_version(att.exercise_version_id)
        if version.validation_state != "validated":
            raise ValidationError("Practice grading requires a validated exercise version.")
        if "max_points" in version.rubric and version.rubric["max_points"] != maximum:
            raise ValidationError("max_points must match the checked rubric.")
        if not isinstance(evidence_ids, list) or not evidence_ids or any(not isinstance(e, str) for e in evidence_ids) or len(set(evidence_ids)) != len(evidence_ids):
            raise ValidationError("evidence_ids must be a non-empty list of distinct evidence IDs.")
        evaluations = []
        for evidence_id in evidence_ids:
            evidence = self.evidence.get_evidence(evidence_id)
            if not evidence or evidence.attempt_id != attempt_id or not self.eligible(version, evidence, learner_id):
                raise ValidationError("Every grade must reference applicable evaluated evidence from this learner's attempt.")
            # Never silently score an old answer after a newer submission of that part.
            event = self.con.execute("SELECT event_index FROM attempt_events WHERE id=?", (evidence.event_id,)).fetchone()
            newer = self.con.execute("""SELECT 1 FROM attempt_events WHERE attempt_id=? AND event_type='work_submission'
                AND event_index>? AND (subpart_key IS NULL OR subpart_key='' OR subpart_key='default'
                OR ? IN ('', 'default') OR subpart_key=?) LIMIT 1""",
                (attempt_id, event[0], evidence.subpart_key, evidence.subpart_key)).fetchone()
            if newer:
                raise ValidationError("Evaluate the latest submitted work before grading this part.")
            evaluations.append(evidence)
        required = get_required_subparts(version.subparts)
        covered = {e.subpart_key for e in evaluations}
        # A caller may score only selected parts, but cannot omit unfavorable
        # current skill evaluations within those parts to manufacture full credit.
        applicable_rows = self.con.execute("""SELECT e.id FROM evidence e JOIN attempt_events s ON s.id=e.event_id
            WHERE e.attempt_id=? AND e.status='active' AND NOT EXISTS (
                SELECT 1 FROM attempt_events newer WHERE newer.attempt_id=e.attempt_id
                AND newer.event_type='work_submission' AND newer.event_index>s.event_index
                AND (newer.subpart_key IS NULL OR newer.subpart_key IN ('','default')
                     OR e.subpart_key IN ('','default') OR newer.subpart_key=e.subpart_key))""", (attempt_id,)).fetchall()
        for row in applicable_rows:
            ev = self.evidence.get_evidence(row["id"])
            if (ev.subpart_key in covered or "default" in covered or ev.subpart_key == "default") and self.eligible(version, ev, learner_id) and ev.id not in evidence_ids:
                raise ValidationError("Include all current evaluated skills for the parts being graded, including incorrect work.")
        complete = not required or required.issubset(covered)
        if not complete and not allow_partial:
            raise ValidationError("Required subparts are missing evaluated evidence; use allow_partial for an explicit partial grade.")
        levels = {e.demonstrated_level for e in evaluations}
        if points > 0 and not levels.intersection(SUCCESS | {"partial_progress"}):
            raise ValidationError("Positive points require positive evaluated work.")
        if points == 0 and "incorrect" not in levels:
            raise ValidationError("Zero points require evaluated incorrect work.")
        if points == maximum and (not complete or not levels.issubset(SUCCESS)):
            raise ValidationError("Full credit requires all required parts correctly evaluated.")
        correctness = "correct" if complete and levels.issubset(SUCCESS) else "incorrect" if levels == {"incorrect"} else "partial"
        grade_id = str(uuid.uuid4())
        self.con.execute("""INSERT INTO attempt_grades
            (id,attempt_id,revision,points_awarded,max_points,feedback,correctness,score_status,evidence_ids_json,correction_reason,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (grade_id, attempt_id, current + 1, points, maximum, feedback, correctness,
            "scored" if complete else "partially_scored", json.dumps(evidence_ids), correction_reason, utc_now_iso()))
        return {"grade_id": grade_id, "attempt_id": attempt_id, "revision": current + 1, "correctness": correctness,
                "score_status": "scored" if complete else "partially_scored", "points_awarded": points,
                "max_points": maximum, "feedback": feedback}

    def grade_record(self, row, version, learner_id):
        result = dict(row)
        result["evidence_ids"] = json.loads(result.pop("evidence_ids_json"))
        applicable = version.validation_state == "validated" and all(
            (ev := self.evidence.get_evidence(eid)) is not None and self.eligible(version, ev, learner_id)
            for eid in result["evidence_ids"])
        latest = self.con.execute("SELECT MAX(revision) FROM attempt_grades WHERE attempt_id=?", (row["attempt_id"],)).fetchone()[0]
        result["is_latest"] = row["revision"] == latest
        result["effective_status"] = (result["score_status"] if applicable else "pending_review") if result["is_latest"] else "superseded"
        result["evidence_still_applicable"] = applicable
        return result

    def summary(self, att):
        version = self.exercises.get_exercise_version(att.exercise_version_id)
        counts = {r["event_type"]: r["n"] for r in self.con.execute(
            "SELECT event_type,COUNT(*) n FROM attempt_events WHERE attempt_id=? GROUP BY event_type", (att.id,))}
        # Fetch only the latest applicable candidate per part/skill. A newer
        # ungraded submission must not inherit an older answer's correctness.
        candidates = self.con.execute("""SELECT id FROM (
            SELECT e.id,ROW_NUMBER() OVER (PARTITION BY e.subpart_key,e.skill_id ORDER BY s.event_index DESC,e.updated_at DESC,e.id DESC) n
            FROM evidence e JOIN attempt_events s ON s.id=e.event_id
            WHERE e.attempt_id=? AND e.status='active'
            AND NOT EXISTS (SELECT 1 FROM attempt_events newer WHERE newer.attempt_id=e.attempt_id
                AND newer.event_type='work_submission' AND newer.event_index>s.event_index
                AND (newer.subpart_key IS NULL OR newer.subpart_key IN ('','default')
                     OR e.subpart_key IN ('','default') OR newer.subpart_key=e.subpart_key))
            ) WHERE n=1""", (att.id,)).fetchall()
        latest = {}
        for row in candidates:
            e = self.evidence.get_evidence(row["id"])
            if self.eligible(version, e, att.learner_id):
                latest[(e.subpart_key, e.skill_id)] = e
        ever_graded = self.con.execute("""SELECT 1 FROM evidence WHERE attempt_id=?
            AND demonstrated_level IN ('independent_mastery','assisted_success','partial_progress','incorrect') LIMIT 1""", (att.id,)).fetchone() is not None
        needs_review = self.con.execute("SELECT 1 FROM evidence WHERE attempt_id=? AND status='pending_review' LIMIT 1", (att.id,)).fetchone() is not None
        levels = {e.demonstrated_level for e in latest.values()}
        required = get_required_subparts(version.subparts)
        complete = bool(latest) and (not required or required.issubset({e.subpart_key for e in latest.values()}))
        correct = complete and levels.issubset(SUCCESS)
        grade = self.con.execute("SELECT * FROM attempt_grades WHERE attempt_id=? ORDER BY revision DESC LIMIT 1", (att.id,)).fetchone()
        practice_grade = self.grade_record(grade, version, att.learner_id) if grade else None
        assessment = self.con.execute("SELECT id,assessment_id,points_awarded,max_points,score_status FROM assessment_items WHERE attempt_id=?", (att.id,)).fetchone()
        return {**att.to_dict(), "shown": bool(counts.get("question_presented")), "shown_count": counts.get("question_presented", 0),
                "answered": bool(counts.get("work_submission")), "submission_count": counts.get("work_submission", 0),
                "hint_count": counts.get("hint_given", 0), "solution_exposure_count": counts.get("solution_revealed", 0),
                "graded": ever_graded, "currently_graded": bool(latest), "answered_correctly": correct,
                "correctness": "correct" if correct else "ungraded" if not latest else "incorrect" if levels == {"incorrect"} else "partial",
                "needs_review": needs_review or bool(ever_graded and not latest) or bool(practice_grade and practice_grade["effective_status"] == "pending_review"),
                "latest_practice_grade": practice_grade, "assessment_score": dict(assessment) if assessment else None,
                "event_counts": counts}

    def question_history(self, course_id, learner_id, exercise_version_id, limit=20, after_id=""):
        page_size(limit)
        if not isinstance(after_id, str):
            raise ValidationError("after_id must be a string.")
        require_text(learner_id, "learner_id")
        version = self.exercises.get_exercise_version(exercise_version_id)
        if not version or version.course_id != course_id:
            raise ValidationError("Question version not found in this course.")
        rows = self.con.execute("""SELECT id FROM attempts WHERE course_id=? AND learner_id=? AND exercise_version_id=?
            AND id>? ORDER BY id LIMIT ?""", (course_id, learner_id, exercise_version_id, after_id, limit + 1)).fetchall()
        items = [self.summary(self.attempts.get_attempt(row["id"])) for row in rows[:limit]]
        return {"course_id": course_id, "learner_id": learner_id, "exercise_version_id": exercise_version_id,
                "question_source": self.source_occurrence(exercise_version_id),
                "attempts": items, "next_after_id": items[-1]["id"] if len(rows) > limit else None}

    def attempt_history(self, course_id, learner_id, attempt_id, limit=50, event_after=0, evidence_after=0, grade_after=0):
        page_size(limit)
        for value in (event_after, evidence_after, grade_after):
            if type(value) is not int or value < 0:
                raise ValidationError("History cursors must be non-negative integers.")
        att = self.require_attempt(course_id, learner_id, attempt_id)
        version = self.exercises.get_exercise_version(att.exercise_version_id)
        events = self.con.execute("SELECT * FROM attempt_events WHERE attempt_id=? AND event_index>? ORDER BY event_index LIMIT ?", (attempt_id, event_after, limit + 1)).fetchall()
        evidence = self.con.execute("SELECT rowid AS sequence,* FROM evidence WHERE attempt_id=? AND rowid>? ORDER BY rowid LIMIT ?", (attempt_id, evidence_after, limit + 1)).fetchall()
        grades = self.con.execute("SELECT * FROM attempt_grades WHERE attempt_id=? AND revision>? ORDER BY revision LIMIT ?", (attempt_id, grade_after, limit + 1)).fetchall()
        items = [dict(row) for row in events[:limit]]
        for item in items:
            item["metadata"] = json.loads(item.pop("event_metadata_json"))
        assessment = self.con.execute("SELECT score_history_json FROM assessment_items WHERE attempt_id=?", (attempt_id,)).fetchone()
        score_history = json.loads(assessment[0]) if assessment else []
        return {"summary": self.summary(att), "question_source": self.source_occurrence(att.exercise_version_id),
                "events": items, "evidence": [dict(row) for row in evidence[:limit]],
                "grades": [self.grade_record(row, version, learner_id) for row in grades[:limit]],
                "assessment_score_history": score_history[grade_after:grade_after + limit],
                "next_event_after": events[limit - 1]["event_index"] if len(events) > limit else None,
                "next_evidence_after": evidence[limit - 1]["sequence"] if len(evidence) > limit else None,
                "next_grade_after": grades[limit - 1]["revision"] if len(grades) > limit else None,
                "next_assessment_score_after": grade_after + limit if len(score_history) > grade_after + limit else None}
