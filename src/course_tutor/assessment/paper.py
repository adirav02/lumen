"""Student-safe paper snapshots, independent of grading and reference solutions."""

import json
from ..questions.assets import snapshot_assets

from ..errors import ValidationError
from ..student import student_paper
from ..models import compute_exercise_version_hash
from ..storage.repositories import AssemblyRepository, AssessmentRepository, ExerciseRepository


def assembly_paper(con, job):
    """Project a private saved job into student fields, including pending jobs.

    Choice presentation and content hashes stay private: options are already in
    the exact question text and their checked mapping may contain answer keys.
    """
    questions = []
    for item in AssemblyRepository(con).items(job['request_id']):
        saved = item['snapshot']
        source = saved.get('source_reference')
        reference = None
        if source:
            reference = {key: source.get(key) for key in (
                'source_version_id', 'question_key', 'original_filename', 'version_num')}
            reference['source_spans'] = [
                {key: span[key] for key in ('label', 'page', 'slide') if key in span}
                for span in source.get('source_spans', [])]
        subparts = []
        for part in saved.get('subparts', []):
            if isinstance(part, str):
                subparts.append({'key': part, 'required': True})
            else:
                public = {'key': part.get('key', part.get('subpart_key', part.get('id'))),
                          'required': part.get('required', True)}
                public.update({key: part[key] for key in ('text', 'question_text') if key in part})
                subparts.append(public)
        questions.append({'item_order': item['item_order'],
            'exercise_version_id': item['exercise_version_id'],
            'question_text': saved['question_text'], 'student_assets': saved.get('student_assets', []),
            **({'presentation_text': saved['presentation']['presentation_text']} if 'presentation' in saved else {}),
            'subparts': saved.get('presentation', {}).get('subparts', subparts),
            'source_reference': reference, 'section': saved.get('section'),
            'max_points': item['max_points']})
    if not questions:
        raise ValidationError('Assessment contains no selected questions.')
    return student_paper({'assessment_id': job['assessment_id'], 'course_id': job['course_id'],
            'title': job['generation'].get('title') or 'Exam',
            **{k: job['generation'].get('effective_blueprint', job['generation']['blueprint'])[k] for k in ('instructions', 'duration_minutes')
               if k in job['generation'].get('effective_blueprint', job['generation']['blueprint'])}, 'questions': questions})


def assessment_paper(con, assessment_id, course_id=None, file_store=None):
    job = AssemblyRepository(con).get_by_assessment(assessment_id)
    if job and job['state'] == 'published':
        if course_id is not None and job['course_id'] != course_id:
            raise ValidationError('Assessment not found in the requested course.')
        return assembly_paper(con, job)
    assessments = AssessmentRepository(con)
    assessment = assessments.get_assessment(assessment_id)
    if not assessment or (course_id is not None and assessment.course_id != course_id):
        raise ValidationError('Assessment not found in the requested course.')
    questions = []
    exercises = ExerciseRepository(con)
    for item in assessments.get_items(assessment_id):
        version = exercises.get_exercise_version(item.exercise_version_id)
        if not version or version.course_id != assessment.course_id or version.validation_state != 'validated':
            raise ValidationError('Assessment contains an absent, cross-course or unvalidated exercise.')
        source = con.execute('''SELECT q.source_version_id,q.question_key,q.source_spans_json,
            q.review_status,q.visual_review_status,sv.original_filename,sv.version_num,sv.file_hash
            FROM question_occurrences q JOIN source_versions sv ON sv.id=q.source_version_id
            WHERE q.exercise_version_id=? AND q.course_id=? AND sv.course_id=?''',
            (version.id, assessment.course_id, assessment.course_id)).fetchone()
        if source and (source['review_status'] != 'accepted' or source['visual_review_status'] not in ('verified', 'not_required')):
            raise ValidationError('Assessment source review is no longer applicable.')
        questions.append({
            'item_order': item.item_order, 'exercise_version_id': version.id,
            'exercise_revision': len(version.revision_history)+1,
            'exercise_content_hash': compute_exercise_version_hash(version.question_text, version.reference_solution, version.rubric, version.subparts),
            'question_text': version.question_text, 'max_points': item.max_points,
            'subparts': version.subparts,
            'student_assets': snapshot_assets(con, assessment.course_id, version.rubric, file_store),
            'source_reference': ({'source_version_id': source['source_version_id'],
                'question_key': source['question_key'], 'original_filename': source['original_filename'],
                'version_num': source['version_num'], 'file_hash': source['file_hash'],
                'source_spans': json.loads(source['source_spans_json'])} if source else None),
        })
    if not questions:
        raise ValidationError('Assessment contains no selected questions.')
    from .references import resolve
    from ..questions.constraints import load
    questions = resolve(questions, load(con, assessment.course_id))
    return student_paper({'assessment_id': assessment.id, 'course_id': assessment.course_id,
            'title': assessment.title,
            **{k: assessment.blueprint[k] for k in ('instructions', 'duration_minutes')
               if k in (assessment.blueprint or {})}, 'questions': sorted(questions, key=lambda q:q['item_order'])})
