"""Real OOXML fidelity and independent verification gates for course imports."""
from pathlib import Path
from zipfile import ZipFile
import pytest
from course_tutor.api import LumenCore
from course_tutor.errors import LumenError
from course_tutor.ingestion.extractors import get_extractor
from course_tutor.storage.migrations import run_migrations


def docx(path):
    xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:p><w:r><w:t>Question 1: Compute </w:t></w:r><m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>n</m:t></m:r></m:den></m:f></m:oMath></w:p><w:p><w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>Option A</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>row</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'''
    with ZipFile(path,'w') as z:
        z.writestr('word/document.xml',xml)


def test_docx_retains_equation_structure_table_and_answer_cues(tmp_path):
    path=tmp_path/'exam.docx';docx(path)
    sections=get_extractor(path).extract(path)
    assert '(1)/(n)' in sections[0].text
    assert sections[0].metadata['math_xml'] and sections[0].quality_flag=='uncertain_math'
    assert sections[1].metadata['has_highlight_or_shading']
    assert sections[2].text=='row\tcell'
    assert all('page_index' not in s.metadata for s in sections)


def test_visual_review_metadata_solution_links_and_identical_upload_aliases(tmp_path):
    with LumenCore(tmp_path/'workspace') as core:
        core.create_course('Course',course_id='a');core.create_course('Other',course_id='b')
        path=tmp_path/'exam.docx';docx(path)
        sid=core.ingest_source('a',path,role='exam')['data']['source_version_id']
        q=core.list_questions('a',sid)['questions'][0]
        core.review_question_occurrence('a',q['id'],1,'accepted','Boundaries compared')
        core.validate_exercise_version(q['exercise_version_id'],expected_revision=1,reference_solution='1/n',rubric={'max_points':2},checks={'math':True})
        assert core.propose_practice('a')['candidates']==[]
        with pytest.raises(LumenError):
            core.create_assessment('a','Unreviewed visual',{},[q['exercise_version_id']],learner_id='mock')
        core.review_question_visual('a',q['id'],2,'verified','Rendered source compared',{'source_render_checked':True,'formulas_options_diagrams_checked':True})
        assert core.propose_practice('a')['candidates']
        core.annotate_question('a',q['id'],3,{'year':None,'points':2,'stable_id':'course/exam/open/1'},[{'source_version_id':sid,'status':'unverified'}])
        copy=core.ingest_source('a',path,logical_name='identical copy',role='exam')['data']
        assert copy['question_catalog']['duplicate_upload']
        assert len(core.list_questions('a')['questions'])==1
        assert core.list_questions('a',copy['source_version_id'])['questions'][0]['id']==q['id']
        foreign=core.ingest_source('b',path,role='solution')['data']['source_version_id']
        with pytest.raises(LumenError):
            core.annotate_question('a',q['id'],4,{},[{'source_version_id':foreign}])
        assert core.list_questions('a')['questions'][0]['metadata']['year'] is None


@pytest.mark.parametrize('filename',['old.doc','broken.docx'])
def test_unreadable_word_original_is_preserved_with_honest_unsupported_status(tmp_path,filename):
    path=tmp_path/filename;path.write_bytes(b'not a supported OOXML file')
    sections=get_extractor(path).extract(path)
    assert sections[0].quality_flag=='unsupported'
    with LumenCore(tmp_path/'ws') as core:
        core.create_course('Course',course_id='a')
        result=core.ingest_source('a',path,role='exam')['data']
        assert result['extraction_status']=='unsupported'
        region=core.read_source_region(result['source_version_id'])
        assert region['hash_verified'] and Path(region['absolute_path']).read_bytes()==path.read_bytes()
        assert core.list_questions('a')['questions']==[]


def test_question_search_is_course_scoped_and_does_not_return_private_keys(tmp_path):
    with LumenCore(tmp_path/'ws') as core:
        core.create_course('Algorithms',course_id='a');core.create_course('Other',course_id='b')
        for course in ['a','b']:
            core.create_exercise(course,'dp','חלוקה באמצעות תכנון דינמי',reference_solution='PRIVATE KEY')
        hits=core.search_questions('a','תכנון דינמי')['questions']
        assert len(hits)==1 and hits[0]['validation_state']=='pending_review'
        assert 'PRIVATE' not in str(hits)


@pytest.mark.parametrize('withdrawal',['review','upgrade'])
def test_withdrawing_visual_review_invalidates_scores_and_cached_mastery(tmp_path,withdrawal):
    with LumenCore(tmp_path/'ws') as core:
        core.create_course('Algorithms',course_id='a')
        topic=core.create_topic('a','Counting')['id']
        path=tmp_path/'exam.docx';docx(path)
        core.ingest_source('a',path,role='exam')
        q=core.list_questions('a')['questions'][0];version=q['exercise_version_id']
        core.review_question_occurrence('a',q['id'],1,'accepted','Checked boundaries')
        core.review_question_visual('a',q['id'],2,'verified','Compared rendered source',{'source_render_checked':True,'formulas_options_diagrams_checked':True})
        core.validate_exercise_version(version,expected_revision=1,reference_solution='1/n',rubric={'max_points':2},checks={'math':True})
        assessment=core.create_assessment('a','Quiz',{},[version],learner_id='alice')['data']['assessment_id']
        started=core.start_assessment_item_attempt(assessment,1,learner_id='alice')
        attempt=started['attempt']
        submission=core.record_attempt_event(attempt['id'],1,'work_submission',content='1/n')['data']['event']
        evidence=core.commit_evidence(attempt['id'],[{'topic_id':topic,'skill_id':'count','correct':True}],submission_event_id=submission['id'])['data']['evidence_created'][0]
        core.record_assessment_item_score(assessment,1,2)
        assert core.evidence_repo.get_topic_state('a',topic).independent_success_count==1
        if withdrawal=='review':
            core.review_question_visual('a',q['id'],3,'pending_review','A missing diagram needs another review')
        else:
            # Reconstruct the pre-v10 shape around a genuinely confirmed score.
            # Upgrade must preserve history and back it up before withdrawing it.
            core.con.execute('DROP TABLE exam_catalog_aliases')
            for column in ['metadata_json','solution_links_json','visual_review_status','visual_review_history_json']:
                core.con.execute(f'ALTER TABLE question_occurrences DROP COLUMN {column}')
            core.con.execute('ALTER TABLE exam_catalogs DROP COLUMN metadata_json')
            core.con.execute('DROP TABLE backup_v9_assessment_items')
            core.con.execute('DROP TABLE backup_v9_topic_state')
            core.con.execute('DELETE FROM schema_migrations WHERE version=10')
            core.con.commit()
            run_migrations(core.con)
            assert core.con.execute('SELECT points_awarded FROM backup_v9_assessment_items').fetchone()[0]==2
        item=core.assessment_repo.get_item_by_order(assessment,1)
        assert item.points_awarded is None and item.score_status=='pending_review'
        assert item.score_history[-1]['previous_points']==2
        assert core.evidence_repo.get_topic_state('a',topic).independent_success_count==0
        assert core.attempt_history('a','alice',attempt['id'])['summary']['needs_review']
        assert core.evidence_repo.get_evidence(evidence['id']).status=='active'
        with pytest.raises(LumenError):
            core.start_assessment_item_attempt(assessment,1,learner_id='alice')
