"""Directional annotation and readiness regressions against isolated HN101 banks."""
import pytest

from course_tutor.errors import ValidationError
from test_assembly_quality import hn, final_bank


def test_directional_metadata_validation_staleness_cycles_and_receipts(hn):
    _, qs = final_bank(hn)
    occurrences = {q['exercise_version_id']: q for q in hn.list_questions('hn', limit=100)['questions']}
    q1, q2 = occurrences[qs['1']], occurrences[qs['2']]
    metadata = {'depends_on': [{'exercise_version_id': qs['1'], 'part': 'a', 'from_part': 'b'}]}
    first = hn.annotate_question('hn', q2['id'], q2['revision'], metadata, request_id='dependency')
    assert hn.annotate_question('hn', q2['id'], q2['revision'], metadata, request_id='dependency')['idempotent_replay']
    assert first['data']['metadata']['depends_on'][0]['target_hash']
    before = hn.con.total_changes
    for bad in ({'depends_on': 'bad'}, {'depends_on': [{'exercise_version_id': qs['1']}]},
                {'depends_on': [{'exercise_version_id': 'absent'}]},
                {'gives_away': [{'exercise_version_id': qs['1'], 'part': 'missing'}]}):
        with pytest.raises(ValidationError):
            hn.annotate_question('hn', q1['id'], q1['revision'], bad)
    assert hn.con.total_changes == before
    hn.create_course('Other', course_id='other')
    foreign = hn.create_exercise('other', 'foreign', 'Question')['exercise_version_id']
    with pytest.raises(ValidationError, match='course'):
        hn.annotate_question('hn', q1['id'], q1['revision'], {'depends_on': [{'exercise_version_id': foreign}]})
    with pytest.raises(ValidationError, match='prerequisites'):
        hn.create_assessment('hn', 'Forward reference', {}, [qs['2'], qs['1']])
    hn.annotate_question('hn', q1['id'], q1['revision'], {'depends_on': [{'exercise_version_id': qs['2']}]})
    with pytest.raises(ValidationError, match='prerequisites'):
        hn.create_assessment('hn', 'Cycle', {}, [qs['1'], qs['2']])
    # Removing the cycle doesn't make the dependent annotation apply to changed text.
    current = next(q for q in hn.list_questions('hn', limit=100)['questions'] if q['id'] == q1['id'])
    hn.annotate_question('hn', q1['id'], current['revision'], {'depends_on': []})
    hn.update_exercise_version(qs['1'], question_text='Revised prerequisite', expected_revision=1)
    current = next(q for q in hn.list_questions('hn', limit=100)['questions'] if q['id'] == q1['id'])
    hn.review_question_occurrence('hn', q1['id'], current['revision'], 'accepted', 'Rechecked changed fixture text')
    current = next(q for q in hn.list_questions('hn', limit=100)['questions'] if q['id'] == q1['id'])
    hn.review_question_visual('hn', q1['id'], current['revision'], 'verified', 'Rechecked fixture text',
        checks={'source_render_checked': True, 'formulas_options_diagrams_checked': True})
    hn.validate_exercise_version(qs['1'], expected_revision=2, checks={'fixture': True})
    with pytest.raises(ValidationError, match='stale constraints'):
        hn.create_assessment('hn', 'Stale relation', {}, [qs['1'], qs['2']])


def test_distinct_combinations_overlap_and_budget(hn, monkeypatch):
    sid, _ = final_bank(hn)
    bp = {'slots': [{'id': 'two', 'count': 2, 'source_version_ids': [sid]}]}
    report = hn.blueprint_readiness('hn', bp)
    assert report['analysis']['distinct_exams']['count'] == 28
    assert report['analysis']['capacity']['lower_bound'] == 4
    from course_tutor.assessment import readiness
    monkeypatch.setattr(readiness, 'SEARCH_NODE_BUDGET', 2)
    bounded = hn.blueprint_readiness('hn', bp)['analysis']['distinct_exams']
    assert not bounded['exact'] and bounded['count'] is None
    assert bounded['lower_bound'] <= 28 <= bounded['upper_bound']


@pytest.mark.parametrize('instructions', ['text', [None], [''], {'private': 'answer'}])
def test_invalid_instruction_schema_rejected(hn, instructions):
    with pytest.raises(ValidationError, match='instructions'):
        hn.blueprint_readiness('hn', {'slots': [{'id': 'one', 'count': 1}], 'instructions': instructions})


def test_existing_hn_annotations_are_backfilled_without_review_changes(hn):
    _, qs = final_bank(hn, '01')
    occurrence = next(q for q in hn.list_questions('hn', limit=100)['questions'] if q['exercise_version_id'] == qs['2'])
    hn.annotate_question('hn', occurrence['id'], occurrence['revision'], {'depends_on': []})
    with pytest.raises(ValidationError, match='prerequisites'):
        hn.create_assessment('hn', 'Legacy bank', {}, [qs['2']])
    result = hn.apply_known_question_constraints('hn', request_id='backfill')
    assert result['data']['count'] == 1
    current = next(q for q in hn.list_questions('hn', limit=100)['questions'] if q['id'] == occurrence['id'])
    assert current['review_status'] == 'accepted' and current['visual_review_status'] == 'verified'
    assert current['metadata']['depends_on'][0]['exercise_version_id'] == qs['1']


def test_changing_subparts_invalidates_relationship(hn):
    _, qs = final_bank(hn)
    q = next(q for q in hn.list_questions('hn', limit=100)['questions'] if q['exercise_version_id'] == qs['2'])
    hn.annotate_question('hn', q['id'], q['revision'], {'depends_on': [{'exercise_version_id': qs['1'], 'part': 'a'}]})
    hn.update_exercise_version(qs['1'], subparts=[{'key': 'a', 'text': 'Changed subpart'}], expected_revision=1)
    hn.validate_exercise_version(qs['1'], expected_revision=2, checks={'fixture': True})
    with pytest.raises(ValidationError, match='stale constraints'):
        hn.create_assessment('hn', 'Stale parts', {}, [qs['1'], qs['2']])
