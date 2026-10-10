"""Dependency expansion ensuring all prerequisite definitions and mathematical assumptions are included."""

import sqlite3
from typing import Dict, List, Optional, Set

from ..errors import CrossCourseViolationError, ValidationError
from ..models import KnowledgeUnit
from ..storage.repositories import KnowledgeRepository


def expand_unit_dependencies(
    con: sqlite3.Connection,
    course_id: str,
    unit_ids: List[str],
    max_depth: Optional[int] = None,
) -> Dict[str, KnowledgeUnit]:
    """Given a list of unit IDs, transitively resolve all dependencies (prerequisite units).

    Ensures mathematical definitions and conditions required to apply theorems or formulas
    are never missing from the retrieved context (F02, F26).

    Traverses the complete dependency closure using cycle detection (visited set) without
    arbitrary depth caps. Rejects foreign-course units with CrossCourseViolationError,
    and detects ambiguous dependencies when multiple units share a referenced title.
    """
    repo = KnowledgeRepository(con)
    resolved: Dict[str, KnowledgeUnit] = {}
    to_visit: List[str] = list(unit_ids)
    visited: Set[str] = set()

    depth = 0
    while to_visit:
        if max_depth is not None and depth >= max_depth:
            break
        depth += 1
        current_batch = to_visit
        to_visit = []

        for uid in current_batch:
            if uid in visited:
                continue
            visited.add(uid)

            unit = repo.get_unit(uid)
            if unit:
                if unit.course_id != course_id:
                    raise CrossCourseViolationError("KnowledgeUnit", uid, course_id, unit.course_id)
            else:
                # Could be a title or slug referenced as a dependency
                # Find matching units in this course
                matching_in_course = [
                    u
                    for u in repo.list_units(course_id)
                    if u.title.strip().lower() == uid.strip().lower() or u.id == uid
                ]
                if len(matching_in_course) > 1:
                    matching_ids = [u.id for u in matching_in_course]
                    raise ValidationError(
                        f"Ambiguous dependency '{uid}' matches multiple units in course '{course_id}': {matching_ids}"
                    )
                elif len(matching_in_course) == 1:
                    unit = matching_in_course[0]
                else:
                    # Check if it exists in another course to prevent cross-course leakage
                    all_matching = repo.find_units_by_title(uid)
                    foreign = [u for u in all_matching if u.course_id != course_id]
                    if foreign:
                        raise CrossCourseViolationError(
                            "KnowledgeUnit", foreign[0].id, course_id, foreign[0].course_id
                        )
                    unit = None

            if unit:
                resolved[unit.id] = unit
                for dep in unit.dependencies:
                    if dep not in visited and dep not in to_visit:
                        to_visit.append(dep)

    return resolved
