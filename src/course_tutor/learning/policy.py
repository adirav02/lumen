import json
import sqlite3
from typing import Any, List, Optional, Set, Tuple

from ..models import (
    AttemptEvent,
    EvidenceRecord,
    EVALUATED_DEMONSTRATED_LEVELS,
    is_identity_resolved,
    validate_finite_number,
    validate_finite_metadata,
)


def is_evidence_completed_evaluation(evidence: Any) -> bool:
    """Return True if evidence represents a completed evaluation rather than an observation."""
    level = getattr(evidence, "demonstrated_level", None) or (evidence["demonstrated_level"] if isinstance(evidence, dict) or hasattr(evidence, "__getitem__") else None)
    return level in EVALUATED_DEMONSTRATED_LEVELS


def is_evidence_currently_applicable(
    evidence: Any,
    current_rev: int,
    current_hash: str,
) -> bool:
    """Return True if evidence is active and matches the exercise version's current educational identity."""
    status = getattr(evidence, "status", None) or (evidence["status"] if isinstance(evidence, dict) or hasattr(evidence, "__getitem__") else None)
    if status != "active":
        return False
    ev_rev = getattr(evidence, "exercise_revision", None) or (evidence["exercise_revision"] if isinstance(evidence, dict) or hasattr(evidence, "__getitem__") else None)
    ev_hash = getattr(evidence, "exercise_content_hash", None) or (evidence["exercise_content_hash"] if isinstance(evidence, dict) or hasattr(evidence, "__getitem__") else None)
    if not is_identity_resolved(ev_rev, ev_hash):
        return False
    return ev_rev == current_rev and ev_hash == current_hash


def check_evidence_eligibility_chain(
    con: sqlite3.Connection,
    evidence: Any,
    current_rev: int,
    current_hash: str,
    learner_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Validate evidence eligibility across the entire provenance chain.

    Requirements:
    - Evidence record is active and has resolved educational identity.
    - Evidence revision and hash match current exercise version.
    - Attempt exists, belongs to correct learner (if learner_id specified),
      has resolved educational identity matching current exercise version,
      and matches the evidence record.
    - Work submission event exists, belongs to attempt, is non-empty,
      and matches current exercise version if it carries educational identity metadata.
    """
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if hasattr(obj, key):
            val = getattr(obj, key)
            return val if val is not None else default
        if isinstance(obj, dict):
            return obj.get(key, default)
        try:
            return obj[key]
        except Exception:
            return default

    status = _get(evidence, "status")
    if status != "active":
        return False, f"Evidence status is '{status}', expected 'active'."

    version_id = _get(evidence, "exercise_version_id")
    columns = {r[1] for r in con.execute('PRAGMA table_info(question_occurrences)')}
    if 'visual_review_status' in columns:
        source_review = con.execute('SELECT review_status,visual_review_status FROM question_occurrences WHERE exercise_version_id=?', (version_id,)).fetchone()
        if source_review and (source_review['review_status'] != 'accepted' or source_review['visual_review_status'] not in ('verified','not_required')):
            return False, 'Source question extraction/visual verification is pending.'

    ev_rev = _get(evidence, "exercise_revision")
    ev_hash = _get(evidence, "exercise_content_hash")

    if not is_identity_resolved(ev_rev, ev_hash):
        return False, "Evidence has unresolved educational identity."

    if ev_rev != current_rev or ev_hash != current_hash:
        return False, f"Evidence identity (rev {ev_rev}) does not match current exercise version (rev {current_rev})."

    attempt_id = _get(evidence, "attempt_id")
    if not attempt_id:
        return False, "Evidence has no linked attempt."

    att = con.execute(
        "SELECT id, learner_id, exercise_revision, exercise_content_hash FROM attempts WHERE id = ?",
        (attempt_id,),
    ).fetchone()
    if not att:
        return False, f"Linked attempt '{attempt_id}' not found."

    if learner_id is not None and att["learner_id"] != learner_id:
        return False, f"Attempt learner '{att['learner_id']}' does not match expected learner '{learner_id}'."

    if not is_identity_resolved(att["exercise_revision"], att["exercise_content_hash"]):
        return False, f"Linked attempt '{attempt_id}' has unresolved educational identity."

    if att["exercise_revision"] != current_rev or att["exercise_content_hash"] != current_hash:
        return False, f"Linked attempt '{attempt_id}' identity (rev {att['exercise_revision']}) does not match current exercise version (rev {current_rev})."

    if ev_rev != att["exercise_revision"] or ev_hash != att["exercise_content_hash"]:
        return False, f"Evidence educational identity does not match linked attempt '{attempt_id}'."

    event_id = _get(evidence, "event_id")
    if not event_id:
        return False, "Evidence has no linked attempt event."

    ev_row = con.execute(
        "SELECT id, attempt_id, event_type, content, event_metadata_json FROM attempt_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if not ev_row:
        return False, f"Linked event '{event_id}' not found."

    if ev_row["attempt_id"] != attempt_id:
        return False, f"Linked event '{event_id}' does not belong to attempt '{attempt_id}'."

    if ev_row["event_type"] != "work_submission":
        return False, f"Linked event '{event_id}' has type '{ev_row['event_type']}', expected 'work_submission'."

    if not ev_row["content"] or not ev_row["content"].strip():
        return False, f"Linked work submission event '{event_id}' has empty content."

    try:
        meta = json.loads(ev_row["event_metadata_json"] or "{}")
    except Exception:
        meta = {}

    sub_rev = meta.get("exercise_revision")
    sub_hash = meta.get("exercise_content_hash")
    if sub_rev is not None and sub_rev != current_rev:
        return False, f"Submission event metadata revision {sub_rev} does not match current revision {current_rev}."
    if sub_hash is not None and sub_hash != current_hash:
        return False, "Submission event metadata hash does not match current exercise version hash."

    return True, ""


def is_evidence_eligible_for_performance(
    evidence: Any,
    current_rev: int,
    current_hash: str,
    con: Optional[sqlite3.Connection] = None,
    learner_id: Optional[str] = None,
) -> bool:
    """Return True if evidence is active, matches current exercise identity, and represents evaluated work."""
    if not is_evidence_completed_evaluation(evidence):
        return False
    if con is not None:
        ok, _ = check_evidence_eligibility_chain(con, evidence, current_rev, current_hash, learner_id=learner_id)
        return ok
    return is_evidence_currently_applicable(evidence, current_rev, current_hash)


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
    prior_assistance: bool = False,
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
        if has_solution or has_hint or prior_assistance:
            return "assisted_success"
        return "independent_mastery"

    if is_partial_progress:
        return "partial_progress"

    return "incorrect"


def count_family_exposure(events: List[AttemptEvent], exercise_family: str) -> int:
    """Count how many times an exercise family has been attempted."""
    return sum(1 for e in events if e.metadata.get("exercise_family") == exercise_family)

