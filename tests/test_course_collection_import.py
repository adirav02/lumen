"""Collection import preserves originals and excludes all exported learner state."""

import importlib.util
import hashlib
import json
from pathlib import Path

import pytest
from course_tutor.api import LumenCore

spec = importlib.util.spec_from_file_location('collection_import', Path(__file__).parents[1]/'scripts/import_course_collection.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def collection(tmp_path):
    root = tmp_path/'collection'/'sample'
    source = root/'sources/exam.txt'
    source.parent.mkdir(parents=True)
    source.write_text('Question 1: Compute the requested value.\n')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    (root/'course.json').write_text(json.dumps({'course_id':'sample','mock_data':True,'sources':[
        {'source_label':'paper','path':'sources/exam.txt','sha256':digest,'role':'exam'}]}))
    (root/'catalog').mkdir()
    q = {'id':'old-occurrence','exercise_version_id':'old-version','course_id':'sample',
         'source_version_id':'old-source','file_hash':digest,'question_key':'1',
         'question_text':'Question 1: Compute the requested value.',
         'source_spans':[{'section_index':0,'start_offset':0,'end_offset':44}],
         'review_status':'pending_review','visual_review_status':'not_required','metadata':{}}
    q['source_spans'][0]['end_offset'] = len(q['question_text'])
    (root/'catalog/questions.jsonl').write_text(json.dumps(q)+'\n')
    (root/'tracking').mkdir()
    (root/'tracking/mock-results.json').write_text('{"learner_id":"mock-alice","score":100}')
    return root, source


def test_import_and_replay_exclude_mock_history(tmp_path):
    root, source = collection(tmp_path)
    original = source.read_bytes()
    ws = tmp_path/'workspace'
    first = module.import_collection(root.parent, ws)
    assert first['courses'][0]['questions'] == 1
    assert module.import_collection(root.parent, ws) == first
    assert source.read_bytes() == original
    with LumenCore(ws) as core:
        assert [c['id'] for c in core.list_courses()['courses']] == ['sample']
        assert len(core.list_questions('sample')['questions']) == 1
        assert core.propose_practice('sample', source_only=True)['candidates'] == []
        for table in ('attempts','evidence','assessments','learner_settings'):
            assert core.con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0


def test_changed_original_fails_before_creating_workspace(tmp_path):
    root, source = collection(tmp_path)
    source.write_text('Changed original')
    ws = tmp_path/'workspace'
    with pytest.raises(ValueError, match='hash differs'):
        module.import_collection(root.parent, ws)
    assert not ws.exists()
