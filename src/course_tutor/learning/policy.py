import math
from typing import Any, Dict, List, Optional, Set, Tuple

from ..errors import ValidationError
from ..models import (
    AttemptEvent,
    EvidenceRecord,
    EVALUATED_DEMONSTRATED_LEVELS,
    OBSERVATION_DEMONSTRATED_LEVELS,
    is_identity_resolved,
    validate_finite_number,
    validate_finite_metadata,
)


def is_evidence_completed_evaluation(evidence: EvidenceRecord) -> bool:
    """Return True if evidence represents a completed evaluation rather than an observation."""
    return evidence.demonstrated_level in EVALUATED_DEMONSTRATED_LEVELS


def is_evidence_currently_applicable(
    evidence: EvidenceRecord,
    current_rev: int,
    current_hash: str,
) -> bool:
    """Return True if evidence is active and matches the exercise version's current educational identity."""
    if evidence.status != "active":
        return False
    if not is_identity_resolved(evidence.exercise_revision, evidence.exercise_content_hash):
        return False
    return (
        evidence.exercise_revision == current_rev
        and evidence.exercise_content_hash == current_hash
    )


def is_evidence_eligible_for_performance(
    evidence: EvidenceRecord,
    current_rev: int,
    current_hash: str,
) -> bool:
    """Return True if evidence is active, matches current exercise identity, and represents evaluated work."""
    return is_evidence_currently_applicable(evidence, current_rev, current_hash) and is_evidence_completed_evaluation(evidence)


def get_required_subparts(subparts: Any) -> Set[str]:
    """Extract required subpart keys according to an explicit schema.
    
    If subparts is a list:
      - dict element: key from 'subpart_key', 'key', or 'id', excluded if element.get('required') is False.
      - string element: non-empty string.
    If subparts is a dict: all keys are required unless explicitly annotated with {"required": false}.
    """
    if isinstance(subparts, list):
        required = set()
        for s in subparts:
            if isinstance(s, dict):
                if s.get("required") is False:
                    continue
                k = s.get("subpart_key") or s.get("key") or s.get("id")
                if k is not None and str(k).strip():
                    required.add(str(k).strip())
            elif s is not None and str(s).strip():
                required.add(str(s).strip())
        return required
    if isinstance(subparts, dict):
        required = set()
        for k, v in subparts.items():
            k_str = str(k).strip()
            if not k_str:
                continue
            if isinstance(v, dict) and v.get("required") is False:
                continue
            required.add(k_str)
        return required
    return set()


def are_all_required_subparts_evaluated(
    required_subparts: Set[str],
    evaluated_evidence: List[EvidenceRecord],
) -> Tuple[bool, Set[str]]:
    """Verify whether all required subparts have received active evaluated evidence."""
    if not required_subparts:
        return True, set()
    evaluated_subparts = {
        e.subpart_key
        for e in evaluated_evidence
        if e.subpart_key and e.demonstrated_level in EVALUATED_DEMONSTRATED_LEVELS
    }
    missing = required_subparts - evaluated_subparts
    return len(missing) == 0, missing


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

