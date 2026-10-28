"""Public readiness operations remain read-only and expose exact review targets."""
from course_tutor.api import LumenCore


def test_pending_candidates_have_scoped_review_operations(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C',course_id='c')
        source=tmp_path/'q.txt';source.write_text('Question 1: Compute 2+2.')
        sid=c.ingest_source('c',source,role='exam')['data']['source_version_id']
        q=c.list_questions('c',sid)['questions'][0]
        changes=c.con.total_changes
        report=c.blueprint_readiness('c',{'slots':[{'id':'s','count':1,'section':'short'}]})
        action=report['slots'][0]['review_actions'][0]
        assert action['exercise_version_id']==q['exercise_version_id']
        ops={o['operation']:o for o in action['operations']}
        assert {'review-question-occurrence','annotate-question','validate-exercise-version'}<=ops.keys()
        assert ops['review-question-occurrence']['target']=={'occurrence_id':q['id'],'expected_revision':q['revision']}
        assert ops['validate-exercise-version']['target']['expected_revision']==1
        assert c.con.total_changes==changes
        assert report['selection_variation']['status']=='infeasible'
        c.review_question_occurrence('c',q['id'],1,'accepted','Fixture compared.')
        c.annotate_question('c',q['id'],2,{'section':'short'})
        c.validate_exercise_version(q['exercise_version_id'],expected_revision=1,reference_solution='4',rubric={'max_points':1},checks={'fixture':True})
        assert c.blueprint_readiness('c',{'slots':[{'id':'s','count':1,'section':'short'}]})['selection_variation']['status']=='forced_selection'


def test_stale_relationship_is_actionable_without_reading_stems(tmp_path):
    from test_paper_references import bank
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C',course_id='c')
        qs=bank(c,tmp_path/'q.txt')
        c.annotate_question('c',qs['2']['id'],2,{'depends_on':[{'exercise_version_id':qs['1']['exercise_version_id'],'part':'a'}]})
        c.update_exercise_version(qs['1']['exercise_version_id'],subparts=[{'key':'a','text':'Revised setup.'}],expected_revision=1)
        report=c.blueprint_readiness('c',{'slots':[{'id':'s','count':2}]})
        action=next(a for a in report['slots'][0]['review_actions'] if a['exercise_version_id']==qs['2']['exercise_version_id'])
        assert action['stale_relationship']
        assert action['required_prerequisite_version_ids']==[qs['1']['exercise_version_id']]
        assert any(o['operation']=='annotate-question' for o in action['operations'])


def test_selection_status_preserves_budget_uncertainty(tmp_path,monkeypatch):
    from course_tutor.assessment import readiness
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C',course_id='c')
        for name in ('Prove the set inclusion.','Evaluate the geometric sum.'):
            v=c.create_exercise('c',name,name,reference_solution='Fixture',rubric={'max_points':1})['exercise_version_id']
            c.validate_exercise_version(v,expected_revision=1,checks={'fixture':True})
        bp={'slots':[{'id':'s','count':1}]}
        assert c.blueprint_readiness('c',bp)['selection_variation']['status']=='multiple_selections_available'
        monkeypatch.setattr(readiness,'SEARCH_NODE_BUDGET',1)
        report=c.blueprint_readiness('c',bp)
        assert report['analysis']['distinct_exams']['count'] is None
        assert report['selection_variation']['status']=='unknown'


def test_visual_pending_candidates_identify_actual_visual_operation(tmp_path):
    from pathlib import Path
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C',course_id='c')
        source=Path(__file__).parents[1]/'examples/HN101_Complete_Course/Final_examinations/HN-FE02_student.pdf'
        c.ingest_source('c',source,role='exam')
        report=c.blueprint_readiness('c',{'slots':[{'id':'s','count':1}]})
        op=next(o for a in report['slots'][0]['review_actions'] for o in a['operations'] if o['operation']=='review-question-visual')
        assert op['target']['occurrence_id'] and op['target']['expected_revision']>=1
        assert 'checks' in op['required_inputs'] and 'Open the actual' in op['review_requirement']
