"""HN101 source regressions use isolated workspaces; course originals stay untouched."""
import hashlib
import json
from pathlib import Path
import re

import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import ValidationError
from course_tutor.assessment.assembly import prepare_exam
from course_tutor.assessment.export import render_paper_html

ROOT = Path(__file__).parents[1]
HN = ROOT / 'examples/HN101_Complete_Course'


@pytest.fixture
def hn(tmp_path):
    with LumenCore(tmp_path/'workspace') as core:
        core.create_course('HN101', course_id='hn')
        yield core


def final_bank(core, code='03', headings=False):
    suffix = 'pdf' if int(code) <= 3 else 'docx'
    path = HN/'Final_examinations'/f'HN-FE{code}_student.{suffix}'
    sid = core.ingest_source('hn', path, role='exam', catalog_questions=not headings)['data']['source_version_id']
    if headings:
        candidates = []
        for section in core.get_extracted_sections(sid):
            matches = list(re.finditer(r'(?m)^Question\s+(\d+)\b', section['text']))
            for i, match in enumerate(matches):
                end = matches[i+1].start() if i+1 < len(matches) else len(section['text'])
                candidates.append({'question_key': match[1], 'question_text': section['text'][match.start():end].strip(),
                    'source_spans': [{'section_index': section['section_index'], 'start_offset': match.start(), 'end_offset': end}]})
        core.catalog_exam_questions('hn', sid, questions=candidates)
    qs = core.list_questions('hn', sid, limit=100)['questions']
    assert len(qs) == 8
    for q in qs:
        core.review_question_occurrence('hn', q['id'], q['revision'], 'accepted', 'Regression fixture source transcription')
        current = next(x for x in core.list_questions('hn', sid, limit=100)['questions'] if x['id'] == q['id'])
        core.review_question_visual('hn', q['id'], current['revision'], 'verified', 'Regression fixture setup',
            checks={'source_render_checked': True, 'formulas_options_diagrams_checked': True})
        core.validate_exercise_version(q['exercise_version_id'], expected_revision=1,
            reference_solution='Regression fixture reference', rubric={'max_points': 10 if int(q['question_key']) < 5 else 15},
            checks={'fixture': True})
    return sid, {q['question_key']: q['exercise_version_id'] for q in qs}


def test_hn_numbering_instructions_duration_points_and_fields(hn):
    _, qs = final_bank(hn, headings=True)
    instructions = ['Answer all eight questions.', 'Calculator permitted.', 'Carry full precision until display.',
                    'Use extra paper as needed; label each answer by question and part.']
    bp = {'duration_minutes': 120, 'instructions': instructions}
    selected = [qs[k] for k in ('4','3','2','1','6','8','7','5')]
    aid = hn.create_assessment('hn', 'HN101 regression', bp, selected)['data']['assessment_id']
    paper = hn.assessment_paper(aid)
    assert paper['duration_minutes'] == 120 and paper['instructions'] == instructions
    assert all(re.match(r'Question \d', q['question_text']) for q in paper['questions'])
    assert [q['source_reference']['question_key'] for q in paper['questions']] == ['4','3','2','1','6','8','7','5']
    html = render_paper_html(paper)
    for text in (*instructions, '120 minutes', '100 total points', 'Name ___', 'Date ___', 'counter(page)', 'counter(pages)'):
        assert text in html
    assert 'Question 4 Acute' not in html
    assert len(re.findall(r'<h2>Question \d+', html)) == 8
    # Printed citations identify the source/version/pages without its question
    # numbers; the saved paper above retains the exact private mapping.
    assert 'HN-FE03_student.pdf | v1 | Page' in html
    assert not re.search(r'HN-FE03_student\.pdf \| v1 \| \d+ \|', html)
    # Immutable originals and saved source question text retain their headings.
    assert hn.student_preview('hn', qs['4'])['question_text'].startswith('Question 4 Acute')


def test_hn_seed_warning_and_distinct_exams(hn):
    sid, _ = final_bank(hn)
    bp = {'slots': [{'id': 'all', 'count': 8, 'source_version_ids': [sid]}]}
    report = hn.blueprint_readiness('hn', bp)
    assert report['analysis']['distinct_exams']['count'] == 1
    # Eight eligible questions all needed: report deterministic selection as well.
    single = {'slots': [{'id': 'one', 'count': 1, 'source_version_ids': [sid], 'section': 'rare'}]}
    q = hn.list_questions('hn', sid)['questions'][0]
    hn.annotate_question('hn', q['id'], q['revision'], {'section': 'rare'})
    report = hn.blueprint_readiness('hn', single)
    assert report['warnings'][0]['eligible_questions'] == 1
    assert 'seed has little or no effect' in report['warnings'][0]['message']
    assert report['analysis']['distinct_exams']['count'] == 1


@pytest.mark.parametrize('code,dependent,prerequisite,discloser,target', [
    ('01','2','1','8','3'), ('04','2','1','8','1'), ('05','2','1','8','2')])
def test_hn_known_dependencies_and_disclosures(hn, code, dependent, prerequisite, discloser, target):
    sid, qs = final_bank(hn, code)
    with pytest.raises(ValidationError, match='prerequisites'):
        hn.create_assessment('hn', 'Missing prerequisite', {}, [qs[dependent]])
    with pytest.raises(ValidationError, match='disclosures'):
        hn.create_assessment('hn', 'Answer leak', {}, list(dict.fromkeys([qs[prerequisite], qs[target], qs[discloser]])))
    bp = {'slots': [{'id': 'all', 'count': 8, 'source_version_ids': [sid]}]}
    report = hn.blueprint_readiness('hn', bp)
    assert report['analysis']['joint']['status'] == 'infeasible'
    assert report['analysis']['distinct_exams']['count'] == 0
    assert any(w['reason'] == 'answer_disclosure' for w in report['warnings'])
    with pytest.raises(ValidationError, match='allocation'):
        prepare_exam(hn.con, 'hn', 'new-student', bp, 19)
    receipt = hn.apply_known_question_constraints('hn', request_id='mark-known')
    assert hn.apply_known_question_constraints('hn', request_id='mark-known')['idempotent_replay']
    assert receipt['data']['count'] == 0  # Already applied in the catalog transaction.


def test_hn_dependency_order_in_seeded_saved_snapshot(hn):
    sid, qs = final_bank(hn, '01')
    for q in hn.list_questions('hn', sid)['questions']:
        if q['question_key'] in ('1', '2'):
            hn.annotate_question('hn', q['id'], q['revision'], {'section': 'pair'})
    bp = {'instructions': ['Calculator permitted.'], 'duration_minutes': 120,
          'slots': [{'id': 'pair', 'count': 2, 'section': 'pair'}]}
    for seed in range(5):
        prepared = prepare_exam(hn.con, 'hn', 'student', bp, seed)
        assert [i['exercise_version_id'] for i in prepared['items']] == [qs['1'], qs['2']]
        assert 'Calculator permitted.' in prepared['effective_blueprint']['instructions']
        assert prepared['effective_blueprint']['duration_minutes'] == 120
        assert prepared['items'][1]['snapshot']['question_constraints']['depends_on'][0]['part'] == 'a'


def test_csv_original_bytes_and_both_hashes(hn, tmp_path):
    files = sorted(HN.rglob('*.csv'))
    assert len(files) == 15
    for i, original in enumerate(files):
        original_bytes = original.read_bytes()
        source = tmp_path/f'{i}.csv'
        raw = original_bytes.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        source.write_bytes(raw)
        result = hn.ingest_source('hn', source, catalog_questions=False, request_id=f'csv-{i}')
        sid = result['data']['source_version_id']
        row = hn.con.execute('SELECT storage_relpath,file_hash FROM source_versions WHERE id=?', (sid,)).fetchone()
        assert hn.file_store.get_absolute_path(row['storage_relpath']).read_bytes() == raw
        assert row['file_hash'] == hashlib.sha256(raw).hexdigest()
        for section in hn.get_extracted_sections(sid):
            metadata = section['metadata']
            assert metadata['original_sha256'] == row['file_hash']
            assert metadata['extracted_text_sha256'] == hashlib.sha256(section['text'].encode()).hexdigest()
            assert '\r' not in section['text']
        assert original.read_bytes() == original_bytes
        assert hn.ingest_source('hn', source, catalog_questions=False, request_id=f'csv-{i}')['idempotent_replay']

