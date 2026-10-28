"""Public-API reference regression with reviewed source identities."""
import pytest
from pathlib import Path
from course_tutor.api import LumenCore
from course_tutor.errors import ValidationError
from course_tutor.assessment.export import render_paper_html


def bank(core, path, language=False):
    path.write_text(path.name+'\nQuestion 1 Setup\na) Let x = 3.\nQuestion 2 Follow-up\n' +
                    ('השתמשו בתוצאה משאלה 1(a).' if language else 'Use the result from Question 1(a).'))
    sid = core.ingest_source('c', path, role='exam')['data']['source_version_id']
    qs = {q['question_key']: q for q in core.list_questions('c', sid)['questions']}
    for q in qs.values():
        core.review_question_occurrence('c', q['id'], q['revision'], 'accepted', 'Checked synthetic wording')
        core.validate_exercise_version(q['exercise_version_id'], expected_revision=1,
            reference_solution='x=3', rubric={'max_points': 5}, checks={'computed': True})
    return qs


@pytest.mark.parametrize('hebrew', [False, True])
def test_reviewed_references_use_final_number(tmp_path, hebrew):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C', course_id='c')
        qs = bank(c, tmp_path/'exam.txt', hebrew)
        c.annotate_question('c', qs['2']['id'], 2, {'depends_on': [
            {'exercise_version_id': qs['1']['exercise_version_id'], 'part': 'a'}]})
        filler = c.create_exercise('c', 'filler', 'Calculate 2+2.', reference_solution='4', rubric={'max_points': 1})['exercise_version_id']
        c.validate_exercise_version(filler, expected_revision=1, checks={'computed': True})
        aid = c.create_assessment('c', 'Reference', {}, [filler, qs['1']['exercise_version_id'], qs['2']['exercise_version_id']])['data']['assessment_id']
        html = render_paper_html(c.assessment_paper(aid))
        assert ('שאלה 2(a)' if hebrew else 'Question 2(a)') in html
        original = c.student_preview('c', qs['2']['exercise_version_id'])['question_text']
        assert ('שאלה 1(a)' if hebrew else 'Question 1(a)') in original


def test_unreviewed_reference_blocks_delivery(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C', course_id='c')
        qs = bank(c, tmp_path/'exam.txt')
        with pytest.raises(ValidationError, match='reference'):
            aid = c.create_assessment('c', 'Unsafe', {}, [qs['1']['exercise_version_id'], qs['2']['exercise_version_id']])['data']['assessment_id']
            c.assessment_paper(aid)


def test_same_numbers_in_other_source_do_not_resolve_implicitly(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C', course_id='c')
        a=bank(c,tmp_path/'a.txt'); b=bank(c,tmp_path/'b.txt')
        q=a['2']; target=b['1']['exercise_version_id']
        c.annotate_question('c',q['id'],2,{'depends_on':[{'exercise_version_id':target,'part':'a'}]})
        with pytest.raises(ValidationError,match='reference'):
            c.create_assessment('c','Ambiguous sources',{},[target,q['exercise_version_id']])
        current=next(x for x in c.list_questions('c',limit=100)['questions'] if x['id']==q['id'])
        c.annotate_question('c',q['id'],current['revision'],{'depends_on':[{'exercise_version_id':target,'part':'a','reference_text':'Question 1(a)'}]})
        aid=c.create_assessment('c','Reviewed cross-source',{},[target,q['exercise_version_id']])['data']['assessment_id']
        assert 'Question 1(a)' in render_paper_html(c.assessment_paper(aid))
        with pytest.raises(ValidationError,match='prerequisites'):
            c.create_assessment('c','Missing target',{},[q['exercise_version_id']])


def test_saved_reference_presentation_survives_bank_change(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C',course_id='c')
        qs=bank(c,tmp_path/'a.txt')
        c.annotate_question('c',qs['2']['id'],2,{'depends_on':[{'exercise_version_id':qs['1']['exercise_version_id'],'part':'a'}]})
        bp={'slots':[{'id':'pair','count':2}], 'instructions':['Answer both.'], 'duration_minutes':20}
        result=c.assemble_exam('c','simulation',bp,42,'references-snapshot')['data']
        before=c.assessment_paper(result['assessment_id'])
        c.update_exercise_version(qs['1']['exercise_version_id'],question_text='Different setup.',expected_revision=1)
        assert c.assessment_paper(result['assessment_id'])==before
        exported=c.export_assessment(result['assessment_id'],output_directory=tmp_path/'reexport')
        assert 'Question 1(a)' in Path(exported['html_path']).read_text()


def test_manual_structured_subpart_keeps_wording_and_cross_source_reference(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C', course_id='c')
        a = bank(c, tmp_path/'a.txt'); b = bank(c, tmp_path/'b.txt')
        q = a['2']; target = b['1']['exercise_version_id']
        c.update_exercise_version(q['exercise_version_id'], question_text='Follow-up.',
            subparts=[{'key': 'b', 'text': 'Use Question 1(a) to compute twice x.'}], expected_revision=1)
        current = next(x for x in c.list_questions('c', limit=100)['questions'] if x['id']==q['id'])
        c.review_question_occurrence('c', q['id'], current['revision'], 'accepted', 'Checked structured subpart.')
        c.validate_exercise_version(q['exercise_version_id'], expected_revision=2, checks={'computed': True})
        current = next(x for x in c.list_questions('c', limit=100)['questions'] if x['id']==q['id'])
        c.annotate_question('c', q['id'], current['revision'], {'depends_on': [{
            'exercise_version_id': target, 'part': 'a', 'from_part': 'b', 'reference_text': 'Question 1(a)'}]})
        filler = c.create_exercise('c', 'filler', 'Calculate 2+2.', reference_solution='4', rubric={'max_points': 1})['exercise_version_id']
        c.validate_exercise_version(filler, expected_revision=1, checks={'computed': True})
        aid = c.create_assessment('c', 'Structured reference', {}, [filler, target, q['exercise_version_id']])['data']['assessment_id']
        html = render_paper_html(c.assessment_paper(aid))
        assert 'Use Question 2(a) to compute twice x.' in html
        assert 'Use Question 1(a)' not in html


def test_two_reviewed_targets_for_same_reference_block_as_ambiguous(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C', course_id='c')
        a=bank(c,tmp_path/'a.txt'); b=bank(c,tmp_path/'b.txt')
        c.annotate_question('c',a['2']['id'],2,{'depends_on':[
            {'exercise_version_id':q['exercise_version_id'], 'part':'a', 'reference_text':'Question 1(a)'}
            for q in (a['1'],b['1'])]})
        with pytest.raises(ValidationError,match='ambiguous question reference.*review depends_on'):
            c.create_assessment('c','Ambiguous',{},[a['1']['exercise_version_id'],b['1']['exercise_version_id'],a['2']['exercise_version_id']])


def test_structured_source_parts_disambiguate_identical_reference_quotes(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C', course_id='c')
        a=bank(c,tmp_path/'a.txt'); b=bank(c,tmp_path/'b.txt'); q=a['2']
        c.update_exercise_version(q['exercise_version_id'], question_text='Two reviewed cases.',
            subparts=[{'key':key,'text':f'{key}) Use Question 1(a).'} for key in ('a','b')], expected_revision=1)
        current=next(x for x in c.list_questions('c',limit=100)['questions'] if x['id']==q['id'])
        c.review_question_occurrence('c',q['id'],current['revision'],'accepted','Compared both source-part contexts.')
        c.validate_exercise_version(q['exercise_version_id'],expected_revision=2,checks={'computed':True})
        current=next(x for x in c.list_questions('c',limit=100)['questions'] if x['id']==q['id'])
        c.annotate_question('c',q['id'],current['revision'],{'depends_on':[
            {'exercise_version_id':target['exercise_version_id'],'part':'a','from_part':key,'reference_text':'Question 1(a)'}
            for key,target in [('a',a['1']),('b',b['1'])]]})
        aid=c.create_assessment('c','Scoped parts',{},[a['1']['exercise_version_id'],b['1']['exercise_version_id'],q['exercise_version_id']])['data']['assessment_id']
        html=render_paper_html(c.assessment_paper(aid))
        assert 'a) Use Question 1(a).' in html and 'b) Use Question 2(a).' in html
