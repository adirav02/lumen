"""Storage contracts for immutable exam assembly and publication jobs."""

import sqlite3

import pytest

from course_tutor.api import CourseTutor
from course_tutor.errors import IdempotencyConflictError, ValidationError
from course_tutor.storage import migrations
from course_tutor.storage.db import atomic_transaction, get_connection
from course_tutor.storage.repositories import AssemblyRepository, AssessmentRepository


@pytest.fixture
def assembly_storage(tmp_path):
    with CourseTutor(tmp_path / 'workspace') as core:
        core.create_course('Algorithms', course_id='alg')
        version = core.create_exercise('alg', 'family', 'Saved wording',
                                      reference_solution='PRIVATE')['exercise_version_id']
        repo = AssemblyRepository(core.con)
        item = dict(item_id='item-one', exercise_version_id=version, item_order=1,
                    slot_id='slot', max_points=7.5, exercise_revision=1,
                    exercise_content_hash='saved-hash', snapshot={
                        'question_text': 'Saved wording', 'rubric': {'answer': 'PRIVATE'},
                        'reference_solution': 'PRIVATE', 'option_permutation': [0, 1],
                        'answer_mapping': {'A': 'PRIVATE'}, 'provenance': {'page': 1},
                        'review_identity': {'revision': 1}})
        args = dict(request_id='request', input_hash='hash', assessment_id='exam',
                    course_id='alg', learner_id='alice', owner_token='owner',
                    staging_path='/stage', final_path='/final',
                    generation={'blueprint': {'slots': []}, 'seed': 42,
                                'title': 'Saved exam', 'weights': {'private': 2}}, items=[item])
        yield core, repo, args


def test_assembly_storage_upgrade_v10_and_repeat(monkeypatch):
    con = get_connection(':memory:')
    try:
        original = migrations.MIGRATIONS
        with monkeypatch.context() as patch:
            patch.setattr(migrations, 'MIGRATIONS', original[:10])
            migrations.run_migrations(con)
        assert con.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 10
        migrations.run_migrations(con)
        migrations.run_migrations(con)
        assert con.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 13
        assert con.execute('SELECT COUNT(*) FROM assembly_jobs').fetchone()[0] == 0
    finally:
        con.close()


def test_assembly_storage_snapshot_finalize_roundtrip(assembly_storage):
    core, repo, args = assembly_storage
    with pytest.raises(ValidationError):
        repo.create(**args)
    with atomic_transaction(core.con):
        repo.create(**args)
    assert repo.get('request')['generation'] == args['generation']
    assert repo.items('request')[0]['snapshot'] == args['items'][0]['snapshot']
    core.con.execute("UPDATE exercise_versions SET question_text='Changed',reference_solution='Changed'")
    assert repo.items('request')[0]['snapshot']['question_text'] == 'Saved wording'
    receipt = {'assessment_id': 'exam', 'pdf_path': '/final/student.pdf',
               'summary': '1 question; pending visual review'}
    with atomic_transaction(core.con):
        assert repo.finalize('request', 'owner', receipt) == receipt
        assert repo.finalize('request', 'owner', receipt) == receipt
    saved = AssessmentRepository(core.con).get_items('exam')
    assert [(i.id, i.item_order, i.max_points) for i in saved] == [('item-one', 1, 7.5)]
    assert repo.get('request')['state'] == 'published'
    assert not repo.reservations('alg')
    assert core.con.execute('SELECT COUNT(*) FROM operation_receipts').fetchone()[0] == 1
    assert core.con.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 0


def test_assembly_storage_conflict_fail_release_claim(assembly_storage):
    core, repo, args = assembly_storage
    with atomic_transaction(core.con):
        repo.create(**args)
        repo.create(**args)
    before = repo.items('request')
    assert len(repo.reservations('alg')) == 1
    with pytest.raises(IdempotencyConflictError), atomic_transaction(core.con):
        repo.create(**dict(args, input_hash='changed'))
    with pytest.raises(ValidationError), atomic_transaction(core.con):
        repo.fail('request', 'other-owner')
    with atomic_transaction(core.con):
        repo.fail('request', 'owner', 'PRIVATE exception detail')
    assert repo.get('request')['failure_code'] == 'publication_failed'
    assert not repo.reservations('alg')
    assert repo.items('request') == before
    with atomic_transaction(core.con):
        repo.claim('request', 'hash', 'owner', 'new-owner')
    with pytest.raises(ValidationError), atomic_transaction(core.con):
        repo.claim('request', 'hash', 'owner', 'stale-owner')
    assert len(repo.reservations('alg')) == 1


@pytest.mark.parametrize('change', [{'max_points': 0}, {'exercise_revision': 0},
                                   {'exercise_content_hash': ''}, {'item_order': 0}])
def test_assembly_storage_constraints(assembly_storage, change):
    core, repo, args = assembly_storage
    item = dict(args['items'][0], **change)
    with pytest.raises((sqlite3.IntegrityError, ValidationError)), atomic_transaction(core.con):
        repo.create(**dict(args, items=[item]))
    assert repo.get('request') is None


def test_assembly_storage_finalize_rollback(assembly_storage):
    core, repo, args = assembly_storage
    with atomic_transaction(core.con):
        repo.create(**args)
    with pytest.raises(RuntimeError), atomic_transaction(core.con):
        repo.finalize('request', 'owner', {'assessment_id': 'exam',
            'pdf_path': '/final/student.pdf', 'summary': 'pending visual review'})
        raise RuntimeError('simulated commit failure')
    assert repo.get('request')['state'] == 'pending'
    assert AssessmentRepository(core.con).get_assessment('exam') is None
    assert len(repo.reservations('alg')) == 1
    assert core.con.execute('SELECT COUNT(*) FROM operation_receipts').fetchone()[0] == 0

# Read-only preparation contracts; lifecycle/render tests are added by their owners.
from course_tutor.assessment.assembly import prepare_exam
from course_tutor.assessment import readiness
from test_blueprint_readiness import question, edge


@pytest.fixture
def selection_core(tmp_path):
    with CourseTutor(tmp_path / 'workspace') as core:
        core.create_course('Algorithms', course_id='alg')
        yield core


def selected(result):
    return [i['exercise_version_id'] for i in result['items']]


def test_prepare_hard_slots_seed_and_no_mutation(selection_core):
    core = selection_core
    ta = core.create_topic('alg', 'A')['id']
    tb = core.create_topic('alg', 'B')['id']
    aa = {question(core, 'a' + str(i), [ta]) for i in range(5)}
    bb = {question(core, 'b' + str(i), [tb]) for i in range(4)}
    blueprint = {'duration_minutes': 90, 'relaxations': [], 'shuffle_options': False,
                 'slots': [{'id': 'z', 'count': 2, 'topic_ids': [ta], 'max_points': 7.5},
                           {'id': 'a', 'count': 1, 'topic_ids': [tb], 'max_points': 3}]}
    before = core.con.total_changes
    paths = set(core.workspace_root.rglob('*'))
    first = prepare_exam(core.con, 'alg', 'alice', blueprint, 42)
    again = prepare_exam(core.con, 'alg', 'alice', blueprint, 42)
    assert selected(first) == selected(again)
    assert first['selection_inputs'] == again['selection_inputs']
    assert set(selected(first)[:2]) <= aa and set(selected(first)[2:]) <= bb
    assert [i['slot_id'] for i in first['items']] == ['z', 'z', 'a']
    assert [i['max_points'] for i in first['items']] == [7.5, 7.5, 3]
    assert len({tuple(selected(prepare_exam(core.con, 'alg', 'alice', blueprint, seed))) for seed in range(10)}) > 1
    assert core.con.total_changes == before
    assert set(core.workspace_root.rglob('*')) == paths
    assert not core.con.in_transaction
    core.con.execute('BEGIN')
    prepare_exam(core.con, 'alg', 'alice', blueprint, 42)
    assert core.con.in_transaction
    core.con.rollback()
    assert 'Secret' not in __import__('json').dumps(first['readiness'])
    assert first['items'][0]['snapshot']['reference_solution'] == 'Secret solution'


def test_prepare_conflicts_and_any_topic(selection_core):
    core = selection_core
    ta = core.create_topic('alg', 'A')['id']
    tb = core.create_topic('alg', 'B')['id']
    a = question(core, 'a', [ta], family='shared')
    b = question(core, 'b', [tb], family='shared')
    c = question(core, 'c', [ta])
    bp = {'slots': [{'id': 'x', 'count': 1, 'topic_ids': [ta, tb]},
                    {'id': 'y', 'count': 1, 'topic_ids': [tb]}]}
    for seed in range(8):
        result = prepare_exam(core.con, 'alg', 'alice', bp, seed)
        assert set(selected(result)) == {b, c}
    edge(core, b, c)
    before = core.con.total_changes
    paths = set(core.workspace_root.rglob('*'))
    with pytest.raises(ValidationError) as err:
        prepare_exam(core.con, 'alg', 'alice', bp, 42)
    gap = err.value.details['gaps'][0]
    assert set(gap) >= {'slot_id', 'section', 'topic_ids', 'question_type', 'needed', 'eligible', 'shortfall', 'exclusion_reasons'}
    assert 'Secret' not in str(err.value.to_dict())
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths
    assert core.con.execute('SELECT COUNT(*) FROM assembly_jobs').fetchone()[0] == 0


@pytest.mark.parametrize('extra', [{'max_points': True}, {'max_points': 0}, {'max_points': float('nan')},
                                  {'max_points': float('inf')}, {'year_min': True}, {'year_max': 0},
                                  {'year_min': 2025, 'year_max': 2024}, {'difficulty': []},
                                  {'source_version_ids': []}, {'source_version_ids': ['absent']},
                                  {'derived_from': 'unreviewed'}])
def test_prepare_strict_slot_schema(selection_core, extra):
    core = selection_core
    with pytest.raises(ValidationError):
        prepare_exam(core.con, 'alg', 'alice', {'slots': [dict(id='s', count=1, **extra)]}, 1)


@pytest.mark.parametrize('extra', [{'relaxations': ['repeat']}, {'relaxations': {}}, {'shuffle_options': True},
                                  {'shuffle_options': 0}, {'duration_minutes': False}, {'duration_minutes': float('inf')},
                                  {'derived_structure': {}}, {'unknown': 1}])
def test_prepare_reject_policies_before_writes(selection_core, extra):
    core = selection_core
    before = core.con.total_changes
    with pytest.raises(ValidationError):
        prepare_exam(core.con, 'alg', 'alice', dict(slots=[{'id': 's', 'count': 1}], **extra), 1)
    assert core.con.total_changes == before


@pytest.mark.parametrize('seed', [True, 1., None, '42'])
def test_prepare_strict_seed(selection_core, seed):
    with pytest.raises(ValidationError):
        prepare_exam(selection_core.con, 'alg', 'alice', {'slots': [{'id': 's', 'count': 1}]}, seed)


def test_prepare_verified_source_year_difficulty_and_type(selection_core, tmp_path):
    import json
    core = selection_core
    path = tmp_path / 'exam.txt'
    path.write_text('\n'.join(f'Question {i}: Unique item {i}.' for i in range(1, 6)))
    source = core.ingest_source('alg', path, role='exam')['data']['source_version_id']
    qs = core.list_questions('alg', source)['questions']
    for i, q in enumerate(qs):
        core.con.execute("UPDATE exercise_versions SET validation_state='validated' WHERE id=?", (q['exercise_version_id'],))
        metadata = {'section': 'A', 'question_type': 'proof', 'year': 2024, 'difficulty': 'hard'}
        if i == 1:
            metadata.pop('year')
        if i == 2:
            metadata['year'] = True
        if i == 3:
            metadata.pop('difficulty')
        core.con.execute("UPDATE question_occurrences SET metadata_json=?,review_status='accepted',visual_review_status=? WHERE id=?",
                         (json.dumps(metadata), 'pending_review' if i == 4 else 'verified', q['id']))
    question(core, 'no source')
    slot = dict(id='s', count=1, section='A', question_type='proof', source_version_ids=[source],
                year_min=2023, year_max=2025, difficulty='hard', max_points=10)
    result = prepare_exam(core.con, 'alg', 'alice', {'slots': [slot]}, 1)
    assert selected(result) == [qs[0]['exercise_version_id']]
    assert result['items'][0]['snapshot']['section'] == 'A'
    assert result['items'][0]['snapshot']['question_type'] == 'proof'
    assert result['items'][0]['snapshot']['source_reference']['source_version_id'] == source
    assert result['readiness']['slots'][0]['unknown_required_metadata']['year']['count'] == 3
    with pytest.raises(ValidationError):
        prepare_exam(core.con, 'alg', 'alice', {'slots': [dict(slot, count=2)]}, 1)


def test_prepare_unknown_budget_safely_rejects(selection_core, monkeypatch):
    core = selection_core
    ids = [question(core, str(i)) for i in range(3)]
    for a, b in __import__('itertools').combinations(ids, 2):
        edge(core, a, b)
    monkeypatch.setattr(readiness, 'SEARCH_NODE_BUDGET', 0)
    before = core.con.total_changes
    with pytest.raises(ValidationError) as err:
        prepare_exam(core.con, 'alg', 'alice', {'slots': [{'id': 's', 'count': 2}]}, 1)
    assert err.value.details['gaps'][0]['joint_reason'] == 'search_budget_exhausted'
    assert core.con.total_changes == before


def test_prepare_adaptive_weights_are_learner_scoped_and_observations_neutral(selection_core):
    core = selection_core
    topic = core.create_topic('alg', 'Trees', slug='trees')['id']
    other = core.create_topic('alg', 'Unknown')['id']
    past = question(core, 'past', [topic])
    weak = question(core, 'weak', [topic])
    neutral = question(core, 'neutral', [other])
    blueprint = {'slots': [{'id': 's', 'count': 1}]}
    attempt = core.start_attempt('alg', past, learner_id='alice')['data']
    initial = prepare_exam(core.con, 'alg', 'alice', blueprint, 1)
    assert initial['selection_inputs']['weights'][weak]['weight'] == 1
    submission = core.record_attempt_event(attempt['id'], 1, 'work_submission', content='Observed incorrect work')
    core.commit_evidence(attempt['id'], [{'topic_id': topic, 'skill_id': 'count', 'correct': False,
                                         'rationale': 'Wrong counting argument'}],
                         submission_event_id=submission['data']['event']['id'])
    result = prepare_exam(core.con, 'alg', 'alice', blueprint, 1)
    weights = result['selection_inputs']['weights']
    assert weights[weak]['weight'] == 2.5 and weights[neutral]['weight'] == 1
    assert weights[weak]['evidence_ids']
    bob = prepare_exam(core.con, 'alg', 'bob', blueprint, 1)
    assert bob['selection_inputs']['weights'][weak]['weight'] == 1
    assert not bob['selection_inputs']['weights'][weak]['evidence_ids']
    # Across fixed seeds, the race gives weak-topic candidates the expected preference.
    counts = sum(selected(prepare_exam(core.con, 'alg', 'alice', blueprint, seed)) == [weak] for seed in range(40))
    assert counts > 23
    core.con.execute("UPDATE evidence SET demonstrated_level='unassessed'")
    assert prepare_exam(core.con, 'alg', 'alice', blueprint, 1)['selection_inputs']['weights'][weak]['weight'] == 1
    core.con.execute("UPDATE evidence SET demonstrated_level='incorrect',exercise_content_hash='obsolete'")
    assert prepare_exam(core.con, 'alg', 'alice', blueprint, 1)['selection_inputs']['weights'][weak]['weight'] == 1


def test_prepare_pending_reservations_require_lock_liveness(assembly_storage):
    core, repo, args = assembly_storage
    core.validate_exercise_version(args['items'][0]['exercise_version_id'], expected_revision=1, checks={'review': True}, rubric={'points': 1})
    with atomic_transaction(core.con):
        repo.create(**args)
    bp = {'slots': [{'id': 's', 'count': 1}]}
    with pytest.raises(ValidationError):
        prepare_exam(core.con, 'alg', 'alice', bp, 1, live_request_ids={'request'})
    assert selected(prepare_exam(core.con, 'alg', 'alice', bp, 1, live_request_ids=set()))
    assert selected(prepare_exam(core.con, 'alg', 'alice', bp, 1,
                                 live_request_ids={'request'}, exclude_request_id='request'))
    assert repo.get('request')['state'] == 'pending'


def test_prepare_seed_search_budget_and_section_order(selection_core, tmp_path, monkeypatch):
    import json
    core = selection_core
    source_path = tmp_path / 'sections.txt'
    source_path.write_text('\n'.join(f'Question {i}: Unique item {i}.' for i in range(1, 4)))
    source = core.ingest_source('alg', source_path, role='exam')['data']['source_version_id']
    qs = core.list_questions('alg', source)['questions']
    for q, section, kind in zip(qs, ['A', 'B', 'A'], ['proof', 'short', 'short']):
        core.con.execute("UPDATE exercise_versions SET validation_state='validated' WHERE id=?", (q['exercise_version_id'],))
        core.con.execute("UPDATE question_fingerprints SET exact_hash=?,structure_hash=? WHERE exercise_version_id=?", (q['id'], q['id'], q['exercise_version_id']))
        core.con.execute("UPDATE question_occurrences SET review_status='accepted',visual_review_status='verified',metadata_json=? WHERE id=?",
                         (json.dumps({'section': section, 'question_type': kind}), q['id']))
    bp = {'slots': [{'id': 'ap', 'count': 1, 'section': 'A', 'question_type': 'proof'},
                    {'id': 'bs', 'count': 1, 'section': 'B', 'question_type': 'short'},
                    {'id': 'as', 'count': 1, 'section': 'A', 'question_type': 'short'}]}
    result = prepare_exam(core.con, 'alg', 'alice', bp, 3)
    assert [i['slot_id'] for i in result['items']] == ['ap', 'as', 'bs']
    assert selected(result) == [qs[i]['exercise_version_id'] for i in [0, 2, 1]]
    monkeypatch.setattr(readiness, 'SEARCH_NODE_BUDGET', 0)
    with pytest.raises(ValidationError) as error:
        prepare_exam(core.con, 'alg', 'alice', bp, 3)
    assert error.value.details['gaps'][0]['joint_reason'] == 'selection_search_budget_exhausted'


def test_assembly_paper_immutable_student_allowlist(assembly_storage):
    import json
    core, repo, args = assembly_storage
    snapshot = args['items'][0]['snapshot']
    snapshot.update(question_text='Saved wording\nA. original first\nB. original second',
        section='Section A', subparts=[{'key': 'a', 'text': 'Explain your reasoning',
                                      'private_answer': 'PRIVATE'}],
        source_reference={'original_filename': 'exam.txt', 'version_num': 1,
            'question_key': 'Q1', 'source_version_id': 'source',
            'source_spans': [{'label': 'page 1', 'private': 'PRIVATE'}],
            'metadata': {'answer': 'PRIVATE'}})
    with atomic_transaction(core.con):
        repo.create(**args)
        repo.finalize('request', 'owner', {'assessment_id': 'exam',
            'pdf_path': '/final/test.pdf', 'summary': '1 question; pending visual review'})
    before = core.assessment_paper('exam')
    core.con.execute("UPDATE exercise_versions SET question_text='changed',reference_solution='PRIVATE changed',validation_state='draft'")
    core.con.execute("UPDATE assessments SET title='Changed live title'")
    changes = core.con.total_changes
    after = core.assessment_paper('exam', 'alg')
    assert before == after
    assert after['questions'][0]['max_points'] == 7.5
    assert after['questions'][0]['question_text'] == snapshot['question_text']
    assert after['questions'][0]['section'] == 'Section A'
    public = json.dumps(after)
    assert 'PRIVATE' not in public and 'saved-hash' not in public
    assert 'answer_mapping' not in public and 'weights' not in public
    assert core.con.total_changes == changes
    from course_tutor.assessment.export import render_paper_html
    html = render_paper_html(after)
    assert 'PRIVATE' not in html and 'saved-hash' not in html
    assert 'original first' in html and 'original second' in html
    assert '7.5 points' in html and 'Section A' in html
    with pytest.raises(ValidationError):
        core.assessment_paper('exam', 'other')


# Publication lifecycle checks use a real readable PDF without requiring a browser
# process at every injected crash window. One separate smoke uses the real renderer.
from pathlib import Path
from course_tutor.assessment import assembly as coordinator
from course_tutor.assessment import export as paper_export
from course_tutor.errors import ConflictError
import json
import os
import shutil


@pytest.fixture
def publish_core(selection_core, monkeypatch):
    core = selection_core
    for n in range(4):
        question(core, 'publication-'+str(n))
    monkeypatch.setattr(paper_export, 'browser_executable', lambda: 'fixture-browser')
    def pdf(html_path, pdf_path, executable):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(str(pdf_path))
    monkeypatch.setattr(paper_export, 'print_pdf', pdf)
    return core


def assemble(core, request='publication', **kw):
    return core.assemble_exam('alg', 'alice', kw.pop('blueprint', {'slots': [{'id': 's', 'count': 1}]}),
                              kw.pop('seed', 42), request, **kw)


def job(core, request='publication'):
    return AssemblyRepository(core.con).get(request)


def test_public_assembly_finalized_compact_and_replay(publish_core, monkeypatch):
    core = publish_core
    render = coordinator.render_staged_paper
    def checked_render(paper, directory):
        assert not core.con.in_transaction
        assert job(core)['state'] == 'pending'
        assert core.con.execute('SELECT COUNT(*) FROM assessments').fetchone()[0] == 0
        return render(paper, directory)
    monkeypatch.setattr(coordinator, 'render_staged_paper', checked_render)
    result = assemble(core)
    assert set(result) == {'status', 'data'}
    assert set(result['data']) == {'assessment_id', 'pdf_path', 'summary'}
    assert 'pending visual review' in result['data']['summary']
    assert Path(result['data']['pdf_path']).stat().st_size > 0
    before = core.con.total_changes
    paths = set(core.workspace_root.rglob('*'))
    assert assemble(core) == result
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths
    assert job(core)['state'] == 'published'
    assert not AssemblyRepository(core.con).reservations('alg')
    assert core.con.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 0
    assert core.con.execute('SELECT COUNT(*) FROM topic_state').fetchone()[0] == 0
    public = ''.join((Path(job(core)['final_path'])/p).read_text() for p in ('test.html', 'presentation.json'))
    assert 'Secret solution' not in public and 'selection_inputs' not in public
    with pytest.raises(IdempotencyConflictError):
        assemble(core, seed=43)


def test_public_assembly_shortage_creates_nothing(publish_core):
    core = publish_core
    before, paths = core.con.total_changes, set(core.workspace_root.rglob('*'))
    with pytest.raises(ValidationError) as error:
        assemble(core, blueprint={'slots': [{'id': 's', 'count': 5}]})
    assert error.value.details['gaps']
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths
    assert job(core) is None


@pytest.mark.parametrize('boundary', ['render', 'rename'])
def test_publication_failure_releases_and_stable_retry(publish_core, monkeypatch, boundary):
    core = publish_core
    name = 'render_staged_paper' if boundary == 'render' else 'publish_directory'
    original = getattr(coordinator, name)
    def failure(*args):
        raise RuntimeError('Injected failure')
    monkeypatch.setattr(coordinator, name, failure)
    with pytest.raises(RuntimeError):
        assemble(core)
    saved = job(core)
    snapshot = AssemblyRepository(core.con).items('publication')
    assert saved['state'] == 'failed'
    assert not Path(saved['staging_path']).exists() and not Path(saved['final_path']).exists()
    assert not AssemblyRepository(core.con).reservations('alg')
    with pytest.raises(IdempotencyConflictError):
        assemble(core, title='changed')
    monkeypatch.setattr(coordinator, name, original)
    result = assemble(core)
    assert result['data']['assessment_id'] == saved['assessment_id']
    assert snapshot == AssemblyRepository(core.con).items('publication')
    assert core.con.execute('SELECT COUNT(*) FROM assessments').fetchone()[0] == 1


def test_rename_before_commit_recovered_without_rerender(publish_core, monkeypatch):
    core = publish_core
    original = AssemblyRepository.finalize
    def fail(self, *args):
        result = original(self, *args)
        raise RuntimeError('crash before final commit')
    monkeypatch.setattr(AssemblyRepository, 'finalize', fail)
    with pytest.raises(RuntimeError):
        assemble(core)
    saved = job(core)
    assert saved['state'] == 'pending'
    assert Path(saved['final_path']).is_dir()
    assert core.con.execute('SELECT COUNT(*) FROM assessments').fetchone()[0] == 0
    pdf = Path(saved['final_path'])/'test.pdf'
    original_bytes = pdf.read_bytes()
    monkeypatch.setattr(AssemblyRepository, 'finalize', original)
    monkeypatch.setattr(coordinator, 'render_staged_paper', lambda *a: pytest.fail('must recover saved bytes'))
    result = assemble(core)
    assert result['data']['assessment_id'] == saved['assessment_id']
    assert pdf.read_bytes() == original_bytes
    assert core.con.execute('SELECT COUNT(*) FROM assessments').fetchone()[0] == 1


def test_dead_job_cleanup_waits_for_readiness_then_releases(publish_core, monkeypatch):
    core = publish_core
    def crash(*args):
        raise KeyboardInterrupt('process exits during render')
    with monkeypatch.context() as patch:
        patch.setattr(coordinator, 'render_staged_paper', crash)
        with pytest.raises(KeyboardInterrupt):
            assemble(core)
    old = job(core)
    assert old['state'] == 'pending' and Path(old['staging_path']).exists()
    before, paths = core.con.total_changes, set(core.workspace_root.rglob('*'))
    with pytest.raises(ValidationError):
        assemble(core, 'shortage', blueprint={'slots': [{'id': 's', 'count': 20}]})
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths
    assemble(core, 'next')
    assert job(core)['state'] == 'failed'
    assert not Path(old['staging_path']).exists()
    assert not AssemblyRepository(core.con).reservations('alg')


def test_live_owner_never_stolen_and_identical_retry_conflicts(publish_core, monkeypatch):
    core = publish_core
    render = coordinator.render_staged_paper
    def active(paper, stage):
        # A second API connection sees a lock-proven live reservation even with
        # an arbitrarily old timestamp. Same-process flock uses independent FDs.
        core.con.execute("UPDATE assembly_jobs SET updated_at='1900-01-01'")
        with CourseTutor(core.workspace_root) as other:
            before = other.con.total_changes
            with pytest.raises(ConflictError):
                assemble(other)
            assert other.con.total_changes == before
            result = prepare_exam(other.con, 'alg', 'alice', {'slots': [{'id': 's', 'count': 3}]}, 42,
                                  live_request_ids={'publication'})
            assert len(result['items']) == 3
            with pytest.raises(ValidationError):
                assemble(other, 'cannot-steal', blueprint={'slots': [{'id': 's', 'count': 4}]})
        assert job(core)['state'] == 'pending'
        return render(paper, stage)
    monkeypatch.setattr(coordinator, 'render_staged_paper', active)
    assemble(core)


def test_saved_retry_revalidates_without_reselecting(publish_core, monkeypatch):
    core = publish_core
    with monkeypatch.context() as patch:
        patch.setattr(coordinator, 'render_staged_paper', lambda *a: (_ for _ in ()).throw(RuntimeError()))
        with pytest.raises(RuntimeError):
            assemble(core)
    saved = AssemblyRepository(core.con).items('publication')[0]
    core.con.execute("UPDATE exercise_versions SET question_text='changed' WHERE id=?", (saved['exercise_version_id'],))
    before = core.con.total_changes
    with pytest.raises(ValidationError, match='Saved selection'):
        assemble(core)
    assert core.con.total_changes == before
    assert job(core)['state'] == 'failed'
    assert AssemblyRepository(core.con).items('publication')[0] == saved


def test_destination_collision_never_replaced(publish_core, monkeypatch):
    core = publish_core
    render = coordinator.render_staged_paper
    def collision(paper, stage):
        result = render(paper, stage)
        final = Path(job(core)['final_path'])
        final.mkdir()
        (final/'untouched').write_text('sentinel')
        return result
    monkeypatch.setattr(coordinator, 'render_staged_paper', collision)
    with pytest.raises(ValidationError, match='destination'):
        assemble(core)
    assert (Path(job(core)['final_path'])/'untouched').read_text() == 'sentinel'
    assert job(core)['state'] == 'failed'


def test_saved_export_preserves_bytes_and_missing_export_uses_snapshots(publish_core, monkeypatch):
    core = publish_core
    result = assemble(core)['data']
    pdf = Path(result['pdf_path'])
    before = pdf.read_bytes()
    paper = core.assessment_paper(result['assessment_id'])
    core.con.execute("UPDATE exercise_versions SET question_text='changed',validation_state='draft'")
    core.con.execute("UPDATE assessments SET title='changed'")
    count = core.con.total_changes
    assert core.export_assessment(result['assessment_id'])['pdf_path'] == str(pdf)
    assert pdf.read_bytes() == before
    shutil.rmtree(pdf.parent)
    monkeypatch.setattr(coordinator, 'prepare_exam', lambda *a, **kw: pytest.fail('no selection on export'))
    exported = core.export_assessment(result['assessment_id'])
    assert Path(exported['pdf_path']).exists()
    assert core.assessment_paper(result['assessment_id']) == paper
    assert 'changed' not in (pdf.parent/'test.html').read_text()
    assert core.con.total_changes == count
    (pdf.parent/'test.html').write_text('corruption')
    with pytest.raises(ValidationError, match='artifact set'):
        core.export_assessment(result['assessment_id'])
    assert (pdf.parent/'test.html').read_text() == 'corruption'


def test_owned_orphan_cleanup_skips_live_and_unknown(publish_core):
    core = publish_core
    result = assemble(core)
    parent = Path(result['data']['pdf_path']).parent.parent
    fake = dict(request_id='orphan', assessment_id='orphan-id', input_hash='hash')
    orphan = parent/'.assembly-orphan-id'
    orphan.mkdir()
    (orphan/'.assembly-owner.json').write_text(json.dumps(fake))
    fd = coordinator._lock(core, 'orphan', create=True)
    unknown = parent/'.assembly-unknown'
    unknown.mkdir()
    (unknown/'sentinel').write_text('untouched')
    coordinator._clean_orphans(core, AssemblyRepository(core.con), parent)
    assert orphan.exists()
    os.close(fd)
    coordinator._clean_orphans(core, AssemblyRepository(core.con), parent)
    assert not orphan.exists() and (unknown/'sentinel').exists()


def test_real_assembly_pdf_smoke(selection_core):
    if not paper_export.browser_executable():
        pytest.skip('supported browser unavailable')
    core = selection_core
    question(core, 'real renderer')
    result = assemble(core)['data']
    from pypdf import PdfReader
    pages = PdfReader(result['pdf_path']).pages
    assert len(pages) > 0
    text = '\n'.join(p.extract_text() for p in pages)
    assert 'Secret solution' not in text and 'Question' in text


def test_next_request_recovers_renamed_job_and_keeps_its_reservation(publish_core, monkeypatch):
    core = publish_core
    original = AssemblyRepository.finalize
    with monkeypatch.context() as patch:
        patch.setattr(AssemblyRepository, 'finalize', lambda *a: (_ for _ in ()).throw(RuntimeError()))
        with pytest.raises(RuntimeError):
            assemble(core)
    old = job(core)
    old_version = AssemblyRepository(core.con).items('publication')[0]['exercise_version_id']
    next_result = assemble(core, 'next')
    assert job(core)['state'] == 'published'
    assert Path(old['final_path']).is_dir()
    assert next_result['data']['assessment_id'] != old['assessment_id']
    assert old_version not in selected({'items': AssemblyRepository(core.con).items('next')})
    assert core.con.execute('SELECT COUNT(*) FROM assessments').fetchone()[0] == 2
    assert core.con.execute('SELECT COUNT(*) FROM operation_receipts WHERE operation_name="assemble_exam"').fetchone()[0] == 2


def test_unrecognized_staging_and_empty_final_are_preserved(publish_core, monkeypatch):
    core = publish_core
    original = coordinator.render_staged_paper
    def empty_collision(paper, stage):
        result = original(paper, stage)
        Path(job(core)['final_path']).mkdir()
        return result
    with monkeypatch.context() as patch:
        patch.setattr(coordinator, 'render_staged_paper', empty_collision)
        with pytest.raises(ValidationError):
            assemble(core)
    old = job(core)
    assert Path(old['final_path']).is_dir() and list(Path(old['final_path']).iterdir()) == []
    Path(old['final_path']).rmdir()
    staging = Path(old['staging_path'])
    staging.mkdir()
    (staging/'foreign').write_text('keep')
    with pytest.raises(FileExistsError):
        assemble(core)
    assert (staging/'foreign').read_text() == 'keep'
    assert job(core)['state'] == 'failed'
    assert not AssemblyRepository(core.con).reservations('alg')


@pytest.mark.parametrize('kwargs', [{'seed': True}, {'request': ''}, {'title': ''},
                                  {'blueprint': []}, {'blueprint': {'slots': [], 'x': float('nan')}}])
def test_public_invalid_input_has_no_output(publish_core, kwargs):
    core = publish_core
    before, paths = core.con.total_changes, set(core.workspace_root.rglob('*'))
    with pytest.raises(ValidationError):
        assemble(core, **kwargs)
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths


def test_render_cannot_run_inside_caller_transaction(publish_core):
    core = publish_core
    core.con.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(ValidationError, match='active transaction'):
            assemble(core)
        assert job(core) is None
    finally:
        core.con.rollback()


def reviewed_relaxation_bank(core, tmp_path):
    topic = core.create_topic('alg', 'Relaxation topic')['id']
    source = tmp_path / 'relaxation-exam.txt'
    source.write_text('Question 1: Prove the first special claim.\nQuestion 2: Compute the second special value.')
    sid = core.ingest_source('alg', source, role='exam')['data']['source_version_id']
    questions = core.list_questions('alg', sid)['questions']
    assert len(questions) == 2
    for q, difficulty, year in zip(questions, ['hard', 'easy'], [2020, 2025]):
        vid = q['exercise_version_id']
        core.con.execute("UPDATE exercise_versions SET validation_state='validated',topic_mappings_json=? WHERE id=?",
                         (json.dumps([topic]), vid))
        core.con.execute('UPDATE question_fingerprints SET exact_hash=?,structure_hash=? WHERE exercise_version_id=?',
                         (vid, vid, vid))
        core.con.execute("UPDATE question_occurrences SET review_status='accepted',visual_review_status='verified',metadata_json=? WHERE id=?",
                         (json.dumps(dict(difficulty=difficulty, year=year, question_type='proof', section='A')), q['id']))
    blueprint = {'slots': [dict(id='s', count=1, topic_ids=[topic], question_type='proof', section='A',
                                difficulty='hard', year_min=2024)],
                 'relaxations': ['difficulty', 'year_min']}
    return questions, blueprint


@pytest.mark.parametrize('order,index', [(['difficulty', 'year_min'], 1), (['year_min', 'difficulty'], 0)])
def test_ordered_relaxation_readiness_and_selection(selection_core, tmp_path, order, index):
    core = selection_core
    questions, bp = reviewed_relaxation_bank(core, tmp_path)
    bp['relaxations'] = order
    before, paths = core.con.total_changes, set(core.workspace_root.rglob('*'))
    report = core.blueprint_readiness('alg', bp, 'alice')
    prepared = prepare_exam(core.con, 'alg', 'alice', bp, 42)
    policy = prepared['relaxation_policy']
    assert 'relaxation_policy' not in report
    assert report['analysis']['joint']['status'] == 'feasible'
    assert report['slots'][0]['eligible']['version_ids'] == selected(prepared)
    assert policy['applied'] == order[:1]
    assert [a['status'] for a in policy['attempted']] == ['infeasible', 'feasible']
    assert selected(prepared) == [questions[index]['exercise_version_id']]
    effective_slot = prepared['effective_blueprint']['slots'][0]
    assert order[0] not in effective_slot and order[1] in effective_slot
    assert effective_slot['topic_ids'] == bp['slots'][0]['topic_ids']
    assert bp['slots'][0]['difficulty'] == 'hard'  # caller input is immutable
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths


@pytest.mark.parametrize('policy', [['topic_ids'], ['question_type'], ['count'], ['repeat'],
                                    ['difficulty', 'difficulty'], [1], 'difficulty'])
def test_relaxation_policy_validation(selection_core, policy):
    with pytest.raises(ValidationError):
        prepare_exam(selection_core.con, 'alg', 'alice',
                     {'slots': [{'id': 's', 'count': 1}], 'relaxations': policy}, 1)


@pytest.mark.parametrize('field,value', [('year_min', True), ('year_max', 10000),
                                        ('difficulty', ''), ('source_version_ids', ['foreign'])])
def test_relaxation_validates_original_constraints(selection_core, field, value):
    with pytest.raises(ValidationError):
        prepare_exam(selection_core.con, 'alg', 'alice',
                     {'slots': [{'id': 's', 'count': 1, field: value}], 'relaxations': [field]}, 1)


@pytest.mark.parametrize('gate', ['count', 'topic', 'type', 'section', 'math', 'visual', 'extraction', 'provenance'])
def test_relaxation_preserves_hard_gates_creates_nothing(publish_core, tmp_path, gate):
    core = publish_core
    questions, bp = reviewed_relaxation_bank(core, tmp_path)
    if gate == 'count':
        bp['slots'][0]['count'] = 3
    elif gate == 'topic':
        bp['slots'][0]['topic_ids'] = [core.create_topic('alg', 'Other topic')['id']]
    elif gate in ('type', 'section'):
        bp['slots'][0]['question_type' if gate == 'type' else 'section'] = 'missing'
    elif gate == 'provenance':
        core.con.execute('DELETE FROM question_occurrences')
    elif gate == 'math':
        core.con.execute("UPDATE exercise_versions SET validation_state='pending_review'")
    else:
        field = 'visual_review_status' if gate == 'visual' else 'review_status'
        core.con.execute(f"UPDATE question_occurrences SET {field}='pending_review'")
    before, paths = core.con.total_changes, set(core.workspace_root.rglob('*'))
    with pytest.raises(ValidationError) as error:
        assemble(core, blueprint=bp)
    assert error.value.details['gaps']
    assert set(error.value.details) == {'gaps'}
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths


def test_relaxed_retry_keeps_saved_policy_and_reexport(publish_core, tmp_path, monkeypatch):
    core = publish_core
    questions, bp = reviewed_relaxation_bank(core, tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(coordinator, 'render_staged_paper', lambda *a: (_ for _ in ()).throw(RuntimeError('fail')))
        with pytest.raises(RuntimeError):
            assemble(core, blueprint=bp)
    saved = job(core)
    assert saved['generation']['blueprint'] == bp
    assert saved['generation']['relaxation_policy']['applied'] == ['difficulty']
    assert saved['generation']['effective_blueprint']['slots'][0]['year_min'] == 2024
    items = AssemblyRepository(core.con).items('publication')
    # Now a stricter prefix would work; retry must keep its original selection.
    core.con.execute('UPDATE question_occurrences SET metadata_json=? WHERE id=?',
                     (json.dumps(dict(difficulty='hard', year=2025, question_type='proof', section='A')), questions[0]['id']))
    monkeypatch.setattr(coordinator, 'prepare_exam', lambda *a, **k: pytest.fail('retry must not select'))
    result = assemble(core, blueprint=bp)['data']
    assert job(core)['generation'] == saved['generation']
    assert AssemblyRepository(core.con).items('publication') == items
    public = (Path(result['pdf_path']).parent / 'presentation.json').read_text()
    assert 'relaxation_policy' not in public and 'selection_inputs' not in public
    shutil.rmtree(Path(result['pdf_path']).parent)
    core.con.execute("UPDATE exercise_versions SET question_text='CHANGED'")
    monkeypatch.setattr(readiness, '_report', lambda *a, **k: pytest.fail('export must not select'))
    core.export_assessment(result['assessment_id'], 'alg')
    assert 'CHANGED' not in (Path(result['pdf_path']).parent / 'test.html').read_text()


@pytest.mark.parametrize('boundary', ['pending', 'mkdir', 'marker_initial', 'marker_complete', 'render',
                                      'verify', 'rename_before', 'rename_after', 'finalize_before', 'finalize_after'])
def test_each_publication_boundary_failure(publish_core, monkeypatch, boundary):
    core = publish_core
    with monkeypatch.context() as patch:
        def failure(*a, **k):
            raise RuntimeError('injected ' + boundary)
        if boundary in ('pending', 'finalize_before', 'finalize_after'):
            name = 'create' if boundary == 'pending' else 'finalize'
            original = getattr(AssemblyRepository, name)
            def repository_failure(self, *a, **k):
                if boundary in ('pending', 'finalize_after'):
                    original(self, *a, **k)
                failure()
            patch.setattr(AssemblyRepository, name, repository_failure)
        elif boundary == 'mkdir':
            original = Path.mkdir
            def mkdir(path, *a, **k):
                if path.name.startswith('.assembly-') and path.name != '.assembly-locks':
                    failure()
                return original(path, *a, **k)
            patch.setattr(Path, 'mkdir', mkdir)
        elif boundary.startswith('marker'):
            original = Path.write_text
            def marker(path, data, *a, **k):
                if path.name == '.assembly-owner.json' and (
                        ('manifest_sha256' in data) == (boundary == 'marker_complete')):
                    failure()
                return original(path, data, *a, **k)
            patch.setattr(Path, 'write_text', marker)
        elif boundary.startswith('rename'):
            original = coordinator.publish_directory
            def rename(*a):
                if boundary == 'rename_after':
                    original(*a)
                failure()
            patch.setattr(coordinator, 'publish_directory', rename)
        else:
            patch.setattr(coordinator, 'render_staged_paper' if boundary == 'render' else 'verify_staged_paper', failure)
        with pytest.raises(RuntimeError):
            assemble(core)
    saved = job(core)
    after_rename = boundary in ('rename_after', 'finalize_before', 'finalize_after')
    if boundary == 'pending':
        assert saved is None
    else:
        assert saved['state'] == ('pending' if after_rename else 'failed')
        assert not Path(saved['staging_path']).exists()
        assert Path(saved['final_path']).exists() == after_rename
        assert bool(AssemblyRepository(core.con).reservations('alg')) == after_rename
    assert core.con.execute('SELECT COUNT(*) FROM assessments').fetchone()[0] == 0
    assert core.con.execute('SELECT COUNT(*) FROM operation_receipts').fetchone()[0] == 0
    result = assemble(core)['data']
    assert Path(result['pdf_path']).is_file()
    assert core.con.execute('SELECT COUNT(*) FROM assessments').fetchone()[0] == 1
    assert job(core)['state'] == 'published'


@pytest.mark.parametrize('field', ['source_version_ids', 'year_max'])
def test_other_authorized_relaxations(selection_core, tmp_path, field):
    core = selection_core
    questions, bp = reviewed_relaxation_bank(core, tmp_path)
    slot = bp['slots'][0]
    slot.pop('year_min')
    if field == 'source_version_ids':
        other = tmp_path / 'other-exam.txt'
        other.write_text('Question 1: A different source claim.')
        slot[field] = [core.ingest_source('alg', other, role='exam')['data']['source_version_id']]
    else:
        slot[field] = 2010
    bp['relaxations'] = [field]
    result = prepare_exam(core.con, 'alg', 'alice', bp, 42)
    assert result['relaxation_policy']['applied'] == [field]
    assert selected(result) == [questions[0]['exercise_version_id']]


def test_strict_success_does_not_apply_authorized_policy(selection_core, tmp_path):
    core = selection_core
    questions, bp = reviewed_relaxation_bank(core, tmp_path)
    bp['slots'][0]['year_min'] = 2019
    result = prepare_exam(core.con, 'alg', 'alice', bp, 42)
    assert result['relaxation_policy']['applied'] == []
    assert len(result['relaxation_policy']['attempted']) == 1
    assert selected(result) == [questions[0]['exercise_version_id']]


@pytest.mark.parametrize('kind', ['exposure', 'reservation', 'similarity'])
def test_relaxation_retains_history_filters(publish_core, tmp_path, kind):
    core = publish_core
    questions, bp = reviewed_relaxation_bank(core, tmp_path)
    bp['slots'][0]['count'] = 2
    a, b = [q['exercise_version_id'] for q in questions]
    if kind == 'exposure':
        core.start_attempt('alg', a, learner_id='alice')
    elif kind == 'reservation':
        core.create_assessment('alg', 'Reservation', selected_exercise_version_ids=[a], learner_id='alice')
    else:
        edge(core, a, b)
    before, paths = core.con.total_changes, set(core.workspace_root.rglob('*'))
    with pytest.raises(ValidationError) as error:
        assemble(core, blueprint=bp)
    assert error.value.details['gaps']
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths


def record_selection_result(core, version, topic, correct=False, *, learner='alice',
                            course='alg', attempt=None, skill='count', subpart='default', level=None):
    if attempt is None:
        attempt = core.start_attempt(course, version, learner_id=learner)['data']['id']
    revision = core.con.execute('SELECT current_revision FROM attempts WHERE id=?', (attempt,)).fetchone()[0]
    event = core.record_attempt_event(attempt, revision, 'work_submission',
                                     content='Submitted reasoning', subpart_key=subpart)['data']['event']
    evaluation = dict(topic_id=topic, skill_id=skill, subpart_key=subpart,
                      correct=correct, rationale='Reviewed submitted reasoning')
    if level:
        evaluation['demonstrated_level'] = level
    receipt = core.commit_evidence(attempt, [evaluation], submission_event_id=event['id'])
    return receipt['data']['evidence_created'][0], event


def adaptive_weight(core, candidate, learner='alice'):
    return prepare_exam(core.con, 'alg', learner, {'slots': [{'id': 's', 'count': 1}]}, 42)[
        'selection_inputs']['weights'][candidate]


def test_family_results_replace_retries_and_variants_with_latest_submission(selection_core):
    core = selection_core
    topic = core.create_topic('alg', 'Counting')['id']
    past = question(core, 'past', [topic], family='shared')
    variant = question(core, 'variant', [topic], family='shared')
    distinct = question(core, 'distinct', [topic])
    candidate = question(core, 'candidate', [topic])
    first, _ = record_selection_result(core, past, topic)
    assert adaptive_weight(core, candidate)['weight'] == 2.5
    retry, _ = record_selection_result(core, past, topic, attempt=first['attempt_id'])
    assert adaptive_weight(core, candidate)['weight'] == 2.5
    latest, _ = record_selection_result(core, variant, topic)
    weight = adaptive_weight(core, candidate)
    assert weight['weight'] == 2.5 and weight['evidence_ids'] == [latest['id']]
    other, _ = record_selection_result(core, distinct, topic, True)
    weight = adaptive_weight(core, candidate)
    assert weight['weight'] == pytest.approx(1 + .5 + 1/3)
    assert weight['evidence_ids'] == sorted([latest['id'], other['id']])
    changed, _ = record_selection_result(core, past, topic, True)
    weight = adaptive_weight(core, candidate)
    assert weight['weight'] == pytest.approx(1 + 1/3)
    assert weight['evidence_ids'] == sorted([changed['id'], other['id']])
    # Correct an older submission now: correction time cannot make it newest.
    corrected = core.correct_evidence(retry['id'], 'Reviewed again',
                                     replacement={'demonstrated_level': 'independent_mastery'})['data']['resulting_evidence']
    assert adaptive_weight(core, candidate) == weight
    core.correct_evidence(changed['id'], 'Retract latest')
    assert adaptive_weight(core, candidate)['evidence_ids'] == sorted([latest['id'], other['id']])
    replacement = core.correct_evidence(latest['id'], 'Correct latest eligible outcome',
                                       replacement={'demonstrated_level': 'independent_mastery'})['data']['resulting_evidence']
    assert adaptive_weight(core, candidate)['weight'] == pytest.approx(1 + 1/3)
    assert adaptive_weight(core, candidate)['evidence_ids'] == sorted([replacement['id'], other['id']])
    assert core.con.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 7
    assert core.con.execute('SELECT status FROM evidence WHERE id=?', (corrected['id'],)).fetchone()[0] == 'active'


def test_family_representatives_use_submission_time_then_ids(selection_core):
    core = selection_core
    topic = core.create_topic('alg', 'Chronology')['id']
    past = question(core, 'past', [topic], family='shared')
    candidate = question(core, 'candidate', [topic])
    old, old_event = record_selection_result(core, past, topic)
    old, old_event = record_selection_result(core, past, topic, attempt=old['attempt_id'])
    new, new_event = record_selection_result(core, past, topic, True)
    # Older attempt has a higher event index, and its evidence was updated later.
    core.con.execute("UPDATE attempt_events SET created_at='2026-01-01T00:00:00+00:00' WHERE id=?", (old_event['id'],))
    core.con.execute("UPDATE attempt_events SET created_at='2026-01-02T00:00:00+00:00' WHERE id=?", (new_event['id'],))
    core.con.execute("UPDATE evidence SET updated_at='2099-01-01' WHERE id=?", (old['id'],))
    assert adaptive_weight(core, candidate)['evidence_ids'] == [new['id']]
    core.con.execute("UPDATE attempt_events SET created_at='2026-01-02T00:00:00+00:00' WHERE id=?", (old_event['id'],))
    winner = max([(old_event['id'], old['id']), (new_event['id'], new['id'])])[1]
    first = prepare_exam(core.con, 'alg', 'alice', {'slots': [{'id': 's', 'count': 1}]}, 42)
    again = prepare_exam(core.con, 'alg', 'alice', {'slots': [{'id': 's', 'count': 1}]}, 42)
    assert first['selection_inputs']['weights'][candidate]['evidence_ids'] == [winner]
    assert first['selection_inputs'] == again['selection_inputs']
    assert selected(first) == selected(again)
    assert first['selection_inputs']['policy'] == 'strict_weighted_priority_v2'


def test_family_units_keep_topics_skills_and_subparts_distinct(selection_core):
    core = selection_core
    topic = core.create_topic('alg', 'Counting')['id']
    second_topic = core.create_topic('alg', 'Proof')['id']
    past = question(core, 'past', [topic, second_topic])
    candidate = question(core, 'candidate', [topic])
    second_candidate = question(core, 'second candidate', [second_topic])
    first, _ = record_selection_result(core, past, topic, subpart='a')
    second, _ = record_selection_result(core, past, topic, True, subpart='b')
    third, _ = record_selection_result(core, past, topic, True, skill='proof', subpart='a')
    fourth, _ = record_selection_result(core, past, second_topic, True, subpart='a')
    assert adaptive_weight(core, candidate)['evidence_ids'] == sorted([first['id'], second['id'], third['id']])
    assert adaptive_weight(core, candidate)['weight'] == pytest.approx(1 + 1/3 + 1/4)
    assert adaptive_weight(core, second_candidate)['evidence_ids'] == [fourth['id']]


@pytest.mark.parametrize('invalid', ['pending', 'observation', 'stale_evidence', 'stale_attempt',
                                    'stale_submission', 'extraction', 'visual', 'unvalidated',
                                    'new_submission', 'learner', 'course'])
def test_ineligible_family_results_do_not_replace_eligible_unit(selection_core, tmp_path, invalid):
    core = selection_core
    topic = core.create_topic('alg', 'Counting')['id']
    past = question(core, 'past', [topic], family='shared')
    candidate = question(core, 'candidate', [topic])
    good, _ = record_selection_result(core, past, topic)
    if invalid == 'course':
        core.create_course('Other', course_id='other')
        foreign_topic = core.create_topic('other', 'Counting')['id']
        foreign = core.create_exercise('other', 'shared', 'Other course question',
                                       topic_mappings=[foreign_topic], reference_solution='Checked solution', rubric={'points': 1})['exercise_version_id']
        core.validate_exercise_version(foreign, expected_revision=1, checks={'review': True})
        record_selection_result(core, foreign, foreign_topic, True, course='other')
    else:
        if invalid in ('extraction', 'visual'):
            source = tmp_path / 'source.txt'
            source.write_text('Question 1: Count the special objects.')
            sid = core.ingest_source('alg', source, role='exam')['data']['source_version_id']
            variant = core.list_questions('alg', sid)['questions'][0]['exercise_version_id']
            core.con.execute("UPDATE exercise_versions SET validation_state='validated' WHERE id=?", (variant,))
            core.con.execute("UPDATE question_occurrences SET review_status='accepted',visual_review_status='verified'")
            core.con.execute("UPDATE exercises SET exercise_family='shared' WHERE id=(SELECT exercise_id FROM exercise_versions WHERE id=?)", (variant,))
        else:
            variant = question(core, 'variant', [topic], family='shared')
        bad, event = record_selection_result(core, variant, topic, True,
                                             learner='bob' if invalid == 'learner' else 'alice')
        if invalid == 'pending':
            core.con.execute("UPDATE evidence SET status='pending_review' WHERE id=?", (bad['id'],))
        elif invalid == 'observation':
            core.con.execute("UPDATE evidence SET demonstrated_level='unassessed' WHERE id=?", (bad['id'],))
        elif invalid == 'stale_evidence':
            core.con.execute("UPDATE evidence SET exercise_content_hash='obsolete' WHERE id=?", (bad['id'],))
        elif invalid == 'stale_attempt':
            core.con.execute("UPDATE attempts SET exercise_content_hash='obsolete' WHERE id=?", (bad['attempt_id'],))
        elif invalid == 'stale_submission':
            core.con.execute("UPDATE attempt_events SET event_metadata_json=? WHERE id=?",
                             (json.dumps({'exercise_content_hash': 'obsolete'}), event['id']))
        elif invalid in ('extraction', 'visual'):
            field = 'review_status' if invalid == 'extraction' else 'visual_review_status'
            core.con.execute(f"UPDATE question_occurrences SET {field}='pending_review' WHERE exercise_version_id=?", (variant,))
        elif invalid == 'unvalidated':
            core.con.execute("UPDATE exercise_versions SET validation_state='draft' WHERE id=?", (variant,))
        elif invalid == 'new_submission':
            core.record_attempt_event(bad['attempt_id'], 2, 'work_submission', content='Unevaluated newer work')
    before, paths = core.con.total_changes, set(core.workspace_root.rglob('*'))
    weight = adaptive_weight(core, candidate)
    assert weight['weight'] == 2.5 and weight['evidence_ids'] == [good['id']]
    assert core.con.total_changes == before and set(core.workspace_root.rglob('*')) == paths


def test_saved_family_weights_and_reexport_survive_later_results(publish_core, monkeypatch):
    core = publish_core
    topic = core.create_topic('alg', 'Counting')['id']
    past = question(core, 'past', [topic])
    candidate = question(core, 'candidate', [topic])
    first, _ = record_selection_result(core, past, topic)
    result = assemble(core)['data']
    saved = job(core)['generation']
    assert saved['selection_inputs']['weights'][candidate]['evidence_ids'] == [first['id']]
    original_paper = core.assessment_paper(result['assessment_id'])
    record_selection_result(core, past, topic, True)
    fresh = question(core, 'fresh candidate', [topic])
    assert adaptive_weight(core, fresh)['weight'] == 1.5
    assert job(core)['generation'] == saved
    shutil.rmtree(Path(result['pdf_path']).parent)
    monkeypatch.setattr(coordinator, 'prepare_exam', lambda *a, **k: pytest.fail('export must use snapshots'))
    before = core.con.total_changes
    core.export_assessment(result['assessment_id'])
    assert core.assessment_paper(result['assessment_id']) == original_paper
    assert job(core)['generation'] == saved and core.con.total_changes == before


def test_family_evidence_id_tie_and_retraction_to_unknown(selection_core):
    from dataclasses import replace
    from course_tutor.storage.repositories import EvidenceRepository

    core = selection_core
    topic = core.create_topic('alg', 'Counting')['id']
    past = question(core, 'past', [topic])
    candidate = question(core, 'candidate', [topic])
    original, _ = record_selection_result(core, past, topic)
    repo = EvidenceRepository(core.con)
    # Simulate historical active evaluations of the same submission. Evidence ID,
    # rather than correction/update time, is the final deterministic tie breaker.
    duplicate = replace(repo.get_evidence(original['id']), id='zz-tie',
                        demonstrated_level='independent_mastery', updated_at='1900-01-01')
    repo.create_evidence(duplicate)
    assert adaptive_weight(core, candidate)['evidence_ids'] == ['zz-tie']
    assert adaptive_weight(core, candidate)['weight'] == 1.5
    core.correct_evidence('zz-tie', 'Retract duplicate')
    assert adaptive_weight(core, candidate)['evidence_ids'] == [original['id']]
    core.correct_evidence(original['id'], 'Retract remaining evidence')
    weight = adaptive_weight(core, candidate)
    assert weight['weight'] == 1 and weight['evidence_ids'] == []
    assert weight['reason'] == 'unknown_topics_neutral'


@pytest.mark.parametrize('invalid', ['observation', 'stale_identity', 'pending'])
def test_ineligible_submission_tie_cannot_hide_valid_representative(selection_core, invalid):
    from dataclasses import replace
    from course_tutor.storage.repositories import EvidenceRepository

    core = selection_core
    topic = core.create_topic('alg', 'Counting')['id']
    past = question(core, 'past', [topic])
    candidate = question(core, 'candidate', [topic])
    original, _ = record_selection_result(core, past, topic)
    repo = EvidenceRepository(core.con)
    fields = {'demonstrated_level': 'unassessed'} if invalid == 'observation' else (
        {'exercise_content_hash': 'obsolete'} if invalid == 'stale_identity' else {'status': 'pending_review'})
    repo.create_evidence(replace(repo.get_evidence(original['id']), id='zz-ineligible', **fields))
    weight = adaptive_weight(core, candidate)
    assert weight['evidence_ids'] == [original['id']] and weight['weight'] == 2.5


def test_same_submission_evaluated_topics_have_separate_representatives(selection_core):
    from dataclasses import replace
    from course_tutor.storage.repositories import EvidenceRepository

    core = selection_core
    topic = core.create_topic('alg', 'Counting')['id']
    other = core.create_topic('alg', 'Proof')['id']
    past = question(core, 'past', [topic, other])
    candidate = question(core, 'candidate', [topic])
    other_candidate = question(core, 'other candidate', [other])
    original, _ = record_selection_result(core, past, topic)
    repo = EvidenceRepository(core.con)
    repo.create_evidence(replace(repo.get_evidence(original['id']), id='zz-other-topic', topic_id=other,
                                demonstrated_level='independent_mastery'))
    assert adaptive_weight(core, candidate)['evidence_ids'] == [original['id']]
    assert adaptive_weight(core, other_candidate)['evidence_ids'] == ['zz-other-topic']
