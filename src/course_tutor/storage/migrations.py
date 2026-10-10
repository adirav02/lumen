"""Database migrations runner and schema definition."""

import sqlite3
from typing import List, Tuple
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


def run_migrations(con: sqlite3.Connection) -> None:
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
                _execute_sql_script(con, sql)
                con.execute(
                    "INSERT INTO schema_migrations (version, applied_at, description) VALUES (?, datetime('now'), ?)",
                    (version, desc),
                )
