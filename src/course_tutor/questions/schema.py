"""Additive schema: originals, attempts and existing score histories stay intact."""

SCHEMA_SQL = """
CREATE TABLE exam_catalogs (
    source_version_id TEXT PRIMARY KEY REFERENCES source_versions(id) ON DELETE RESTRICT,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    exam_label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    revision INTEGER NOT NULL DEFAULT 1,
    review_history_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_exam_catalogs_course ON exam_catalogs(course_id, source_version_id);
CREATE TABLE question_occurrences (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    source_version_id TEXT NOT NULL REFERENCES exam_catalogs(source_version_id) ON DELETE RESTRICT,
    exercise_version_id TEXT NOT NULL UNIQUE REFERENCES exercise_versions(id) ON DELETE RESTRICT,
    question_key TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    source_spans_json TEXT NOT NULL,
    quality_flags_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending_review',
    revision INTEGER NOT NULL DEFAULT 1,
    review_history_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(source_version_id, question_key)
);
CREATE INDEX idx_question_occurrences_course ON question_occurrences(course_id, id);
CREATE TABLE question_fingerprints (
    exercise_version_id TEXT PRIMARY KEY REFERENCES exercise_versions(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL,
    exact_hash TEXT NOT NULL,
    structure_hash TEXT NOT NULL
);
CREATE INDEX idx_question_exact ON question_fingerprints(course_id, exact_hash);
CREATE INDEX idx_question_structure ON question_fingerprints(course_id, structure_hash);
CREATE VIRTUAL TABLE question_search USING fts5(exercise_version_id UNINDEXED, course_id UNINDEXED, question_text);
CREATE TABLE question_relations (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    left_version_id TEXT NOT NULL REFERENCES exercise_versions(id) ON DELETE RESTRICT,
    right_version_id TEXT NOT NULL REFERENCES exercise_versions(id) ON DELETE RESTRICT,
    left_hash TEXT NOT NULL,
    right_hash TEXT NOT NULL,
    kind TEXT NOT NULL,
    method TEXT NOT NULL,
    similarity REAL NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    review_history_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(left_version_id, right_version_id, left_hash, right_hash)
);
CREATE INDEX idx_question_relations_left ON question_relations(course_id, left_version_id, status);
CREATE INDEX idx_question_relations_right ON question_relations(course_id, right_version_id, status);
CREATE TABLE attempt_grades (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL,
    points_awarded REAL NOT NULL,
    max_points REAL NOT NULL,
    feedback TEXT NOT NULL,
    correctness TEXT NOT NULL,
    score_status TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    correction_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(attempt_id, revision)
);
CREATE INDEX idx_attempts_learner_question ON attempts(course_id, learner_id, exercise_version_id, id);
CREATE INDEX idx_exercises_course_family ON exercises(course_id, exercise_family);
CREATE INDEX idx_versions_course_validation ON exercise_versions(course_id, validation_state, created_at, id);
CREATE INDEX idx_evidence_attempt ON evidence(attempt_id, status);
CREATE INDEX idx_evidence_event ON evidence(event_id);
CREATE INDEX idx_assessments_learner ON assessments(course_id, learner_id, id);
"""
