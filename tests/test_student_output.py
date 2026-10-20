"""Private-answer canaries cannot cross any supported student content surface."""
import json
import subprocess
import sys
import pytest
from course_tutor.api import LumenCore
from course_tutor.assessment.export import render_paper_html
from course_tutor.errors import ValidationError

CANARY='PRIVATE_ANSWER_CANARY_761'


def test_canary_preview_search_paper_html_and_real_pdf(tmp_path):
    from pypdf import PdfReader
    from course_tutor.assessment.export import browser_executable
    with LumenCore(tmp_path/'ws') as c:
        c.create_course('SYNTHETIC',course_id='s')
        source=tmp_path/'mixed.txt'
        source.write_text('Question 1: Compute the synthetic sum.\nInstructor answer: '+CANARY)
        sid=c.ingest_source('s',source,role='solutions_with_statements',catalog_questions=False)['data']['source_version_id']
        q=c.catalog_exam_questions('s',sid,questions=[{'question_key':'1','question_text':'Compute the synthetic sum.',
            'subparts':[{'key':'a','private_answer':CANARY}], 'source_spans':[{'section_index':0,'start_offset':12,'end_offset':38}]}])['data']
        q=c.list_questions('s',sid)['questions'][0]
        # A source candidate must pass actual extraction acceptance before release.
        with pytest.raises(ValidationError):
            c.student_preview('s',q['exercise_version_id'])
        c.review_question_occurrence('s',q['id'],q['revision'],'accepted','Compared selected stem only')
        c.validate_exercise_version(q['exercise_version_id'],expected_revision=1,checks={'review':True},
            reference_solution=CANARY,rubric={'answer':CANARY})
        c.annotate_question('s',q['id'],q['revision']+1,{'private_answer':CANARY})
        vid=q['exercise_version_id']
        aid=c.create_assessment('s','SYNTHETIC',{},[vid])['data']['assessment_id']
        outputs=[c.student_preview('s',vid),c.student_search('s','synthetic'),c.assessment_paper(aid,'s')]
        assert CANARY not in json.dumps(outputs)
        assert not c.student_search('s',CANARY)['questions']
        html=render_paper_html(c.assessment_paper(aid,'s'))
        assert CANARY not in html and 'Compute the synthetic sum.' in html
        if browser_executable():
            pdf=c.export_assessment(aid,'s')
            assert CANARY not in ''.join(page.extract_text() for page in PdfReader(pdf['pdf_path']).pages)
            assert CANARY not in open(pdf['html_path']).read()
        else:
            pytest.skip('Real browser unavailable; preview/HTML/search verified, PDF check blocked')
        for op in ['search','read-source-region','get-extracted-sections','list-questions','read-units']:
            p=subprocess.run([sys.executable,'-m','course_tutor.cli',op,'--audience','student','-w',str(c.workspace_root),'-j','{}'],capture_output=True,text=True)
            assert p.returncode==1 and json.loads(p.stdout)['error_code']=='TUTOR_ONLY'
