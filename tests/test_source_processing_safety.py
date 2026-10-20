"""Synthetic failure, publication, concurrency and historical-retention boundaries."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from threading import Barrier
from zipfile import ZipFile

import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import IdempotencyConflictError, SourceCorruptedError
from course_tutor.ingestion import processing
from course_tutor.ingestion.extractors import TextExtractor
from course_tutor.ingestion.pipeline import IngestionPipeline
from course_tutor.questions.catalog import QuestionCatalog


@pytest.fixture
def sample(tmp_path):
    with LumenCore(tmp_path / 'workspace') as core:
        core.create_course('Synthetic', course_id='c')
        path = tmp_path / 'exam.txt'
        path.write_text('Question 1: What is 2 + 2?\nA. 4\nB. 5\n')
        yield core, path


def counts(core):
    return {table: core.con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in ('source_versions', 'source_processing', 'source_sections',
                          'knowledge_units', 'question_occurrences', 'operation_receipts')}


def assert_clean(core):
    assert not list(core.file_store.staging_dir.iterdir())
    assert not core.con.in_transaction
    assert not core.con.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('same_request', [False, True])
def test_two_prepared_misses_commit_one_derived_set(sample, monkeypatch, same_request):
    core, path = sample
    barrier = Barrier(2, timeout=10)
    original = IngestionPipeline.prepare_staged_ingestion

    def both_miss(self, prep, configuration):
        result = original(self, prep, configuration)
        assert prep['sections'] is not None  # Neither connection has committed yet.
        assert not self.con.in_transaction
        barrier.wait()
        return result

    monkeypatch.setattr(IngestionPipeline, 'prepare_staged_ingestion', both_miss)
    requests = ['race', 'race' if same_request else 'race-other']

    def ingest(request):
        with LumenCore(core.workspace_root) as other:
            return other.ingest_source('c', path, role='exam', request_id=request,
                structured_units=[{'kind': 'definition', 'title': 'Sum', 'content': '2 + 2 = 4'}])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ingest, requests))
    monkeypatch.setattr(IngestionPipeline, 'prepare_staged_ingestion', original)
    assert len({r['data']['source_version_id'] for r in results}) == 1
    assert counts(core) == dict(source_versions=1, source_processing=1, source_sections=1,
        knowledge_units=1, question_occurrences=1, operation_receipts=1 if same_request else 2)
    for request in requests:
        retry = ingest(request)
        assert retry['idempotent_replay']
        assert retry['data']['source_version_id'] == results[0]['data']['source_version_id']
    assert_clean(core)


@pytest.mark.parametrize('failure', ['extraction', 'catalog'])
def test_interrupted_processing_rolls_back_and_retry_completes(sample, monkeypatch, failure):
    core, path = sample
    before = counts(core)
    target, name = (TextExtractor, 'extract') if failure == 'extraction' else (QuestionCatalog, 'catalog')
    original = getattr(target, name)

    def interrupted(self, *args, **kwargs):
        if failure == 'catalog':
            original(self, *args, **kwargs)
            assert self.con.execute('SELECT COUNT(*) FROM source_sections').fetchone()[0] == 1
            assert self.con.execute('SELECT COUNT(*) FROM source_processing').fetchone()[0] == 1
            assert self.con.execute('SELECT COUNT(*) FROM question_occurrences').fetchone()[0] == 1
        raise RuntimeError('injected interruption')

    monkeypatch.setattr(target, name, interrupted)
    with pytest.raises(RuntimeError, match='injected interruption'):
        core.ingest_source('c', path, role='exam', request_id='retry')
    assert counts(core) == before
    assert_clean(core)
    monkeypatch.setattr(target, name, original)
    result = core.ingest_source('c', path, role='exam', request_id='retry')
    assert result['data']['sections_extracted'] == 1
    assert counts(core)['source_processing'] == counts(core)['operation_receipts'] == 1
    assert_clean(core)


def test_extraction_uses_staged_bytes_outside_transaction(sample, monkeypatch):
    core, path = sample
    original_bytes = path.read_bytes()
    stage = core.ingestion.stage_ingestion
    extract = TextExtractor.extract

    def stage_then_change(*args, **kwargs):
        prep = stage(*args, **kwargs)
        path.write_text('Question 2: changed after staging')
        return prep

    def inspect(self, staged):
        assert not core.con.in_transaction
        assert staged != path
        assert staged.read_bytes() == original_bytes
        return extract(self, staged)

    monkeypatch.setattr(core.ingestion, 'stage_ingestion', stage_then_change)
    monkeypatch.setattr(TextExtractor, 'extract', inspect)
    data = core.ingest_source('c', path, request_id='staged')['data']
    assert data['file_hash'] == hashlib.sha256(original_bytes).hexdigest()
    assert core.file_store.get_absolute_path(data['storage_relpath']).read_bytes() == original_bytes
    assert '2 + 2' in core.get_extracted_sections(data['source_version_id'])[0]['text']
    assert_clean(core)


def test_corrupted_staging_on_reuse_cannot_commit_receipt(sample, monkeypatch):
    core, path = sample
    core.ingest_source('c', path, request_id='first')
    before = counts(core)
    prepare = core.ingestion.prepare_staged_ingestion

    def corrupt_reuse(prep, config):
        result = prepare(prep, config)
        assert prep['sections'] is None
        prep['staged_path'].write_bytes(b'corrupt')
        return result

    monkeypatch.setattr(core.ingestion, 'prepare_staged_ingestion', corrupt_reuse)
    with pytest.raises(SourceCorruptedError):
        core.ingest_source('c', path, request_id='corrupt-reuse')
    assert counts(core) == before
    assert_clean(core)


def test_receipt_replay_survives_upgrade_but_conflicting_request_fails(sample, monkeypatch):
    core, path = sample
    first = core.ingest_source('c', path, request_id='stable')
    monkeypatch.setattr(processing, 'UNIT_BUILDER_VERSION', 'upgraded')

    def forbidden(*args, **kwargs):
        raise AssertionError('Receipt replay entered extraction')

    monkeypatch.setattr(TextExtractor, 'extract', forbidden)
    replay = core.ingest_source('c', path, request_id='stable')
    assert replay['idempotent_replay']
    assert replay['data'] == first['data']
    path.write_text('changed bytes')
    with pytest.raises(IdempotencyConflictError):
        core.ingest_source('c', path, request_id='stable')
    assert counts(core)['source_versions'] == counts(core)['operation_receipts'] == 1
    assert_clean(core)


@pytest.mark.parametrize('change', ['bytes', 'processor'])
@pytest.mark.parametrize('visual', [False, True])
def test_new_processing_keeps_review_and_learner_history_exact(sample, monkeypatch, change, visual):
    core, path = sample
    if visual:
        # Minimal OOXML fixture exercises the built-in visual gate without a renderer.
        path = path.with_suffix('.docx')
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Question 1: What is 2 + 2?</w:t></w:r></w:p></w:body></w:document>'
        with ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', xml)
    first = core.ingest_source('c', path, role='exam')['data']
    question = core.list_questions('c', first['source_version_id'])['questions'][0]
    version = question['exercise_version_id']
    core.review_question_occurrence('c', question['id'], 1, 'accepted', 'Checked original boundaries')
    if visual:
        core.review_question_visual('c', question['id'], 2, 'verified', 'Compared original render',
            {'source_render_checked': True, 'formulas_options_diagrams_checked': True})
    core.validate_exercise_version(version, expected_revision=1, reference_solution='4',
        rubric={'max_points': 2}, checks={'math': True})
    topic = core.create_topic('c', 'Arithmetic')['id']
    attempt = core.start_attempt('c', version, learner_id='synthetic')['data']
    submission = core.record_attempt_event(attempt['id'], 1, 'work_submission', content='4')['data']['event']
    evidence = core.commit_evidence(attempt['id'], [{'topic_id': topic, 'skill_id': 'sum', 'correct': True}],
        submission_event_id=submission['id'])['data']['evidence_created'][0]
    core.grade_attempt('c', 'synthetic', attempt['id'], 0, 2, 2, 'Correct sum', [evidence['id']])
    old_question = core.list_questions('c', first['source_version_id'])['questions'][0]
    old_history = core.attempt_history('c', 'synthetic', attempt['id'])
    old_provenance = core.get_extracted_sections(first['source_version_id'])
    if change == 'bytes':
        if visual:
            with ZipFile(path, 'w') as archive:
                archive.writestr('word/document.xml', xml.replace('2 + 2?', '2 + 3?'))
        else:
            path.write_text(path.read_text() + '\nAdditional source text')
    else:
        monkeypatch.setattr(processing, 'CATALOG_VERSION', 'upgraded')
    new = core.ingest_source('c', path, role='exam')['data']
    fresh = core.list_questions('c', new['source_version_id'])['questions'][0]
    assert new['source_version_id'] != first['source_version_id']
    assert fresh['id'] != question['id']
    assert fresh['exercise_version_id'] != version
    assert fresh['review_status'] == fresh['validation_state'] == 'pending_review'
    assert fresh['visual_review_status'] == ('pending_review' if visual else 'not_required')
    assert core.list_questions('c', first['source_version_id'])['questions'][0] == old_question
    assert core.attempt_history('c', 'synthetic', attempt['id']) == old_history
    assert core.get_extracted_sections(first['source_version_id']) == old_provenance
    original = core.file_store.get_absolute_path(first['storage_relpath'])
    assert hashlib.sha256(original.read_bytes()).hexdigest() == first['file_hash']
    assert_clean(core)
