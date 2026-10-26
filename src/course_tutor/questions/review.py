"""Separate source metadata/visual attestation from extraction and math validation."""

import json

from ..errors import ValidationError
from ..models import utc_now_iso, validate_finite_number
from .catalog import QuestionCatalog, require_text, refresh_review_dependents

MIGRATION_V10_SQL = """
ALTER TABLE exam_catalogs ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE question_occurrences ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE question_occurrences ADD COLUMN solution_links_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE question_occurrences ADD COLUMN visual_review_status TEXT NOT NULL DEFAULT 'pending_review';
ALTER TABLE question_occurrences ADD COLUMN visual_review_history_json TEXT NOT NULL DEFAULT '[]';
CREATE TABLE exam_catalog_aliases (
    source_version_id TEXT PRIMARY KEY REFERENCES source_versions(id) ON DELETE RESTRICT,
    canonical_source_version_id TEXT NOT NULL REFERENCES exam_catalogs(source_version_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_evidence_version_topic ON evidence(exercise_version_id,course_id,topic_id);
CREATE INDEX IF NOT EXISTS idx_assessment_items_version ON assessment_items(exercise_version_id);
UPDATE question_occurrences SET visual_review_status='not_required'
WHERE source_version_id IN (SELECT id FROM source_versions WHERE mime_type LIKE 'text/%');
"""


class QuestionReview(QuestionCatalog):
    def annotate(self, course_id, occurrence_id, expected_revision, metadata, solution_links=None):
        row = self.con.execute('SELECT * FROM question_occurrences WHERE id=? AND course_id=?', (occurrence_id, course_id)).fetchone()
        if not row:
            raise ValidationError('Question occurrence not found in this course.')
        self.check_revision(row, expected_revision, occurrence_id)
        if not isinstance(metadata, dict):
            raise ValidationError('metadata must be an object; unknown values should be null.')
        if metadata.get('points') is not None:
            validate_finite_number(metadata['points'], 'points', min_val=0)
        if metadata.get('year') is not None and (type(metadata['year']) is not int or not 1900 <= metadata['year'] <= 2200):
            raise ValidationError('year must be null or an integer between 1900 and 2200.')
        from .constraints import validate_metadata
        metadata = validate_metadata(self.con, course_id, row['exercise_version_id'], metadata)
        links = solution_links if solution_links is not None else json.loads(row['solution_links_json'])
        if not isinstance(links, list):
            raise ValidationError('solution_links must be a list.')
        for link in links:
            if not isinstance(link, dict) or not isinstance(link.get('source_version_id'), str):
                raise ValidationError('Each solution link needs a source_version_id.')
            self.source(course_id, link['source_version_id'])
        combined = {**json.loads(row['metadata_json']), **metadata}
        from .provenance import normalize_metadata
        combined = normalize_metadata(combined)
        history = json.loads(row['review_history_json']) + [{'action': 'annotated', 'previous_metadata': json.loads(row['metadata_json']),
            'previous_solution_links': json.loads(row['solution_links_json']), 'at': utc_now_iso()}]
        self.con.execute('UPDATE question_occurrences SET metadata_json=?,solution_links_json=?,review_history_json=?,revision=revision+1 WHERE id=?',
            (json.dumps(combined, ensure_ascii=False), json.dumps(links), json.dumps(history), occurrence_id))
        return {'occurrence_id': occurrence_id, 'revision': row['revision'] + 1, 'metadata': combined, 'solution_links': links}

    def review_visual(self, course_id, occurrence_id, expected_revision, status, notes, checks=None):
        require_text(notes, 'notes')
        if status not in ('verified', 'pending_review', 'rejected'):
            raise ValidationError('Invalid visual review status.')
        row = self.con.execute('SELECT * FROM question_occurrences WHERE id=? AND course_id=?', (occurrence_id, course_id)).fetchone()
        if not row:
            raise ValidationError('Question occurrence not found in this course.')
        self.check_revision(row, expected_revision, occurrence_id)
        if status == 'verified' and (not isinstance(checks, dict) or checks.get('source_render_checked') is not True or checks.get('formulas_options_diagrams_checked') is not True):
            raise ValidationError('Visual verification requires explicit source-render and formulas/options/diagrams checks.')
        history = json.loads(row['visual_review_history_json']) + [{'status': status, 'notes': notes, 'checks': checks, 'at': utc_now_iso()}]
        self.con.execute('UPDATE question_occurrences SET visual_review_status=?,visual_review_history_json=?,revision=revision+1 WHERE id=?',
            (status, json.dumps(history), occurrence_id))
        refresh_review_dependents(self.con, row['exercise_version_id'])
        return {'occurrence_id': occurrence_id, 'revision': row['revision']+1, 'visual_review_status': status}
