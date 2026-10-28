"""Source-bound offline PNGs: identity, review gates, privacy and immutable export."""
import base64
import hashlib
import json
from pathlib import Path
import struct
import zlib

import pytest
from course_tutor.api import LumenCore
from course_tutor.errors import ValidationError
from course_tutor.assessment.export import render_paper_html
from course_tutor.questions.assets import student_assets


def png():
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00\x00\xff\x00'))+chunk(b'IEND',b'')


def setup(c,tmp_path):
    c.create_course('C',course_id='c')
    path=tmp_path/'figure.png';path.write_bytes(png())
    sid=c.ingest_source('c',path,catalog_questions=False)['data']['source_version_id']
    text=tmp_path/'paper.txt';text.write_text('Question 1: Compare the two colored regions in the figure.')
    paper=c.ingest_source('c',text,role='exam')['data']['source_version_id'];q=c.list_questions('c',paper)['questions'][0]
    c.review_question_occurrence('c',q['id'],1,'accepted','Synthetic source fixture.')
    asset={'source_version_id':sid,'alt':'Two color regions','caption':'Source figure', 'review_notes':'PRIVATE ASSET REVIEW'}
    return q['exercise_version_id'],sid,asset


def validate(c,vid,asset,checks=None):
    return c.validate_exercise_version(vid,expected_revision=1,reference_solution='PRIVATE ANSWER',
        rubric={'max_points':10,'student_assets':[asset]},checks=checks or {'math_review':True,'visual_assets_reviewed':True})


def test_visual_review_required_and_source_identity_bound(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        vid,sid,asset=setup(c,tmp_path)
        with pytest.raises(ValidationError,match='visual_assets_reviewed'):
            validate(c,vid,asset,{'math_review':True})
        v=validate(c,vid,asset)
        binding=v['rubric']['student_assets'][0]
        assert binding['source_version_id']==sid and binding['sha256']==hashlib.sha256(png()).hexdigest()
        assert binding['region']=='whole_image'
        preview=c.student_preview('c',vid)
        assert preview['student_assets'][0]['data_base64']==base64.b64encode(png()).decode()
        assert 'PRIVATE' not in json.dumps(preview) and str(tmp_path) not in json.dumps(preview)


@pytest.mark.parametrize('changed',[False,True])
def test_missing_or_changed_original_blocks_new_paper_but_snapshot_reexports(tmp_path,changed):
    with LumenCore(tmp_path/'w') as c:
        vid,sid,asset=setup(c,tmp_path);validate(c,vid,asset)
        result=c.assemble_exam('c','simulation',{'slots':[{'id':'one','count':1}]},42,'asset-assembly')['data']
        before=c.assessment_paper(result['assessment_id'])
        html=render_paper_html(before)
        assert 'data:image/png;base64,' in html and 'img-src data:' in html
        assert 'PRIVATE' not in html and str(tmp_path) not in html
        original=Path(c.read_source_region(sid)['absolute_path'])
        if changed:original.write_bytes(b'corrupted source')
        else:original.unlink()
        with pytest.raises(ValidationError,match='diagram.*(missing|hash changed)'):
            c.student_preview('c',vid)
        # Use a second learner to avoid the original reservation being the blocker.
        with pytest.raises(ValidationError,match='diagram.*(missing|hash changed)'):
            c.assemble_exam('c','other',{'slots':[{'id':'one','count':1}]},19,'new-assets')
        assert c.assessment_paper(result['assessment_id'])==before
        export=c.export_assessment(result['assessment_id'],output_directory=tmp_path/'reexport')
        assert Path(export['html_path']).read_text()==html
        assert Path(export['pdf_path']).is_file()


@pytest.mark.parametrize('bad',[{'path':'/private/file.png'},{'url':'https://example.com/image.png'},{'sha256':'wrong'}])
def test_arbitrary_paths_urls_and_false_hashes_rejected(tmp_path,bad):
    with LumenCore(tmp_path/'w') as c:
        vid,sid,asset=setup(c,tmp_path)
        with pytest.raises(ValidationError):validate(c,vid,{**asset,**bad})


def test_cross_course_asset_and_tampered_snapshot_rejected(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        vid,sid,asset=setup(c,tmp_path)
        c.create_course('Other',course_id='other')
        v=c.create_exercise('other','figure','Question with figure')['exercise_version_id']
        with pytest.raises(ValidationError,match='in this course'):validate(c,v,asset)
        validate(c,vid,asset)
        projected=c.student_preview('c',vid)['student_assets']
        projected[0]['sha256']='incorrect'
        with pytest.raises(ValidationError,match='snapshot hash changed'):student_assets(projected)


def test_asset_edit_revokes_validation_and_requires_fresh_visual_attestation(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        vid,sid,asset=setup(c,tmp_path);v=validate(c,vid,asset)
        rubric=v['rubric'];rubric['student_assets'][0]['caption']='New reviewed caption.'
        changed=c.update_exercise_version(vid,rubric=rubric,expected_revision=1)
        assert changed['validation_state']=='pending_review'
        with pytest.raises(ValidationError):c.student_preview('c',vid)
        with pytest.raises(ValidationError,match='visual_assets_reviewed'):
            c.validate_exercise_version(vid,expected_revision=2,checks={'math_review':True})
        c.validate_exercise_version(vid,expected_revision=2,checks={'math_review':True,'visual_assets_reviewed':True})
        assert c.student_preview('c',vid)['student_assets'][0]['caption']=='New reviewed caption.'


def test_invalid_png_cannot_enter_student_projection(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        vid,sid,asset=setup(c,tmp_path)
        # A falsely named source is not safe merely because its MIME says PNG.
        bad=tmp_path/'bad.png';bad.write_bytes(b'<svg onload="alert(1)"></svg>')
        sid=c.ingest_source('c',bad,catalog_questions=False)['data']['source_version_id']
        validate(c,vid,{**asset,'source_version_id':sid})
        with pytest.raises(ValidationError,match='require a PNG'):c.student_preview('c',vid)


def test_rtl_math_with_offline_asset_has_isolated_english_metadata(tmp_path):
    with LumenCore(tmp_path/'w') as c:
        vid,sid,asset=setup(c,tmp_path);validate(c,vid,asset)
        q=c.student_preview('c',vid)
        q.update(item_order=1,max_points=10,question_text=r'חשבו את גודל המומנט בעזרת הנוסחה \(\tau=F\times d\). הסבירו את בחירת המרחק מהציר וכתבו יחידות מתאימות.')
        html=render_paper_html({'assessment_id':'rtl','course_id':'c','title':'Synthetic RTL check','questions':[q]})
        assert 'dir="rtl"' in html and '<math' in html and '<bdi dir="ltr">10 points</bdi>' in html
        assert 'unicode-bidi:isolate' in html and 'class="with-assets"' in html
        assert 'PRIVATE' not in html and str(tmp_path) not in html
