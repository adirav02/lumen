"""Course brief compiler providing compact session context, open attempts, and next actions."""

import sqlite3
from typing import Any, Dict, List

from ..errors import CourseNotFoundError
from ..storage.repositories import (
    AttemptRepository,
    CourseRepository,
    EvidenceRepository,
    ExerciseRepository,
    KnowledgeRepository,
    SourceRepository,
    TopicRepository,
)


def get_course_brief(
    con: sqlite3.Connection,
    course_id: str,
    learner_id: str = "default_learner",
) -> Dict[str, Any]:
    """Compile a compact, high-signal course brief without reloading full materials or history.

    Reports learner settings, open attempts, material coverage, missing syllabus topics, and next actions.
    """
    course_repo = CourseRepository(con)
    source_repo = SourceRepository(con)
    topic_repo = TopicRepository(con)
    knowledge_repo = KnowledgeRepository(con)
    attempt_repo = AttemptRepository(con)
    evidence_repo = EvidenceRepository(con)
    exercise_repo = ExerciseRepository(con)

    course = course_repo.get_course(course_id)
    if not course:
        raise CourseNotFoundError(course_id)

    settings = course_repo.get_or_create_learner_settings(course_id, learner_id)

    # 1. Open / Paused Attempt (for instant session resume)
    open_attempt = attempt_repo.get_open_attempt(course_id, learner_id)
    open_attempt_info = None
    if open_attempt:
        ex_ver = exercise_repo.get_exercise_version(open_attempt.exercise_version_id)
        open_attempt_info = {
            "attempt_id": open_attempt.id,
            "exercise_version_id": open_attempt.exercise_version_id,
            "status": open_attempt.status,
            "revision": open_attempt.current_revision,
            "started_at": open_attempt.started_at,
            "question_preview": ex_ver.question_text[:100] if ex_ver else "",
        }

    # 2. Source materials overview & extraction quality
    sources = source_repo.list_sources(course_id)
    sources_summary = []
    extraction_limitations = []

    for s in sources:
        versions = source_repo.list_source_versions(s.id)
        latest_ver = versions[-1] if versions else None
        if latest_ver:
            sources_summary.append({
                "logical_name": s.logical_name,
                "role": s.role,
                "version_num": latest_ver.version_num,
                "original_filename": latest_ver.original_filename,
                "extraction_status": latest_ver.extraction_status,
            })
            if latest_ver.extraction_notes:
                extraction_limitations.append(f"{s.logical_name}: {latest_ver.extraction_notes}")

    # 3. Topic coverage & missing syllabus content (F23)
    topics = topic_repo.list_topics(course_id)
    assessed_topics = []
    unassessed_topics = []
    topics_missing_materials = []

    for t in topics:
        # Check units linked to this topic
        linked_units = con.execute("SELECT COUNT(*) FROM unit_topics WHERE topic_id = ?", (t.id,)).fetchone()[0]
        if linked_units == 0:
            topics_missing_materials.append(t.name)

        state = evidence_repo.get_topic_state(course_id, t.id)
        if state and not state.unassessed_flag:
            assessed_topics.append({
                "name": t.name,
                "independent": state.independent_success_count,
                "assisted": state.assisted_success_count,
                "errors": state.error_count,
            })
        else:
            unassessed_topics.append(t.name)

    # 4. Useful next actions
    next_actions: List[Dict[str, Any]] = []
    if open_attempt:
        next_actions.append({
            "action": "resume_attempt",
            "description": f"Resume open attempt ({open_attempt.status}) on exercise {open_attempt.exercise_version_id}.",
            "params": {"attempt_id": open_attempt.id, "expected_revision": open_attempt.current_revision},
        })
    elif unassessed_topics:
        next_actions.append({
            "action": "practice_unassessed",
            "description": f"Practice unassessed topic: '{unassessed_topics[0]}'.",
            "params": {"topic_name": unassessed_topics[0]},
        })
    elif topics_missing_materials:
        next_actions.append({
            "action": "upload_material",
            "description": f"Upload materials for topic '{topics_missing_materials[0]}' (currently missing source content).",
            "params": {"topic_name": topics_missing_materials[0]},
        })
    else:
        next_actions.append({
            "action": "run_diagnostic",
            "description": "Run comprehensive diagnostic assessment to evaluate overall mastery.",
            "params": {"course_id": course_id},
        })

    return {
        "course": {
            "id": course.id,
            "name": course.name,
            "scope": course.scope,
            "default_language": course.default_language,
            "revision": course.revision,
        },
        "learner_settings": {
            "teaching_preference": settings.teaching_preference,
            "chosen_language": settings.chosen_language,
            "explicit_goals": settings.explicit_goals,
        },
        "open_attempt": open_attempt_info,
        "sources": sources_summary,
        "extraction_limitations": extraction_limitations,
        "coverage": {
            "total_topics": len(topics),
            "assessed_topics_count": len(assessed_topics),
            "assessed_topics": assessed_topics,
            "unassessed_topics_count": len(unassessed_topics),
            "unassessed_topics": unassessed_topics,
            "topics_missing_materials": topics_missing_materials,
        },
        "recommended_next_actions": next_actions,
    }
