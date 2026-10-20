"""Synthetic equality, metadata provenance, and advisory-similarity regressions."""
from fractions import Fraction as F
import pytest
from course_tutor.api import LumenCore
from course_tutor.questions.answers import accepts_answer
from course_tutor.errors import ValidationError


def test_full_optimal_set_is_accepted_in_actual_evidence_grading(tmp_path):
    penalty=lambda q:sum(p*(7*max(d-q,0)+3*max(q-d,0)) for d,p in [(10,F(1,5)),(20,F(1,2)),(30,F(3,10))])
    optima=[q for q in range(41) if penalty(q)==min(penalty(x) for x in range(41))]
    assert optima==list(range(20,31)) and all(penalty(q)==27 for q in optima)
    rubric={'max_points':1,'answer_sets':{'optimal_q':{'values':optima}}}
    with LumenCore(tmp_path/'ws') as c:
        c.create_course('SYNTHETIC',course_id='s')
        topic=c.create_topic('s','Stock')['id']
        vid=c.create_exercise('s','stock','Choose an optimal integer stock.',reference_solution='All integers 20 through 30; minimum penalty 27.',rubric=rubric)['exercise_version_id']
        c.validate_exercise_version(vid,expected_revision=1,checks={'exact_enumeration':True})
        for value in [19,*optima,31]:
            attempt=c.start_attempt('s',vid)['data']['id']
            c.record_attempt_event(attempt,1,'work_submission',content=str(value))
            r=c.commit_evidence(attempt,[{'topic_id':topic,'skill_id':'stock','answer_set_key':'optimal_q'}])
            assert r['data']['evidence_created'][0]['demonstrated_level']==('independent_mastery' if value in optima else 'incorrect')
    with pytest.raises(ValidationError):
        accepts_answer(rubric,'optimal_q','No submitted scalar answer')


def test_filename_year_never_satisfies_verified_date_constraint(tmp_path):
    with LumenCore(tmp_path/'ws') as c:
        c.create_course('SYNTHETIC',course_id='s')
        file=tmp_path/'mid term 2026.txt';file.write_text('Question 1: Compute a synthetic value.')
        sid=c.ingest_source('s',file,role='exam')['data']['source_version_id']
        q=c.list_questions('s',sid)['questions'][0]
        assert q['metadata']['filename_years']==[2026] and q['metadata']['year'] is None
        c.review_question_occurrence('s',q['id'],1,'accepted','Checked native stem')
        c.validate_exercise_version(q['exercise_version_id'],expected_revision=1,checks={'checked':True},reference_solution='1',rubric={'max_points':1})
        c.annotate_question('s',q['id'],2,{'year':2026,'year_provenance':'filename'})
        bp={'slots':[{'id':'s','count':1,'year_min':2026,'year_max':2026}]}
        assert c.blueprint_readiness('s',bp)['slots'][0]['available']==0
        c.annotate_question('s',q['id'],3,{'year':2026,'year_provenance':'verified_exam_date','year_evidence':'Synthetic explicit sitting date on cover'})
        assert c.blueprint_readiness('s',bp)['slots'][0]['available']==1


def test_casefolded_lexical_overlap_is_advisory(tmp_path):
    with LumenCore(tmp_path/'ws') as c:
        c.create_course('SYNTHETIC',course_id='s')
        a=c.create_exercise('s','a','Calculate expected demand for the small stock warehouse.')['exercise_version_id']
        b=c.create_exercise('s','b','CALCULATE expected DEMAND for the larger stock warehouse!')['exercise_version_id']
        c.create_exercise('s','c','Prove a property of disconnected graphs.')
        report=c.lexical_question_overlap('s',a)
        assert report['candidates'][0]['exercise_version_id']==b
        assert report['candidates'][0]['status']=='advisory_tutor_review'
        assert 'does not prove novelty' in report['notes']
        assert not c.list_question_relations('s')['relations']  # Advisory does not assert equivalence.
