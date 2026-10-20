"""Atomic, individually validated catalog and metadata batches without model calls."""
from ..errors import LumenError, ValidationError
from ..storage.db import atomic_transaction
from .catalog import QuestionCatalog, require_text
from .review import QuestionReview


def compose_question_text(stem, context_blocks):
    """Set complete canonical text, reusing already included context on retries."""
    require_text(stem, 'question_text')
    if not isinstance(context_blocks, list) or any(not isinstance(c, str) or not c.strip() for c in context_blocks):
        raise ValidationError('context_blocks must be a list of nonempty strings.')
    result = stem
    for context in dict.fromkeys(context_blocks):
        if context not in result:
            result += '\n\n'+context
    return result


def batch_questions(con, course_id, items):
    if not isinstance(items, list) or not 1 <= len(items) <= 500:
        raise ValidationError('items must contain 1 to 500 catalog_candidate or annotate objects.')
    results, rejected = [], []
    catalog, review = QuestionCatalog(con), QuestionReview(con)
    for index, item in enumerate(items):
        try:
            with atomic_transaction(con):
                if not isinstance(item, dict):
                    raise ValidationError('Each item must be an object.')
                operation = item.get('operation')
                if operation == 'catalog_candidate':
                    if set(item)-{'operation','source_version_id','exam_label','question','metadata'}:
                        raise ValidationError('Unsupported catalog_candidate fields.')
                    question = item.get('question')
                    if not isinstance(question, dict):
                        raise ValidationError('question must be an object.')
                    source = item.get('source_version_id')
                    catalog.catalog(course_id, source, [question], item.get('exam_label'))
                    row = con.execute('SELECT * FROM question_occurrences WHERE course_id=? AND source_version_id=? AND question_key=?',
                                      (course_id, source, question['question_key'])).fetchone()
                    result = {'occurrence_id': row['id'], 'exercise_version_id': row['exercise_version_id'], 'revision': row['revision']}
                    if 'metadata' in item:
                        result.update(review.annotate(course_id, row['id'], row['revision'], item['metadata']))
                elif operation == 'annotate':
                    if set(item)-{'operation','occurrence_id','expected_revision','metadata','solution_links'}:
                        raise ValidationError('Unsupported annotate fields.')
                    result = review.annotate(course_id, item.get('occurrence_id'), item.get('expected_revision'),
                                             item.get('metadata'), item.get('solution_links'))
                else:
                    raise ValidationError('operation must be catalog_candidate or annotate.')
                results.append({'index': index, **result})
        except LumenError as exc:
            rejected.append({'index': index, **exc.to_dict()})
    if rejected:
        # The enclosing core transaction rolls back EVERY item and its receipt.
        raise ValidationError('Batch rejected; no items committed.', {'rejected_items': rejected, 'committed': False})
    return {'items': results, 'committed': True, 'count': len(results)}
