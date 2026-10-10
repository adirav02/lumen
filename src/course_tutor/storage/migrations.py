"""Database migrations runner and schema definition."""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from ..errors import LegacyDuplicateAttemptLinkError, ValidationError
from .db import atomic_transaction

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

MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "Initial schema for Lumen core with FTS5", MIGRATION_V1_SQL),
    (2, "Persist complete extracted sections and source locators", MIGRATION_V2_SQL),
    (3, "Track assessment item score status, audit history, and supporting evidence", MIGRATION_V3_SQL),
    (4, "Track learner ownership on assessments and revision history on exercise versions", MIGRATION_V4_SQL),
    (5, "Enforce unique non-null attempt-to-item link in assessment_items", MIGRATION_V5_SQL),
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
) -> Dict[str, Any]:
    """Actionable repair path for quarantined legacy duplicate attempt links."""
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
                # Read item score history
                it = con.execute("SELECT score_history_json FROM assessment_items WHERE id = ?", (item_id,)).fetchone()
                try:
                    hist = json.loads(it[0]) if it and it[0] else []
                except Exception:
                    hist = []
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
                        score_status = 'pending_review',
                        score_history_json = ?
                    WHERE id = ?
                    """,
                    (att_id, json.dumps(hist), item_id),
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
                resolved_list.append({"attempt_id": att_id, "assessment_item_id": item_id})

        remaining = con.execute(
            "SELECT attempt_id, assessment_item_id FROM legacy_duplicate_attempt_links WHERE resolution_status = 'quarantined'"
        ).fetchall()

        return {
            "resolved": resolved_list,
            "unresolved": [dict(r) for r in remaining],
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
                con.execute(
                    "INSERT INTO schema_migrations (version, applied_at, description) VALUES (?, datetime('now'), ?)",
                    (version, desc),
                )
