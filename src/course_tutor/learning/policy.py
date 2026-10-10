"""Deterministic evaluation policy for learner evidence, assistance tracking, and topic state."""

from typing import Any, Dict, List, Optional

from ..models import AttemptEvent, EvidenceRecord


def determine_demonstrated_level(
    submitted_correct: bool,
    events_for_subpart: List[AttemptEvent],
    is_partial_progress: bool = False,
    has_arithmetic_error_only: bool = False,
) -> str:
    """Determine evidence level based on strictly observed assistance history.

    Rules (F07, F09):
    - If solution was revealed before/during submission: always 'assisted_success' or 'solution_exposed'.
    - If hint was given before/during submission: always 'assisted_success'.
    - If correct method with arithmetic mistake: 'partial_progress'.
    - If submitted without any assistance and correct: 'independent_mastery'.
    - If incorrect: 'incorrect'.
    """
    has_solution = any(e.event_type == "solution_revealed" for e in events_for_subpart)
    has_hint = any(e.event_type == "hint_given" for e in events_for_subpart)

    if has_arithmetic_error_only:
        return "partial_progress"

    if submitted_correct:
        if has_solution or has_hint:
            return "assisted_success"
        return "independent_mastery"

    if is_partial_progress:
        return "partial_progress"

    return "incorrect"


def count_family_exposure(events: List[AttemptEvent], exercise_family: str) -> int:
    """Count how many times an exercise family has been attempted."""
    return sum(1 for e in events if e.metadata.get("exercise_family") == exercise_family)
