"""Read-only, learner-scoped practice selection using recorded exposure and mistakes."""

import json
import sqlite3
from typing import Any, Dict, List, Optional

from ..errors import CourseNotFoundError, CrossCourseViolationError, ValidationError
from ..models import compute_exercise_version_hash
from ..questions.catalog import current_relations_sql
from ..storage.repositories import CourseRepository, ExerciseRepository, TopicRepository, ReservationRepository, AssemblyRepository


def propose_practice(
    con: sqlite3.Connection, course_id: str, learner_id: str = "default_learner", count: int = 1,
    topic_ids: Optional[List[str]] = None, exclude_exercise_version_ids: Optional[List[str]] = None,
    allow_repeats: bool = False, focus: str = "all", source_only: bool = False,
) -> Dict[str, Any]:
    """Proposals never create delivery, reservations, attempts or grades.

    Mistake focus intentionally revisits attempted families and requires explicit
    allow_repeats. Similarity candidates conservatively block accidental repeats;
    rejected or obsolete matches do not. Semantic novelty remains a review task.
    """
    if not CourseRepository(con).get_course(course_id):
        raise CourseNotFoundError(course_id)
    if not isinstance(learner_id, str) or not learner_id.strip():
        raise ValidationError("learner_id must be a non-empty string.")
    if type(count) is not int or not 1 <= count <= 100:
        raise ValidationError("count must be an integer between 1 and 100.")
    if type(allow_repeats) is not bool:
        raise ValidationError("allow_repeats must be a boolean.")
    if type(source_only) is not bool:
        raise ValidationError("source_only must be a boolean.")
    if focus not in ("all", "mistakes"):
        raise ValidationError("focus must be 'all' or 'mistakes'.")
    if focus == "mistakes" and not allow_repeats:
        raise ValidationError("Mistake-focused revisits require allow_repeats:true.")
    for name, value in (("topic_ids", topic_ids), ("exclude_exercise_version_ids", exclude_exercise_version_ids)):
        if value is not None and (not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value)):
            raise ValidationError(f"{name} must be a list of non-empty strings.")
    topics = TopicRepository(con)
    for tid in topic_ids or []:
        topics.require_course_topic(course_id, tid)
    local_topics = topics.list_topics(course_id)
    topic_lookup = {t.slug: t.id for t in local_topics}
    topic_lookup.update({t.id: t.id for t in local_topics})
    exercises = ExerciseRepository(con)
    for vid in exclude_exercise_version_ids or []:
        version = exercises.get_exercise_version(vid)
        if not version:
            raise ValidationError(f"Exercise version '{vid}' not found.")
        if version.course_id != course_id:
            raise CrossCourseViolationError("ExerciseVersion", vid, course_id, version.course_id)
    params = dict(course=course_id, learner=learner_id, repeats=int(allow_repeats),
                  excluded=json.dumps(exclude_exercise_version_ids or []), topics=json.dumps(topic_ids or []), focus=focus,
                  source_only=int(source_only))
    params["pending"] = json.dumps([r["exercise_version_id"] for r in
        AssemblyRepository(con).reservations(course_id) if r["learner_id"] == learner_id])
    # Filtering stays in SQLite. No full-bank reference solutions/rubrics are
    # materialized; only selected questions need their checked content identity.
    relations = current_relations_sql()
    query = """WITH exposure AS (
        SELECT exercise_version_id vid FROM attempts WHERE course_id=:course AND learner_id=:learner
        UNION SELECT i.exercise_version_id FROM assessment_items i JOIN assessments a ON a.id=i.assessment_id
            WHERE a.course_id=:course AND (a.learner_id=:learner OR a.learner_id IS NULL)
            AND """ + ReservationRepository.active_predicate("a.id") + """
        UNION SELECT value FROM json_each(:pending)
        ), excluded AS (SELECT value vid FROM json_each(:excluded)),
        related AS (""" + relations + """ WHERE r.course_id=:course AND r.status!='rejected'),
        rejected AS (""" + relations + """ WHERE r.course_id=:course AND r.status='rejected'),
        eligible AS (
        SELECT v.id, v.exercise_id,v.created_at,x.exercise_family,x.external_ref,f.exact_hash,f.structure_hash,
            (SELECT COUNT(*) FROM attempts a JOIN exercise_versions av ON av.id=a.exercise_version_id
             JOIN exercises ax ON ax.id=av.exercise_id WHERE a.course_id=:course AND a.learner_id=:learner
             AND ax.exercise_family=x.exercise_family) prior_attempts_in_family,
            (SELECT COUNT(*) FROM assessment_items i JOIN assessments a ON a.id=i.assessment_id
             JOIN exercise_versions av ON av.id=i.exercise_version_id JOIN exercises ax ON ax.id=av.exercise_id
             WHERE a.course_id=:course AND (a.learner_id=:learner OR a.learner_id IS NULL)
             AND ax.exercise_family=x.exercise_family) assessment_selections_in_family
        FROM exercise_versions v JOIN exercises x ON x.id=v.exercise_id
        LEFT JOIN question_fingerprints f ON f.exercise_version_id=v.id
        WHERE v.course_id=:course AND v.validation_state='validated' AND trim(x.exercise_family)!=''
        AND (:source_only=0 OR EXISTS (SELECT 1 FROM question_occurrences q
            JOIN source_versions sv ON sv.id=q.source_version_id
            WHERE q.exercise_version_id=v.id AND q.course_id=:course AND sv.course_id=:course
            AND q.review_status='accepted' AND q.visual_review_status IN ('verified','not_required')))
        AND NOT EXISTS (SELECT 1 FROM question_occurrences q WHERE q.exercise_version_id=v.id
            AND (q.review_status!='accepted' OR q.visual_review_status NOT IN ('verified','not_required')))
        AND (json_array_length(:topics)=0 OR EXISTS (
            SELECT 1 FROM json_each(v.topic_mappings_json) m JOIN topics t
            ON (t.id=m.value OR t.slug=m.value) AND t.course_id=:course JOIN json_each(:topics) wanted ON wanted.value=t.id))
        AND NOT EXISTS (SELECT 1 FROM excluded e JOIN exercise_versions ev ON ev.id=e.vid
            JOIN exercises ex ON ex.id=ev.exercise_id LEFT JOIN question_fingerprints ef ON ef.exercise_version_id=ev.id
            WHERE ex.exercise_family=x.exercise_family OR (ef.exact_hash=f.exact_hash)
            OR (ef.structure_hash=f.structure_hash AND NOT EXISTS (SELECT 1 FROM rejected r
                WHERE (r.left_version_id=v.id AND r.right_version_id=e.vid) OR (r.right_version_id=v.id AND r.left_version_id=e.vid)))
            OR EXISTS (SELECT 1 FROM related r WHERE (r.left_version_id=v.id AND r.right_version_id=e.vid)
                        OR (r.right_version_id=v.id AND r.left_version_id=e.vid)))
        AND (:repeats=1 OR NOT EXISTS (SELECT 1 FROM exposure e JOIN exercise_versions ev ON ev.id=e.vid
            JOIN exercises ex ON ex.id=ev.exercise_id LEFT JOIN question_fingerprints ef ON ef.exercise_version_id=ev.id
            WHERE ex.exercise_family=x.exercise_family OR ef.exact_hash=f.exact_hash
            OR (ef.structure_hash=f.structure_hash AND NOT EXISTS (SELECT 1 FROM rejected r
                WHERE (r.left_version_id=v.id AND r.right_version_id=e.vid) OR (r.right_version_id=v.id AND r.left_version_id=e.vid)))
            OR EXISTS (SELECT 1 FROM related r WHERE (r.left_version_id=v.id AND r.right_version_id=e.vid)
                        OR (r.right_version_id=v.id AND r.left_version_id=e.vid))))
        AND (:focus='all' OR EXISTS (
            SELECT 1 FROM evidence e JOIN attempts a ON a.id=e.attempt_id
            JOIN exercise_versions ev ON ev.id=e.exercise_version_id JOIN exercises ex ON ex.id=ev.exercise_id
            JOIN attempt_events se ON se.id=e.event_id
            WHERE e.course_id=:course AND a.learner_id=:learner AND ex.exercise_family=x.exercise_family
            AND e.status='active' AND ev.validation_state='validated' AND e.exercise_revision=a.exercise_revision
            AND e.exercise_content_hash=a.exercise_content_hash AND e.demonstrated_level IN ('incorrect','partial_progress')
            AND NOT EXISTS (SELECT 1 FROM evidence newer JOIN attempts na ON na.id=newer.attempt_id
                JOIN exercise_versions nv ON nv.id=newer.exercise_version_id JOIN exercises nx ON nx.id=nv.exercise_id
                JOIN attempt_events ns ON ns.id=newer.event_id
                WHERE na.learner_id=:learner AND newer.course_id=:course AND nx.exercise_family=x.exercise_family
                AND newer.status='active' AND nv.validation_state='validated' AND newer.exercise_revision=na.exercise_revision
                AND newer.exercise_content_hash=na.exercise_content_hash
                AND newer.skill_id=e.skill_id AND newer.subpart_key=e.subpart_key
                AND newer.demonstrated_level IN ('incorrect','partial_progress','independent_mastery','assisted_success')
                AND (ns.created_at>se.created_at OR (ns.created_at=se.created_at AND ns.id>se.id)))))
        ) SELECT * FROM (SELECT eligible.*,ROW_NUMBER() OVER (PARTITION BY exercise_family ORDER BY created_at,id) family_order FROM eligible)
          WHERE family_order=1 ORDER BY (prior_attempts_in_family+assessment_selections_in_family)>0,
            prior_attempts_in_family,assessment_selections_in_family,created_at,id"""
    selected, families, hashes, blocked, available = [], set(), set(), set(), 0
    selected_structures = {}
    for row in con.execute(query, params):
        if row["exercise_family"] in families or row["exact_hash"] in hashes or row["id"] in blocked:
            continue
        same_template = selected_structures.get(row["structure_hash"], [])
        if any(not con.execute(relations + " WHERE r.status='rejected' AND ((r.left_version_id=? AND r.right_version_id=?) OR (r.right_version_id=? AND r.left_version_id=?))",
            (row["id"], vid, row["id"], vid)).fetchone() for vid in same_template):
            continue
        families.add(row["exercise_family"])
        if row["exact_hash"]:
            hashes.add(row["exact_hash"])
        selected_structures.setdefault(row["structure_hash"], []).append(row["id"])
        # Avoid similar questions inside the proposed batch too. This bounded
        # adjacency query uses indexed endpoints, not a global all-pairs scan.
        for match in con.execute(relations + " WHERE r.course_id=? AND r.status!='rejected' AND (r.left_version_id=? OR r.right_version_id=?)", (course_id, row["id"], row["id"])):
            blocked.add(match["right_version_id"] if match["left_version_id"] == row["id"] else match["left_version_id"])
        available += 1
        version = exercises.get_exercise_version(row["id"])
        provenance = con.execute("""SELECT q.source_version_id,q.question_key,q.source_spans_json,
            sv.original_filename,sv.file_hash FROM question_occurrences q
            JOIN source_versions sv ON sv.id=q.source_version_id
            WHERE q.exercise_version_id=? AND q.course_id=? AND sv.course_id=?""",
            (row["id"], course_id, course_id)).fetchone()
        selected.append({"exercise_version_id": row["id"], "exercise_id": row["exercise_id"],
            "exercise_family": row["exercise_family"], "question_text": version.question_text,
            "source_reference": ({"source_version_id": provenance["source_version_id"],
                "question_key": provenance["question_key"], "source_spans": json.loads(provenance["source_spans_json"]),
                "original_filename": provenance["original_filename"], "file_hash": provenance["file_hash"]} if provenance else None),
            "topic_ids": sorted({topic_lookup[t] for t in version.topic_mappings if t in topic_lookup}),
            "external_ref": row["external_ref"], "expected_revision": len(version.revision_history) + 1,
            "expected_content_hash": compute_exercise_version_hash(version.question_text, version.reference_solution, version.rubric, version.subparts),
            "prior_attempts_in_family": row["prior_attempts_in_family"], "assessment_selections_in_family": row["assessment_selections_in_family"],
            "is_repeat_or_reserved": bool(row["prior_attempts_in_family"] or row["assessment_selections_in_family"])})
        if len(selected) == count:
            break
    return {"course_id": course_id, "learner_id": learner_id, "requested_count": count, "candidates": selected,
        "available_families": available, "available_families_is_lower_bound": len(selected) == count,
        "shortfall": max(0, count-len(selected)), "allow_repeats": allow_repeats,
        "focus": focus, "source_only": source_only, "recorded": False,
        "notes": ["Proposal only: no question was presented, attempted, scored or reserved by this call.",
                  "Exposure includes learner attempts and active learner/unowned assessment reservations; starting an attempt does not prove presentation.",
                  "Current exact matches and unrejected similarity candidates prevent accidental repetition; similarity is conservative and reviewable.",
                  "Mistake focus uses the latest applicable evaluation per recorded family/skill/subpart. External history and undetected paraphrases remain unknown."]}
