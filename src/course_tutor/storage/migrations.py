"""Database migrations runner and schema definition."""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from ..errors import ConflictError, LegacyDuplicateAttemptLinkError, ValidationError
from ..models import (
    EVALUATED_DEMONSTRATED_LEVELS,
    compute_exercise_version_hash,
    is_identity_resolved,
)
from ..learning.policy import (
    check_evidence_eligibility_chain,
    get_required_subparts,
)
from .db import atomic_transaction
from ..questions.schema import SCHEMA_SQL as MIGRATION_V9_SQL
from ..questions.review import MIGRATION_V10_SQL

MIGRATION_V1_SQL = """
-- Migration 001: Initial Schema for Lumen Core

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    default_language TEXT NOT NULL DEFAULT 'en',
    notation_settings TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    logical_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'reference',
    created_at TEXT NOT NULL,
    UNIQUE(course_id, logical_name)
);

CREATE TABLE IF NOT EXISTS source_versions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL,
    file_hash TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    storage_relpath TEXT NOT NULL,
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    extraction_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(source_id, version_num)
);

CREATE INDEX IF NOT EXISTS idx_source_versions_hash ON source_versions(file_hash);

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    parent_topic_id TEXT REFERENCES topics(id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(course_id, slug)
);

CREATE TABLE IF NOT EXISTS topic_links (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    from_topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    to_topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL DEFAULT 'prerequisite',
    UNIQUE(course_id, from_topic_id, to_topic_id, relationship_type)
);

CREATE TABLE IF NOT EXISTS topic_aliases (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    UNIQUE(course_id, topic_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_topic_aliases_alias ON topic_aliases(course_id, alias);

CREATE TABLE IF NOT EXISTS knowledge_units (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    assumptions TEXT NOT NULL DEFAULT '[]',
    symbol_definitions TEXT NOT NULL DEFAULT '{}',
    exceptions TEXT NOT NULL DEFAULT '[]',
    dependencies TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'published',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_units_course ON knowledge_units(course_id, kind);

CREATE TABLE IF NOT EXISTS unit_provenance (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
    source_version_id TEXT NOT NULL REFERENCES source_versions(id) ON DELETE CASCADE,
    page_index INTEGER,
    page_label TEXT,
    slide_index INTEGER,
    region_box TEXT,
    origin_type TEXT NOT NULL DEFAULT 'extracted'
);

CREATE TABLE IF NOT EXISTS unit_topics (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    UNIQUE(unit_id, topic_id)
);

CREATE TABLE IF NOT EXISTS exercises (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    exercise_family TEXT NOT NULL,
    external_ref TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exercise_versions (
    id TEXT PRIMARY KEY,
    exercise_id TEXT NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    subparts_json TEXT NOT NULL DEFAULT '[]',
    topic_mappings_json TEXT NOT NULL DEFAULT '[]',
    skill_mappings_json TEXT NOT NULL DEFAULT '[]',
    reference_solution TEXT NOT NULL DEFAULT '',
    rubric_json TEXT NOT NULL DEFAULT '{}',
    validation_state TEXT NOT NULL DEFAULT 'validated',
    validation_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(exercise_id, version_num)
);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    exercise_version_id TEXT NOT NULL REFERENCES exercise_versions(id) ON DELETE RESTRICT,
    learner_id TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'practice',
    status TEXT NOT NULL DEFAULT 'open',
    current_revision INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_course_status ON attempts(course_id, status);

CREATE TABLE IF NOT EXISTS attempt_events (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    event_index INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    subpart_key TEXT,
    content TEXT NOT NULL DEFAULT '',
    event_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(attempt_id, event_index)
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    event_id TEXT REFERENCES attempt_events(id) ON DELETE SET NULL,
    exercise_version_id TEXT NOT NULL REFERENCES exercise_versions(id) ON DELETE RESTRICT,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE RESTRICT,
    skill_id TEXT NOT NULL,
    subpart_key TEXT NOT NULL,
    demonstrated_level TEXT NOT NULL,
    error_category TEXT,
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    parent_evidence_id TEXT REFERENCES evidence(id) ON DELETE SET NULL,
    correction_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_course_topic ON evidence(course_id, topic_id, status);

CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    blueprint_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessment_items (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    exercise_version_id TEXT NOT NULL REFERENCES exercise_versions(id) ON DELETE RESTRICT,
    item_order INTEGER NOT NULL,
    attempt_id TEXT REFERENCES attempts(id) ON DELETE SET NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    max_points REAL NOT NULL DEFAULT 10.0,
    points_awarded REAL,
    exposure_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(assessment_id, item_order)
);

CREATE TABLE IF NOT EXISTS topic_state (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    policy_version INTEGER NOT NULL DEFAULT 1,
    independent_success_count INTEGER NOT NULL DEFAULT 0,
    assisted_success_count INTEGER NOT NULL DEFAULT 0,
    partial_progress_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    unassessed_flag INTEGER NOT NULL DEFAULT 1,
    last_evidence_event_id TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    UNIQUE(course_id, topic_id)
);

CREATE TABLE IF NOT EXISTS learner_settings (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    learner_id TEXT NOT NULL,
    teaching_preference TEXT NOT NULL DEFAULT 'gradual_hints',
    chosen_language TEXT NOT NULL DEFAULT 'en',
    explicit_goals TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(course_id, learner_id)
);

CREATE TABLE IF NOT EXISTS operation_receipts (
    request_id TEXT PRIMARY KEY,
    course_id TEXT,
    canonical_request_hash TEXT NOT NULL,
    operation_name TEXT NOT NULL,
    affected_ids_json TEXT NOT NULL DEFAULT '[]',
    response_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- Full-Text Search 5 virtual table for units
CREATE VIRTUAL TABLE IF NOT EXISTS fts_units USING fts5(
    unit_id UNINDEXED,
    course_id UNINDEXED,
    title,
    content,
    summary,
    assumptions,
    symbols,
    tokenize = 'unicode61'
);
"""
MIGRATION_V2_SQL = """
-- Migration 002: Persist complete extracted sections and source locators

CREATE TABLE IF NOT EXISTS source_sections (
    id TEXT PRIMARY KEY,
    source_version_id TEXT NOT NULL REFERENCES source_versions(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    section_index INTEGER NOT NULL,
    label TEXT NOT NULL,
    text TEXT NOT NULL,
    quality_flag TEXT NOT NULL DEFAULT 'clean',
    notes TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(source_version_id, section_index)
);

CREATE INDEX IF NOT EXISTS idx_source_sections_ver ON source_sections(source_version_id, section_index);
"""

MIGRATION_V3_SQL = """
ALTER TABLE assessment_items ADD COLUMN score_status TEXT NOT NULL DEFAULT 'unassessed';
ALTER TABLE assessment_items ADD COLUMN score_history_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE assessment_items ADD COLUMN evidence_ids_json TEXT NOT NULL DEFAULT '[]';
"""

MIGRATION_V4_SQL = """
ALTER TABLE assessments ADD COLUMN learner_id TEXT;
ALTER TABLE assessment_items ADD COLUMN learner_id TEXT;
ALTER TABLE exercise_versions ADD COLUMN revision_history_json TEXT NOT NULL DEFAULT '[]';
"""

MIGRATION_V5_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_items_unique_attempt ON assessment_items(attempt_id) WHERE attempt_id IS NOT NULL;
"""

MIGRATION_V6_SQL = """
ALTER TABLE attempts ADD COLUMN exercise_revision INTEGER;
ALTER TABLE attempts ADD COLUMN exercise_content_hash TEXT;
ALTER TABLE evidence ADD COLUMN exercise_revision INTEGER;
ALTER TABLE evidence ADD COLUMN exercise_content_hash TEXT;
"""

MIGRATION_V7_SQL = """
CREATE TABLE IF NOT EXISTS backup_v6_assessment_items AS SELECT * FROM assessment_items WHERE 1=0;
CREATE TABLE IF NOT EXISTS backup_v6_attempts AS SELECT * FROM attempts WHERE 1=0;
CREATE TABLE IF NOT EXISTS backup_v6_evidence AS SELECT * FROM evidence WHERE 1=0;
"""

MIGRATION_V8_SQL = """
CREATE TABLE IF NOT EXISTS backup_v7_assessment_items AS SELECT * FROM assessment_items WHERE 1=0;
CREATE TABLE IF NOT EXISTS backup_v7_assessments AS SELECT * FROM assessments WHERE 1=0;
CREATE TABLE IF NOT EXISTS backup_v7_evidence AS SELECT * FROM evidence WHERE 1=0;
CREATE TABLE IF NOT EXISTS backup_v7_topic_state AS SELECT * FROM topic_state WHERE 1=0;
CREATE TABLE IF NOT EXISTS backup_v7_attempt_events AS SELECT * FROM attempt_events WHERE 1=0;
"""

MIGRATION_V11_SQL = """
CREATE TABLE assembly_jobs (
    request_id TEXT PRIMARY KEY,
    input_hash TEXT NOT NULL,
    assessment_id TEXT NOT NULL UNIQUE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    learner_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','published','failed')),
    owner_token TEXT NOT NULL,
    staging_path TEXT NOT NULL,
    final_path TEXT NOT NULL,
    generation_json TEXT NOT NULL,
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_assembly_jobs_scope ON assembly_jobs(course_id,learner_id,state);
CREATE TABLE assembly_item_snapshots (
    request_id TEXT NOT NULL REFERENCES assembly_jobs(request_id) ON DELETE RESTRICT,
    item_id TEXT NOT NULL UNIQUE,
    exercise_version_id TEXT NOT NULL REFERENCES exercise_versions(id) ON DELETE RESTRICT,
    item_order INTEGER NOT NULL CHECK(item_order > 0),
    slot_id TEXT NOT NULL,
    max_points REAL NOT NULL CHECK(max_points > 0 AND max_points < 1e308),
    exercise_revision INTEGER NOT NULL CHECK(exercise_revision > 0),
    exercise_content_hash TEXT NOT NULL CHECK(length(exercise_content_hash) > 0),
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY(request_id,item_order),
    UNIQUE(request_id,exercise_version_id)
);
CREATE INDEX idx_assembly_snapshots_version ON assembly_item_snapshots(exercise_version_id);
"""

MIGRATION_V12_SQL = """
CREATE TABLE reservation_releases (
    assessment_id TEXT PRIMARY KEY CHECK(length(trim(assessment_id)) > 0),
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    learner_id TEXT,
    released_at TEXT NOT NULL CHECK(length(trim(released_at)) > 0),
    reason TEXT NOT NULL CHECK(reason IN ('released','cancelled','expired'))
);
CREATE INDEX idx_reservation_releases_scope ON reservation_releases(course_id,learner_id);
"""

MIGRATION_V13_SQL = """
CREATE TABLE source_processing (
    source_version_id TEXT PRIMARY KEY REFERENCES source_versions(id) ON DELETE RESTRICT,
    processing_fingerprint TEXT NOT NULL CHECK(length(processing_fingerprint) = 64),
    descriptor_json TEXT NOT NULL,
    reuse_eligible INTEGER NOT NULL CHECK(reuse_eligible IN (0, 1))
);
CREATE INDEX idx_source_processing_fingerprint ON source_processing(processing_fingerprint, reuse_eligible);
CREATE INDEX idx_source_versions_processing_scope ON source_versions(source_id, course_id, file_hash);
"""

MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "Initial schema for Lumen core with FTS5", MIGRATION_V1_SQL),
    (2, "Persist complete extracted sections and source locators", MIGRATION_V2_SQL),
    (3, "Track assessment item score status, audit history, and supporting evidence", MIGRATION_V3_SQL),
    (4, "Track learner ownership on assessments and revision history on exercise versions", MIGRATION_V4_SQL),
    (5, "Enforce unique non-null attempt-to-item link in assessment_items", MIGRATION_V5_SQL),
    (6, "Educational content identity tracking on attempts and evidence", MIGRATION_V6_SQL),
    (7, "Resolve authoritative educational identity and quarantine invalid historical links/scores", MIGRATION_V7_SQL),
    (8, "Repair historical scores, quarantine incompatible evidence, and rebuild projections", MIGRATION_V8_SQL),
    (9, "Source-bound exam questions, duplicate candidates, and append-only practice grades", MIGRATION_V9_SQL),
    (10, "Separate visual reviews, source metadata, solution links and identical-exam aliases", MIGRATION_V10_SQL),
    (11, "Immutable exam assembly snapshots and publication jobs", MIGRATION_V11_SQL),
    (12, "Terminal reservation release ledger", MIGRATION_V12_SQL),
    (13, "Completed source processing identity", MIGRATION_V13_SQL),
]



def _execute_sql_script(con: sqlite3.Connection, sql: str) -> None:
    """Execute semicolon-separated DDL statements within the active transaction."""
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    for stmt in statements:
        con.execute(stmt)


def detect_legacy_duplicate_attempt_links(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Detect whether assessment_items contains duplicate non-null attempt links."""
    table_exists = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='assessment_items'"
    ).fetchone()
    if not table_exists:
        return []

    rows = con.execute(
        """
        SELECT attempt_id, COUNT(*) as cnt
        FROM assessment_items
        WHERE attempt_id IS NOT NULL
        GROUP BY attempt_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    duplicates = []
    for r in rows:
        att_id = r[0]
        cnt = r[1]
        items = con.execute(
            """
            SELECT id, assessment_id, item_order, exercise_version_id, learner_id,
                   points_awarded, score_status, score_history_json, evidence_ids_json
            FROM assessment_items
            WHERE attempt_id = ?
            ORDER BY item_order ASC
            """,
            (att_id,),
        ).fetchall()
        duplicates.append({
            "attempt_id": att_id,
            "count": cnt,
            "items": [dict(it) for it in items],
        })
    return duplicates


def quarantine_legacy_duplicate_attempt_links(con: sqlite3.Connection) -> Dict[str, Any]:
    """Quarantine duplicate legacy attempt links before Migration 005.

    Preserves conflicting historical relationships in legacy_duplicate_attempt_links,
    backs up assessment_items, quaranatines active links to pending_review, and reopens assessments.
    """
    duplicates = detect_legacy_duplicate_attempt_links(con)
    if not duplicates:
        return {"quarantined_count": 0, "quarantined_attempts": [], "quarantined_items": []}

    # 1. Back up before material repair
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_v4_assessment_items AS
        SELECT * FROM assessment_items;
        """
    )

    # 2. Audit table for legacy duplicate attempt links
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_duplicate_attempt_links (
            id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL,
            assessment_item_id TEXT NOT NULL,
            assessment_id TEXT NOT NULL,
            item_order INTEGER NOT NULL,
            exercise_version_id TEXT NOT NULL,
            learner_id TEXT,
            points_awarded REAL,
            score_status TEXT,
            evidence_ids_json TEXT NOT NULL DEFAULT '[]',
            score_history_json TEXT NOT NULL DEFAULT '[]',
            quarantined_at TEXT NOT NULL,
            resolution_status TEXT NOT NULL DEFAULT 'quarantined',
            resolution_notes TEXT NOT NULL DEFAULT ''
        );
        """
    )

    quarantined_attempts = []
    quarantined_items = []
    now = datetime.now(timezone.utc).isoformat()

    for dup in duplicates:
        att_id = dup["attempt_id"]
        quarantined_attempts.append(att_id)
        for item in dup["items"]:
            item_id = item["id"]
            quarantined_items.append(item_id)

            # Insert into audit table
            con.execute(
                """
                INSERT OR REPLACE INTO legacy_duplicate_attempt_links (
                    id, attempt_id, assessment_item_id, assessment_id, item_order,
                    exercise_version_id, learner_id, points_awarded, score_status,
                    evidence_ids_json, score_history_json, quarantined_at,
                    resolution_status, resolution_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'quarantined', ?)
                """,
                (
                    f"{att_id}_{item_id}",
                    att_id,
                    item_id,
                    item["assessment_id"],
                    item["item_order"],
                    item["exercise_version_id"],
                    item.get("learner_id"),
                    item.get("points_awarded"),
                    item.get("score_status"),
                    item.get("evidence_ids_json") or "[]",
                    item.get("score_history_json") or "[]",
                    now,
                    f"Quarantined due to duplicate legacy attempt link with attempt {att_id}",
                ),
            )

            # Prepare updated score history
            try:
                hist = json.loads(item.get("score_history_json") or "[]")
            except Exception:
                hist = []
            hist.append({
                "action": "quarantined_legacy_duplicate_attempt_link",
                "quarantined_attempt_id": att_id,
                "previous_points": item.get("points_awarded"),
                "previous_score_status": item.get("score_status"),
                "reason": "Legacy schema-v4 duplicate attempt link quarantined during migration to enforce attempt exclusivity. Preserved in legacy_duplicate_attempt_links table.",
                "recorded_at": now,
            })

            # Update assessment_items: clear attempt_id, reset to pending_review
            con.execute(
                """
                UPDATE assessment_items SET
                    attempt_id = NULL,
                    points_awarded = NULL,
                    score_status = 'pending_review',
                    evidence_ids_json = '[]',
                    score_history_json = ?
                WHERE id = ?
                """,
                (json.dumps(hist), item_id),
            )

            # Reopen the assessment
            con.execute(
                "UPDATE assessments SET status = 'open' WHERE id = ?",
                (item["assessment_id"],),
            )

    return {
        "quarantined_count": len(quarantined_items),
        "quarantined_attempts": quarantined_attempts,
        "quarantined_items": quarantined_items,
    }


def repair_legacy_duplicate_links(
    con: sqlite3.Connection,
    resolved_assignments: Optional[Dict[str, str]] = None,
    expected_link_states: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    """Actionable repair path for quarantined legacy duplicate attempt links.

    Validates course, exercise version, mode, learner ownership, and attempt exclusivity.
    Reaffirming an unchanged link is an idempotent no-op preserving points, evidence, history, and completion.
    A genuinely changed link invalidates prior scores, updates history, and reopens the assessment.
    Stale legacy repairs (already resolved or conflicting with current link state) are rejected with ConflictError.
    """
    with atomic_transaction(con):
        table_exists = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_duplicate_attempt_links'"
        ).fetchone()
        if not table_exists:
            return {"resolved": [], "unresolved": []}

        resolved_list = []
        if resolved_assignments:
            now = datetime.now(timezone.utc).isoformat()
            for att_id, item_id in resolved_assignments.items():
                record = con.execute(
                    "SELECT * FROM legacy_duplicate_attempt_links WHERE attempt_id = ? AND assessment_item_id = ?",
                    (att_id, item_id),
                ).fetchone()
                if not record:
                    raise ValidationError(
                        f"Attempt '{att_id}' and item '{item_id}' not found in quarantined legacy duplicate links."
                    )

                it = con.execute("SELECT * FROM assessment_items WHERE id = ?", (item_id,)).fetchone()
                if not it:
                    raise ValidationError(f"Assessment item '{item_id}' not found.")

                att = con.execute("SELECT * FROM attempts WHERE id = ?", (att_id,)).fetchone()
                if not att:
                    raise ValidationError(f"Attempt '{att_id}' not found.")

                ass = con.execute("SELECT * FROM assessments WHERE id = ?", (it["assessment_id"],)).fetchone()
                if not ass:
                    raise ValidationError(f"Assessment '{it['assessment_id']}' not found.")

                if att["course_id"] != ass["course_id"]:
                    raise ValidationError(
                        f"Attempt '{att_id}' course '{att['course_id']}' does not match assessment course '{ass['course_id']}'."
                    )
                if att["exercise_version_id"] != it["exercise_version_id"]:
                    raise ValidationError(
                        f"Attempt '{att_id}' exercise version '{att['exercise_version_id']}' does not match assessment item '{it['exercise_version_id']}'."
                    )
                if att["mode"] != "diagnostic":
                    raise ValidationError(
                        f"Attempt '{att_id}' has mode '{att['mode']}', expected 'diagnostic'."
                    )
                if ass["learner_id"] and ass["learner_id"] != att["learner_id"]:
                    raise ValidationError(
                        f"Learner mismatch: assessment '{ass['learner_id']}' vs attempt '{att['learner_id']}'."
                    )
                if it["learner_id"] and it["learner_id"] != att["learner_id"]:
                    raise ValidationError(
                        f"Learner mismatch: item '{it['learner_id']}' vs attempt '{att['learner_id']}'."
                    )

                other = con.execute(
                    "SELECT id FROM assessment_items WHERE attempt_id = ? AND id != ?",
                    (att_id, item_id),
                ).fetchone()
                if other:
                    raise ValidationError(
                        f"Attempt '{att_id}' is already linked to another assessment item ({other['id']})."
                    )

                # Defect 7 / Defect C: Reaffirming an unchanged link is an idempotent no-op!
                # Preserves scores, evidence, history, ownership, and completion.
                if it["attempt_id"] == att_id:
                    resolved_list.append({"attempt_id": att_id, "assessment_item_id": item_id, "reaffirmed": True})
                    continue

                # Defect 5: Stale legacy repair checks
                # If this quarantined link was already resolved in the past, historical record does not authorize future relink!
                if record["resolution_status"] == "resolved":
                    raise ConflictError(
                        f"Stale legacy repair: quarantined link for attempt '{att_id}' and item '{item_id}' was already resolved. "
                        f"Item is currently linked to attempt '{it['attempt_id']}'."
                    )

                if expected_link_states is not None:
                    exp_att = expected_link_states.get(item_id)
                    if exp_att != it["attempt_id"]:
                        raise ConflictError(
                            f"Stale link expectation for item '{item_id}': expected current attempt '{exp_att}', found '{it['attempt_id']}'."
                        )
                else:
                    # If expected_link_states not specified, cannot overwrite an active scored item
                    if it["attempt_id"] is not None and it["points_awarded"] is not None:
                        raise ConflictError(
                            f"Cannot overwrite active scored attempt '{it['attempt_id']}' on item '{item_id}' via legacy repair "
                            "without explicit expected_link_states."
                        )


                # Read item score history
                try:
                    hist = json.loads(it["score_history_json"] or "[]")
                except Exception:
                    hist = []

                if it["points_awarded"] is not None:
                    hist.append({
                        "action": "relinked_to_pending_review",
                        "previous_points": it["points_awarded"],
                        "points_awarded": None,
                        "attempt_id": att_id,
                        "previous_attempt_id": it["attempt_id"],
                        "reason": f"Item relinked via legacy repair from {it['attempt_id']} to {att_id}",
                        "recorded_at": now,
                    })
                    con.execute(
                        """
                        UPDATE assessment_items SET
                            attempt_id = ?,
                            learner_id = ?,
                            points_awarded = NULL,
                            score_status = 'pending_review',
                            evidence_ids_json = '[]',
                            score_history_json = ?
                        WHERE id = ?
                        """,
                        (att_id, att["learner_id"], json.dumps(hist), item_id),
                    )
                    con.execute(
                        "UPDATE assessments SET status = 'open' WHERE id = ?",
                        (it["assessment_id"],),
                    )
                else:
                    hist.append({
                        "action": "resolved_legacy_duplicate_link",
                        "attempt_id": att_id,
                        "reason": f"Explicit legacy duplicate link resolution assigning attempt to item {item_id}",
                        "recorded_at": now,
                    })
                    con.execute(
                        """
                        UPDATE assessment_items SET
                            attempt_id = ?,
                            learner_id = ?,
                            score_history_json = ?
                        WHERE id = ?
                        """,
                        (att_id, att["learner_id"], json.dumps(hist), item_id),
                    )

                con.execute(
                    """
                    UPDATE legacy_duplicate_attempt_links SET
                        resolution_status = 'resolved',
                        resolution_notes = ?
                    WHERE attempt_id = ? AND assessment_item_id = ?
                    """,
                    (f"Assigned to assessment item {item_id}", att_id, item_id),
                )
                con.execute(
                    """
                    UPDATE legacy_duplicate_attempt_links SET
                        resolution_status = 'quarantined_unlinked',
                        resolution_notes = ?
                    WHERE attempt_id = ? AND assessment_item_id != ?
                    """,
                    (f"Unlinked because attempt was assigned to {item_id}", att_id, item_id),
                )
                resolved_list.append({"attempt_id": att_id, "assessment_item_id": item_id, "reaffirmed": False})

        remaining = con.execute(
            "SELECT attempt_id, assessment_item_id FROM legacy_duplicate_attempt_links WHERE resolution_status = 'quarantined'"
        ).fetchall()

        return {
            "resolved": resolved_list,
            "unresolved": [dict(r) for r in remaining],
        }


def resolve_and_quarantine_legacy_identities(con: sqlite3.Connection) -> Dict[str, Any]:
    """Inspect and resolve legacy educational identities, quarantining invalid scored items.

    1. Backs up assessment_items, attempts, and evidence prior to material changes.
    2. Authoritatively resolves attempts and evidence when the exercise version was never modified (revision 1).
    3. Leaves ambiguous attempts on modified exercises as NULL (unresolved).
    4. Quarantines legacy scored assessment items whose attempts or evidence are unresolved or outdated.
    """
    now = datetime.now(timezone.utc).isoformat()
    # Back up tables
    con.execute("CREATE TABLE IF NOT EXISTS backup_v6_assessment_items AS SELECT * FROM assessment_items WHERE 1=0;")
    cnt = con.execute("SELECT COUNT(*) FROM backup_v6_assessment_items").fetchone()[0]
    if cnt == 0:
        con.execute("INSERT INTO backup_v6_assessment_items SELECT * FROM assessment_items;")

    con.execute("CREATE TABLE IF NOT EXISTS backup_v6_attempts AS SELECT * FROM attempts WHERE 1=0;")
    cnt_att = con.execute("SELECT COUNT(*) FROM backup_v6_attempts").fetchone()[0]
    if cnt_att == 0:
        con.execute("INSERT INTO backup_v6_attempts SELECT * FROM attempts;")

    con.execute("CREATE TABLE IF NOT EXISTS backup_v6_evidence AS SELECT * FROM evidence WHERE 1=0;")
    cnt_ev = con.execute("SELECT COUNT(*) FROM backup_v6_evidence").fetchone()[0]
    if cnt_ev == 0:
        con.execute("INSERT INTO backup_v6_evidence SELECT * FROM evidence;")

    # Check and update legacy_duplicate_attempt_links table columns if it exists
    tbl_chk = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_duplicate_attempt_links'"
    ).fetchone()
    if tbl_chk:
        cols = [r["name"] for r in con.execute("PRAGMA table_info(legacy_duplicate_attempt_links)").fetchall()]
        if "resolution_status" not in cols:
            con.execute("ALTER TABLE legacy_duplicate_attempt_links ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'quarantined';")
        if "resolution_notes" not in cols:
            con.execute("ALTER TABLE legacy_duplicate_attempt_links ADD COLUMN resolution_notes TEXT NOT NULL DEFAULT '';")

    resolved_attempts_count = 0
    # Inspect attempts
    att_rows = con.execute(
        "SELECT id, exercise_version_id, exercise_revision, exercise_content_hash FROM attempts WHERE exercise_revision IS NULL OR exercise_content_hash IS NULL"
    ).fetchall()
    for att in att_rows:
        ex_row = con.execute("SELECT * FROM exercise_versions WHERE id = ?", (att["exercise_version_id"],)).fetchone()
        if not ex_row:
            continue
        rev_hist_raw = ex_row["revision_history_json"] if "revision_history_json" in ex_row.keys() else "[]"
        try:
            rev_hist = json.loads(rev_hist_raw or "[]")
        except Exception:
            rev_hist = []

        if len(rev_hist) == 0:
            # Exercise version was NEVER modified since creation. Authoritative identity is revision 1.
            try:
                subparts = json.loads(ex_row["subparts_json"] or "[]")
            except Exception:
                subparts = []
            try:
                rubric = json.loads(ex_row["rubric_json"] or "{}")
            except Exception:
                rubric = {}
            c_hash = compute_exercise_version_hash(
                ex_row["question_text"],
                ex_row["reference_solution"],
                rubric,
                subparts,
            )
            con.execute(
                "UPDATE attempts SET exercise_revision = 1, exercise_content_hash = ? WHERE id = ?",
                (c_hash, att["id"]),
            )
            resolved_attempts_count += 1
            # Update attempt_events work_submissions
            events = con.execute(
                "SELECT id, event_metadata_json FROM attempt_events WHERE attempt_id = ? AND event_type = 'work_submission'",
                (att["id"],),
            ).fetchall()
            for ev in events:
                try:
                    meta = json.loads(ev["event_metadata_json"] or "{}")
                except Exception:
                    meta = {}
                if meta.get("exercise_revision") is None or not meta.get("exercise_content_hash"):
                    meta["exercise_revision"] = 1
                    meta["exercise_content_hash"] = c_hash
                    con.execute(
                        "UPDATE attempt_events SET event_metadata_json = ? WHERE id = ?",
                        (json.dumps(meta), ev["id"]),
                    )
            # Update evidence
            con.execute(
                "UPDATE evidence SET exercise_revision = 1, exercise_content_hash = ? WHERE attempt_id = ? AND (exercise_revision IS NULL OR exercise_content_hash IS NULL)",
                (c_hash, att["id"]),
            )

    # Inspect assessment_items
    quarantined_items_count = 0
    scored_items = con.execute(
        "SELECT * FROM assessment_items WHERE points_awarded IS NOT NULL OR score_status = 'scored'"
    ).fetchall()
    for item in scored_items:
        should_quarantine = False
        quarantine_reason = ""
        att_id = item["attempt_id"]
        if not att_id:
            should_quarantine = True
            quarantine_reason = "Assessment item scored without linked attempt."
        else:
            att = con.execute("SELECT * FROM attempts WHERE id = ?", (att_id,)).fetchone()
            ex_ver = con.execute("SELECT * FROM exercise_versions WHERE id = ?", (item["exercise_version_id"],)).fetchone()
            if not att or not ex_ver:
                should_quarantine = True
                quarantine_reason = "Linked attempt or exercise version not found."
            else:
                try:
                    rev_hist = json.loads(ex_ver["revision_history_json"] or "[]")
                except Exception:
                    rev_hist = []
                current_rev = len(rev_hist) + 1
                try:
                    subparts = json.loads(ex_ver["subparts_json"] or "[]")
                except Exception:
                    subparts = []
                try:
                    rubric = json.loads(ex_ver["rubric_json"] or "{}")
                except Exception:
                    rubric = {}
                current_hash = compute_exercise_version_hash(
                    ex_ver["question_text"],
                    ex_ver["reference_solution"],
                    rubric,
                    subparts,
                )

                if att["exercise_revision"] is None or att["exercise_content_hash"] is None:
                    should_quarantine = True
                    quarantine_reason = f"Linked attempt '{att_id}' has unresolved educational identity."
                elif att["exercise_revision"] != current_rev or att["exercise_content_hash"] != current_hash:
                    should_quarantine = True
                    quarantine_reason = f"Linked attempt '{att_id}' is for outdated exercise revision {att['exercise_revision']} (current revision is {current_rev})."
                else:
                    try:
                        ev_ids = json.loads(item["evidence_ids_json"] or "[]")
                    except Exception:
                        ev_ids = []
                    if not ev_ids:
                        should_quarantine = True
                        quarantine_reason = "No supporting evidence IDs recorded for scored item."
                    else:
                        for eid in ev_ids:
                            ev = con.execute("SELECT * FROM evidence WHERE id = ?", (eid,)).fetchone()
                            if not ev or ev["status"] != "active":
                                should_quarantine = True
                                quarantine_reason = f"Supporting evidence '{eid}' is not active."
                                break
                            if ev["exercise_revision"] is None or ev["exercise_content_hash"] is None:
                                should_quarantine = True
                                quarantine_reason = f"Supporting evidence '{eid}' has unresolved educational identity."
                                break
                            if ev["exercise_revision"] != current_rev or ev["exercise_content_hash"] != current_hash:
                                should_quarantine = True
                                quarantine_reason = f"Supporting evidence '{eid}' is for outdated exercise revision {ev['exercise_revision']}."
                                break

        if should_quarantine:
            quarantined_items_count += 1
            try:
                hist = json.loads(item["score_history_json"] or "[]")
            except Exception:
                hist = []
            hist.append({
                "action": "invalidated_unresolved_or_outdated_identity",
                "previous_points": item["points_awarded"],
                "previous_score_status": item["score_status"],
                "reason": f"Legacy assessment item scored with outdated or unresolved educational identity; quarantined to pending_review. ({quarantine_reason})",
                "recorded_at": now,
            })
            con.execute(
                """
                UPDATE assessment_items SET
                    points_awarded = NULL,
                    score_status = 'pending_review',
                    score_history_json = ?
                WHERE id = ?
                """,
                (json.dumps(hist), item["id"]),
            )
            con.execute(
                "UPDATE assessments SET status = 'open' WHERE id = ?",
                (item["assessment_id"],),
            )

    return {
        "resolved_attempts_count": resolved_attempts_count,
        "quarantined_items_count": quarantined_items_count,
    }


def repair_historical_scores_and_rebuild_projections(con: sqlite3.Connection) -> Dict[str, Any]:
    """Repair historical scores, quarantine incompatible evidence, and rebuild projections (Migration 008).

    1. Backs up assessment_items, assessments, evidence, topic_state, and attempt_events to backup_v7_* tables.
    2. Quarantines active evidence whose provenance chain is unresolved or incompatible with current exercise version.
    3. Revalidates scored assessment items against complete scoring policy:
       - required subparts completeness
       - presence of active evaluated evidence
       - score vs evidence alignment (zero score requires evaluated incorrect work, positive score requires positive work)
       Quarantines invalid items to pending_review with audit history, reopening affected assessments.
    4. Rebuilds all topic_state projections inside the migration transaction using the shared eligibility policy.
    """
    now = datetime.now(timezone.utc).isoformat()

    # 1. Back up tables
    for tbl in ["assessment_items", "assessments", "evidence", "topic_state", "attempt_events"]:
        cnt = con.execute(f"SELECT COUNT(*) FROM backup_v7_{tbl}").fetchone()[0]
        if cnt == 0:
            con.execute(f"INSERT INTO backup_v7_{tbl} SELECT * FROM {tbl};")

    # 2. Quarantine active evidence failing provenance chain
    quarantined_evidence_count = 0
    active_ev_rows = con.execute("SELECT * FROM evidence WHERE status = 'active'").fetchall()
    for ev in active_ev_rows:
        ex_ver_id = ev["exercise_version_id"]
        ex_row = con.execute("SELECT * FROM exercise_versions WHERE id = ?", (ex_ver_id,)).fetchone()
        should_quarantine = False
        quarantine_reason = ""
        if not ex_row:
            should_quarantine = True
            quarantine_reason = f"Exercise version '{ex_ver_id}' not found."
        else:
            try:
                rev_hist = json.loads(ex_row["revision_history_json"] or "[]")
            except Exception:
                rev_hist = []
            current_rev = len(rev_hist) + 1
            try:
                subparts = json.loads(ex_row["subparts_json"] or "[]")
            except Exception:
                subparts = []
            try:
                rubric = json.loads(ex_row["rubric_json"] or "{}")
            except Exception:
                rubric = {}
            current_hash = compute_exercise_version_hash(
                ex_row["question_text"],
                ex_row["reference_solution"],
                rubric,
                subparts,
            )
            chain_ok, reason = check_evidence_eligibility_chain(con, ev, current_rev, current_hash)
            if not chain_ok:
                should_quarantine = True
                quarantine_reason = reason

        if should_quarantine:
            quarantined_evidence_count += 1
            con.execute(
                "UPDATE evidence SET status = 'pending_review', updated_at = ? WHERE id = ?",
                (now, ev["id"]),
            )

    # 3. Revalidate and quarantine historical scores in assessment_items
    quarantined_items_count = 0
    scored_items = con.execute(
        "SELECT * FROM assessment_items WHERE points_awarded IS NOT NULL OR score_status IN ('scored', 'partially_scored')"
    ).fetchall()
    for item in scored_items:
        should_quarantine = False
        quarantine_reason = ""
        att_id = item["attempt_id"]
        if not att_id:
            should_quarantine = True
            quarantine_reason = "Assessment item scored without linked attempt."
        else:
            att = con.execute("SELECT * FROM attempts WHERE id = ?", (att_id,)).fetchone()
            ex_ver = con.execute("SELECT * FROM exercise_versions WHERE id = ?", (item["exercise_version_id"],)).fetchone()
            if not att or not ex_ver:
                should_quarantine = True
                quarantine_reason = "Linked attempt or exercise version not found."
            else:
                try:
                    rev_hist = json.loads(ex_ver["revision_history_json"] or "[]")
                except Exception:
                    rev_hist = []
                current_rev = len(rev_hist) + 1
                try:
                    subparts = json.loads(ex_ver["subparts_json"] or "[]")
                except Exception:
                    subparts = []
                try:
                    rubric = json.loads(ex_ver["rubric_json"] or "{}")
                except Exception:
                    rubric = {}
                current_hash = compute_exercise_version_hash(
                    ex_row["question_text"] if "question_text" in ex_ver.keys() else ex_ver["question_text"],
                    ex_ver["reference_solution"],
                    rubric,
                    subparts,
                )

                if not is_identity_resolved(att["exercise_revision"], att["exercise_content_hash"]):
                    should_quarantine = True
                    quarantine_reason = f"Linked attempt '{att_id}' has unresolved educational identity."
                elif att["exercise_revision"] != current_rev or att["exercise_content_hash"] != current_hash:
                    should_quarantine = True
                    quarantine_reason = f"Linked attempt '{att_id}' is for outdated exercise revision {att['exercise_revision']} (current revision is {current_rev})."
                else:
                    try:
                        ev_ids = json.loads(item["evidence_ids_json"] or "[]")
                    except Exception:
                        ev_ids = []

                    active_evs_for_att = con.execute(
                        "SELECT * FROM evidence WHERE attempt_id = ? AND status = 'active'",
                        (att_id,),
                    ).fetchall()
                    if ev_ids:
                        matching_evs = [e for e in active_evs_for_att if e["id"] in ev_ids]
                    else:
                        matching_evs = list(active_evs_for_att)

                    evaluated_evs = [e for e in matching_evs if e["demonstrated_level"] in EVALUATED_DEMONSTRATED_LEVELS]

                    if not evaluated_evs:
                        should_quarantine = True
                        quarantine_reason = "Historical item has missing evaluated evidence (observation-only or no supporting evaluated evidence)."
                    else:
                        ineligible_evs = []
                        for ev in evaluated_evs:
                            ok, r = check_evidence_eligibility_chain(con, ev, current_rev, current_hash)
                            if not ok:
                                ineligible_evs.append((ev, r))
                        if ineligible_evs:
                            should_quarantine = True
                            quarantine_reason = f"Supporting evaluated evidence failed provenance eligibility chain: {ineligible_evs[0][1]}."
                        else:
                            req_subparts = get_required_subparts(subparts)
                            evaluated_subparts = {
                                e["subpart_key"]
                                for e in evaluated_evs
                                if e["subpart_key"]
                            }
                            missing_sub = req_subparts - evaluated_subparts
                            if missing_sub:
                                should_quarantine = True
                                quarantine_reason = f"Declared subparts missing evaluated evidence: {sorted(missing_sub)}."
                            else:
                                pts = item["points_awarded"]
                                if pts is not None:
                                    has_positive = any(
                                        e["demonstrated_level"] in ("independent_mastery", "assisted_success", "partial_progress")
                                        for e in evaluated_evs
                                    )
                                    has_incorrect = any(
                                        e["demonstrated_level"] == "incorrect"
                                        for e in evaluated_evs
                                    )
                                    if pts > 0 and not has_positive:
                                        should_quarantine = True
                                        quarantine_reason = f"Points awarded {pts} > 0 but all evaluated evidence is incorrect."
                                    elif pts == 0 and not has_incorrect:
                                        should_quarantine = True
                                        quarantine_reason = "Points awarded is 0 but all evaluated evidence is positive (zero score requires evaluated incorrect work)."

        if should_quarantine:
            quarantined_items_count += 1
            try:
                hist = json.loads(item["score_history_json"] or "[]")
            except Exception:
                hist = []
            for h in hist:
                if "reason" not in h:
                    h["reason"] = ""
            hist.append({
                "action": "quarantined_by_migration_008",
                "previous_points": item["points_awarded"],
                "previous_score_status": item["score_status"],
                "reason": f"Historical assessment item score invalid under current policy: {quarantine_reason}",
                "recorded_at": now,
            })
            con.execute(
                """
                UPDATE assessment_items SET
                    points_awarded = NULL,
                    score_status = 'pending_review',
                    score_history_json = ?
                WHERE id = ?
                """,
                (json.dumps(hist), item["id"]),
            )
            con.execute(
                "UPDATE assessments SET status = 'open', updated_at = ? WHERE id = ?",
                (now, item["assessment_id"]),
            )

    # 4. Rebuild topic_state projections
    from .repositories import EvidenceRepository
    evidence_repo = EvidenceRepository(con)
    all_topic_pairs = set()
    for r in con.execute("SELECT course_id, id FROM topics").fetchall():
        all_topic_pairs.add((r["course_id"], r["id"]))
    for r in con.execute("SELECT course_id, topic_id FROM topic_state").fetchall():
        all_topic_pairs.add((r["course_id"], r["topic_id"]))

    for cid, tid in all_topic_pairs:
        evidence_repo.recompute_topic_state(cid, tid)

    return {
        "quarantined_evidence_count": quarantined_evidence_count,
        "quarantined_items_count": quarantined_items_count,
        "rebuilt_topic_states_count": len(all_topic_pairs),
    }


def run_migrations(con: sqlite3.Connection, auto_quarantine_duplicates: bool = True) -> None:
    """Ensure schema_migrations exists and apply any pending migrations in order."""
    with atomic_transaction(con):
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT NOT NULL
            );
            """
        )

        cursor = con.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
        applied_versions = {row[0] for row in cursor.fetchall()}

        for version, desc, sql in MIGRATIONS:
            if version not in applied_versions:
                if version == 5:
                    duplicates = detect_legacy_duplicate_attempt_links(con)
                    if duplicates:
                        if not auto_quarantine_duplicates:
                            dup_ids = [d["attempt_id"] for d in duplicates]
                            all_item_ids = [it["id"] for d in duplicates for it in d["items"]]
                            raise LegacyDuplicateAttemptLinkError(
                                duplicate_attempt_ids=dup_ids,
                                affected_items=all_item_ids,
                                details={
                                    "reason": "Legacy schema-v4 workspace contains duplicate attempt links in assessment items. Auto-quarantine disabled.",
                                    "duplicates": duplicates,
                                },
                            )
                        quarantine_legacy_duplicate_attempt_links(con)

                _execute_sql_script(con, sql)

                if version == 7:
                    resolve_and_quarantine_legacy_identities(con)

                if version == 8:
                    repair_historical_scores_and_rebuild_projections(con)

                if version == 9:
                    from ..questions.catalog import QuestionCatalog, index_question
                    for row in con.execute("SELECT id, course_id, question_text FROM exercise_versions"):
                        index_question(con, row["id"], row["course_id"], row["question_text"])
                    for source in con.execute("SELECT v.id,v.course_id FROM source_versions v JOIN sources s ON s.id=v.source_id WHERE s.role IN ('exam','past_exam')"):
                        QuestionCatalog(con).catalog(source["course_id"], source["id"])

                if version == 10:
                    # Preserve pre-upgrade score/projection snapshots before
                    # the new visual gate withdraws unsupported confirmations.
                    con.execute('CREATE TABLE backup_v9_assessment_items AS SELECT * FROM assessment_items')
                    con.execute('CREATE TABLE backup_v9_topic_state AS SELECT * FROM topic_state')
                    from ..questions.catalog import refresh_review_dependents
                    for row in con.execute('''SELECT q.exercise_version_id FROM question_occurrences q
                        WHERE EXISTS (SELECT 1 FROM assessment_items i WHERE i.exercise_version_id=q.exercise_version_id)''').fetchall():
                        refresh_review_dependents(con, row['exercise_version_id'], rebuild_topics=False)
                    from .repositories import EvidenceRepository
                    evidence_repo = EvidenceRepository(con)
                    for topic in con.execute('''SELECT DISTINCT e.course_id,e.topic_id FROM evidence e
                        JOIN question_occurrences q ON q.exercise_version_id=e.exercise_version_id''').fetchall():
                        evidence_repo.recompute_topic_state(topic['course_id'], topic['topic_id'])

                con.execute(
                    "INSERT INTO schema_migrations (version, applied_at, description) VALUES (?, datetime('now'), ?)",
                    (version, desc),
                )

