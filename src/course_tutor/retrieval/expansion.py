"""Dependency expansion ensuring all prerequisite definitions and mathematical assumptions are included."""

import sqlite3
from typing import Dict, List, Set

from ..models import KnowledgeUnit
from ..storage.repositories import KnowledgeRepository


def expand_unit_dependencies(
    con: sqlite3.Connection,
    course_id: str,
    unit_ids: List[str],
    max_depth: int = 3,
) -> Dict[str, KnowledgeUnit]:
    """Given a list of unit IDs, transitively resolve all dependencies (prerequisite units).

    Ensures mathematical definitions and conditions required to apply theorems or formulas
    are never missing from the retrieved context (F02, F26).
    """
    repo = KnowledgeRepository(con)
    resolved: Dict[str, KnowledgeUnit] = {}
    to_visit: Set[str] = set(unit_ids)
    visited: Set[str] = set()

    depth = 0
    while to_visit and depth < max_depth:
        depth += 1
        current_batch = list(to_visit)
        to_visit = set()

        for uid in current_batch:
            if uid in visited:
                continue
            visited.add(uid)

            unit = repo.get_unit(uid)
            if not unit or unit.course_id != course_id:
                # Could be a topic slug or title referenced as a dependency
                # Try finding by title or slug
                matched = [u for u in repo.list_units(course_id) if u.title.lower() == uid.lower() or u.id == uid]
                if matched:
                    unit = matched[0]

            if unit:
                resolved[unit.id] = unit
                for dep in unit.dependencies:
                    if dep not in visited:
                        to_visit.add(dep)

    return resolved
