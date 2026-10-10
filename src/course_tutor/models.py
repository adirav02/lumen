"""Data models and serialization structures for Lumen."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    """Return current ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def compute_canonical_hash(payload: Dict[str, Any], exclude_keys: Optional[List[str]] = None) -> str:
    """Compute deterministic SHA-256 hash for a dictionary, ignoring specified keys."""
    exclude = set(exclude_keys or ["request_id", "timestamp"])
    clean_dict = {k: v for k, v in payload.items() if k not in exclude}
    serialized = json.dumps(clean_dict, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass
class OperationReceipt:
    request_id: str
    course_id: Optional[str]
    canonical_request_hash: str
    operation_name: str
    affected_ids: List[str] = field(default_factory=list)
    response_data: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Course:
    id: str
    name: str
    scope: str = ""
    default_language: str = "en"
    notation_settings: Dict[str, Any] = field(default_factory=dict)
    revision: int = 1
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Source:
    id: str
    course_id: str
    logical_name: str
    role: str = "reference"  # 'syllabus', 'lecture', 'slides', 'exercise', 'reference', 'exam'
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SourceVersion:
    id: str
    source_id: str
    course_id: str
    version_num: int
    file_hash: str
    original_filename: str
    mime_type: str
    byte_size: int
    storage_relpath: str
    extraction_status: str = "pending"  # 'pending', 'extracted', 'uncertain', 'failed'
    extraction_notes: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Topic:
    id: str
    course_id: str
    name: str
    slug: str
    parent_topic_id: Optional[str] = None
    description: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TopicLink:
    id: str
    course_id: str
    from_topic_id: str
    to_topic_id: str
    relationship_type: str = "prerequisite"  # 'prerequisite', 'related', 'subtopic'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TopicAlias:
    id: str
    course_id: str
    topic_id: str
    alias: str
    language: str = "en"  # 'en', 'he', 'notation'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_bool(val: Any) -> bool:
    """Strictly parse boolean values, rejecting ambiguous or misleading representations."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "1", "yes", "t"):
            return True
        if s in ("false", "0", "no", "f", ""):
            return False
    raise ValueError(f"Cannot parse boolean from {val!r}")


@dataclass
class SourceSection:
    id: str
    source_version_id: str
    course_id: str
    section_index: int
    label: str
    text: str
    quality_flag: str = "clean"
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeUnit:
    id: str
    course_id: str
    kind: str  # 'definition', 'theorem', 'formula', 'method', 'example', 'table', 'figure'
    title: str
    content: str
    summary: str = ""
    assumptions: List[str] = field(default_factory=list)
    symbol_definitions: Dict[str, str] = field(default_factory=dict)
    exceptions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # unit IDs or topic IDs
    status: str = "pending_review"  # 'published', 'pending_review'
    revision: int = 1
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UnitProvenance:
    id: str
    unit_id: str
    source_version_id: str
    page_index: Optional[int] = None
    page_label: Optional[str] = None
    slide_index: Optional[int] = None
    region_box: Optional[Dict[str, Any]] = None
    origin_type: str = "extracted"  # 'extracted', 'generated', 'instructor_correction', 'synthesis'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Exercise:
    id: str
    course_id: str
    exercise_family: str
    external_ref: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExerciseVersion:
    id: str
    exercise_id: str
    course_id: str
    version_num: int
    question_text: str
    subparts: List[Dict[str, Any]] = field(default_factory=list)
    topic_mappings: List[str] = field(default_factory=list)
    skill_mappings: List[str] = field(default_factory=list)
    reference_solution: str = ""
    rubric: Dict[str, Any] = field(default_factory=dict)
    validation_state: str = "pending_review"  # 'validated', 'pending_review', 'contradictory'
    validation_notes: str = ""
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Attempt:
    id: str
    course_id: str
    exercise_version_id: str
    learner_id: str
    mode: str = "practice"  # 'practice', 'diagnostic'
    status: str = "open"  # 'open', 'paused', 'completed'
    current_revision: int = 1
    started_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AttemptEvent:
    id: str
    attempt_id: str
    course_id: str
    event_index: int
    event_type: str  # 'work_submission', 'hint_request', 'hint_given', 'solution_request', 'solution_revealed', 'pause', 'resume'
    subpart_key: Optional[str] = None
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceRecord:
    id: str
    course_id: str
    attempt_id: str
    event_id: str
    exercise_version_id: str
    topic_id: str
    skill_id: str
    subpart_key: str
    demonstrated_level: str  # 'independent_mastery', 'assisted_success', 'partial_progress', 'incorrect', 'unassessed'
    error_category: Optional[str] = None  # 'conceptual', 'method_selection', 'counting', 'algebra', 'arithmetic', None
    rationale: str = ""
    status: str = "active"  # 'active', 'retracted', 'superseded'
    parent_evidence_id: Optional[str] = None
    correction_reason: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Assessment:
    id: str
    course_id: str
    title: str
    blueprint: Dict[str, Any] = field(default_factory=dict)
    learner_id: Optional[str] = None
    status: str = "open"  # 'open', 'paused', 'completed'
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AssessmentItem:
    id: str
    assessment_id: str
    exercise_version_id: str
    item_order: int
    attempt_id: Optional[str] = None
    learner_id: Optional[str] = None
    weight: float = 1.0
    max_points: float = 10.0
    points_awarded: Optional[float] = None
    exposure_count: int = 0
    score_status: str = "unassessed"  # 'unassessed', 'scored', 'pending_review'
    score_history: List[Dict[str, Any]] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TopicState:
    id: str
    course_id: str
    topic_id: str
    policy_version: int = 1
    independent_success_count: int = 0
    assisted_success_count: int = 0
    partial_progress_count: int = 0
    error_count: int = 0
    unassessed_flag: bool = True
    last_evidence_event_id: Optional[str] = None
    summary_data: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearnerSettings:
    id: str
    course_id: str
    learner_id: str
    teaching_preference: str = "gradual_hints"  # 'gradual_hints', 'direct_explanations', 'challenge_first'
    chosen_language: str = "en"
    explicit_goals: str = ""
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
