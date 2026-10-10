"""Dependency expansion ensuring all prerequisite definitions and mathematical assumptions are included."""

import sqlite3
from typing import Dict, List, Optional, Set

from ..errors import CrossCourseViolationError, ValidationError
from ..models import KnowledgeUnit
from ..storage.repositories import KnowledgeRepository


class ClosureResult(dict):
    """Result of dependency expansion mapping unit_id to KnowledgeUnit.

    Includes closure completeness flags and lists of unresolved dependencies or missing roots.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unresolved_dependencies: List[str] = []
        self.missing_roots: List[str] = []
        self.cycle_detected: bool = False
        self.closure_complete: bool = True


def expand_unit_dependencies(
    con: sqlite3.Connection,
    course_id: str,
    unit_ids: List[str],
    max_depth: Optional[int] = None,
) -> ClosureResult:
    """Given a list of unit IDs, transitively resolve all dependencies (prerequisite units).

    Ensures mathematical definitions and conditions required to apply theorems or formulas
    are never missing from the retrieved context (F02, F26).

    Traverses the complete dependency closure using cycle detection (visited set) without
    arbitrary depth caps. Rejects foreign-course units with CrossCourseViolationError,
    detects ambiguous dependencies when multiple units share a referenced title,
    and explicitly records unresolved dependencies and missing roots.
    """
    repo = KnowledgeRepository(con)
    resolved: Dict[str, KnowledgeUnit] = {}
    unresolved: List[str] = []
    missing_roots: List[str] = []
    cycle_detected: bool = False
    visited: Set[str] = set()

    # Phase 1: Resolve roots
    to_visit: List[str] = []
    for uid in unit_ids:
        unit = repo.get_unit(uid)
        if unit:
            if unit.course_id != course_id:
                raise CrossCourseViolationError("KnowledgeUnit", uid, course_id, unit.course_id)
            resolved[unit.id] = unit
            visited.add(unit.id)
            for dep in unit.dependencies:
                if dep not in visited and dep not in to_visit:
                    to_visit.append(dep)
        else:
            # Check by title/slug in this course
            matching = [
                u for u in repo.list_units(course_id)
                if u.title.strip().lower() == uid.strip().lower() or u.id == uid
            ]
            if len(matching) > 1:
                matching_ids = [u.id for u in matching]
                raise ValidationError(
                    f"Ambiguous dependency '{uid}' matches multiple units in course '{course_id}': {matching_ids}"
                )
            elif len(matching) == 1:
                unit = matching[0]
                resolved[unit.id] = unit
                visited.add(unit.id)
                for dep in unit.dependencies:
                    if dep not in visited and dep not in to_visit:
                        to_visit.append(dep)
            else:
                # Check if it exists in another course
                foreign = [u for u in repo.find_units_by_title(uid) if u.course_id != course_id]
                if foreign:
                    raise CrossCourseViolationError("KnowledgeUnit", foreign[0].id, course_id, foreign[0].course_id)
                missing_roots.append(uid)

    # Phase 2: Transitive traversal
    depth = 0
    while to_visit:
        if max_depth is not None and depth >= max_depth:
            break
        depth += 1
        current_batch = to_visit
        to_visit = []

        for dep_ref in current_batch:
            if dep_ref in visited:
                cycle_detected = True
                continue
            visited.add(dep_ref)

            unit = repo.get_unit(dep_ref)
            if unit:
                if unit.course_id != course_id:
                    raise CrossCourseViolationError("KnowledgeUnit", dep_ref, course_id, unit.course_id)
            else:
                matching_in_course = [
                    u
                    for u in repo.list_units(course_id)
                    if u.title.strip().lower() == dep_ref.strip().lower() or u.id == dep_ref
                ]
                if len(matching_in_course) > 1:
                    matching_ids = [u.id for u in matching_in_course]
                    raise ValidationError(
                        f"Ambiguous dependency '{dep_ref}' matches multiple units in course '{course_id}': {matching_ids}"
                    )
                elif len(matching_in_course) == 1:
                    unit = matching_in_course[0]
                else:
                    all_matching = repo.find_units_by_title(dep_ref)
                    foreign = [u for u in all_matching if u.course_id != course_id]
                    if foreign:
                        raise CrossCourseViolationError(
                            "KnowledgeUnit", foreign[0].id, course_id, foreign[0].course_id
                        )
                    unresolved.append(dep_ref)
                    unit = None

            if unit:
                resolved[unit.id] = unit
                for child_dep in unit.dependencies:
                    if child_dep not in visited and child_dep not in to_visit:
                        to_visit.append(child_dep)
                    elif child_dep in visited:
                        cycle_detected = True

    result = ClosureResult(resolved)
    result.unresolved_dependencies = unresolved
    result.missing_roots = missing_roots
    result.cycle_detected = cycle_detected
    result.closure_complete = (len(unresolved) == 0 and len(missing_roots) == 0)
    return result
