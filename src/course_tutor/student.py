"""The allowlisted content boundary for student papers, previews and search.

Inputs are approved stems with their necessary setup/data already incorporated.
Never expand to originals, extracted sections, solution links or private references.
"""
from pathlib import Path
from .errors import ValidationError
from .storage.repositories import ExerciseRepository

QUESTION_FIELDS = ('item_order', 'exercise_version_id', 'question_text', 'section', 'max_points',
                   'exercise_revision', 'exercise_content_hash')


def student_question(question):
    public = {key: question[key] for key in QUESTION_FIELDS if key in question}
    public['subparts'] = []
    for part in question.get('subparts', []):
        if isinstance(part, str):
            public['subparts'].append({'key': part, 'required': True})
        else:
            safe = {'key': part.get('key', part.get('subpart_key', part.get('id'))),
                    'required': part.get('required', True)}
            safe.update({key: part[key] for key in ('text', 'question_text') if key in part})
            public['subparts'].append(safe)
    source = question.get('source_reference')
    public['source_reference'] = None
    if source:
        safe = {key: source.get(key) for key in ('source_version_id', 'question_key', 'original_filename', 'version_num')}
        if safe['original_filename']:
            safe['original_filename'] = Path(safe['original_filename']).name
        safe['source_spans'] = [{key: span[key] for key in ('label', 'page', 'slide') if key in span}
                                for span in source.get('source_spans', [])]
        public['source_reference'] = safe
    return public


def student_paper(paper):
    return {**{key: paper[key] for key in ('assessment_id', 'course_id', 'title') if key in paper},
            'questions': [student_question(q) for q in paper['questions']]}


def student_preview(con, course_id, version_id):
    version = ExerciseRepository(con).get_exercise_version(version_id)
    if not version or version.course_id != course_id or version.validation_state != 'validated':
        raise ValidationError('Student content requires a current validated question in this course.')
    source = con.execute('''SELECT q.*,sv.original_filename,sv.version_num FROM question_occurrences q
        JOIN source_versions sv ON sv.id=q.source_version_id
        WHERE q.exercise_version_id=? AND q.course_id=?''', (version_id, course_id)).fetchone()
    if source and (source['review_status'] != 'accepted' or source['visual_review_status'] not in ('verified', 'not_required')):
        raise ValidationError('Student content requires accepted extraction and applicable visual review.')
    import json
    reference = dict(source) if source else None
    if reference:
        reference['source_spans'] = json.loads(reference['source_spans_json'])
    return student_question({'exercise_version_id': version.id, 'question_text': version.question_text,
                             'subparts': version.subparts, 'source_reference': reference})


def student_search(con, course_id, query, limit=20):
    from .questions.catalog import page_size, require_text
    page_size(limit)
    require_text(query, 'query')
    # Deliberately search reviewed stems only. Raw FTS source snippets may include
    # embedded answers and must never be expanded from this surface.
    rows = con.execute('''SELECT v.id FROM exercise_versions v
        LEFT JOIN question_occurrences q ON q.exercise_version_id=v.id
        WHERE v.course_id=? AND v.validation_state='validated'
        AND (q.id IS NULL OR (q.review_status='accepted' AND q.visual_review_status IN ('verified','not_required')))
        AND instr(lower(v.question_text),lower(?))>0 ORDER BY v.id LIMIT ?''', (course_id, query, limit)).fetchall()
    return {'questions': [student_preview(con, course_id, row['id']) for row in rows],
            'scope': 'Validated reviewed stems, setups and data only; originals and private answers excluded.'}
