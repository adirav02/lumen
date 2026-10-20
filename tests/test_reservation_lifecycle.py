"""Reservation ledger storage contracts; test workspaces contain no learner data."""
import json
import sqlite3

import pytest

from course_tutor.api import CourseTutor
from course_tutor.errors import ValidationError
from course_tutor.models import Assessment, AssessmentItem, Attempt
from course_tutor.storage import migrations
from course_tutor.storage.db import atomic_transaction
from course_tutor.storage.repositories import AssessmentRepository, AssemblyRepository, ReservationRepository, AttemptRepository
from test_exam_assembly import assembly_storage


@pytest.fixture
def saved(tmp_path):
    with CourseTutor(tmp_path / 'workspace') as core:
        core.create_course('Algorithms', course_id='alg')
        version = core.create_exercise('alg', 'family', 'Question')['exercise_version_id']
        with atomic_transaction(core.con):
            AssessmentRepository(core.con).create_assessment(
                Assessment(id='exam', course_id='alg', title='Draft', learner_id='alice'),
                [AssessmentItem(id='item', assessment_id='exam', exercise_version_id=version, item_order=1)])
        yield core, ReservationRepository(core.con)


def release(repo, **extra):
    return repo.release(course_id='alg', learner_id='alice', assessment_id='exam', **extra)


def test_release_scope_transaction_rollback_and_history(saved):
    core, repo = saved
    before = [tuple(row) for row in core.con.execute('SELECT * FROM assessment_items')]
    with pytest.raises(ValidationError):
        release(repo)
    for course, owner in [('wrong', 'alice'), ('alg', 'bob'), ('alg', None)]:
        with pytest.raises(ValidationError), atomic_transaction(core.con):
            repo.release(course_id=course, learner_id=owner, assessment_id='exam')
    with pytest.raises(RuntimeError), atomic_transaction(core.con):
        release(repo)
        raise RuntimeError('rollback')
    assert repo.get('exam') is None
    with atomic_transaction(core.con):
        result = release(repo)
        assert release(repo) == result
    assert repo.candidates('alg', 'alice') == []
    assert before == [tuple(row) for row in core.con.execute('SELECT * FROM assessment_items')]
    with pytest.raises(ValidationError), atomic_transaction(core.con):
        release(repo, reason='cancelled')
    with pytest.raises(sqlite3.IntegrityError), atomic_transaction(core.con):
        core.con.execute("INSERT INTO reservation_releases VALUES ('other','alg',NULL,'now','bad')")


@pytest.mark.parametrize('field,value', [('status','completed'), ('status','abandoned'),
    ('attempt_id','attempt'), ('points_awarded',0), ('score_status','pending_review'),
    ('score_history_json',json.dumps([{'old': 'score'}]))])
def test_used_drafts_rejected(saved, field, value):
    core, repo = saved
    if field == 'attempt_id':
        version = core.con.execute('SELECT exercise_version_id FROM assessment_items').fetchone()[0]
        AttemptRepository(core.con).create_attempt(Attempt(id='attempt', course_id='alg',
            exercise_version_id=version, learner_id='alice'))
    table = 'assessments' if field == 'status' else 'assessment_items'
    core.con.execute(f'UPDATE {table} SET {field}=?', (value,))
    with pytest.raises(ValidationError), atomic_transaction(core.con):
        release(repo)
    assert repo.get('exam') is None


def test_null_owner_and_paused_legacy_draft(saved):
    core, repo = saved
    core.con.execute("UPDATE assessments SET learner_id=NULL,status='paused'")
    core.con.execute('UPDATE assessment_items SET exposure_count=99')
    with atomic_transaction(core.con):
        result = repo.release(course_id='alg', learner_id=None, assessment_id='exam')
    assert result['learner_id'] is None


@pytest.mark.parametrize('state', ['pending', 'failed'])
def test_terminal_pending_job_guards(assembly_storage, state):
    core, assembly, args = assembly_storage
    repo = ReservationRepository(core.con)
    with atomic_transaction(core.con):
        assembly.create(**args)
        if state == 'failed':
            assembly.fail('request', 'owner')
        repo.release(course_id='alg', learner_id='alice', assessment_id='exam')
    snapshots = assembly.items('request')
    assert assembly.pending('alg') == []
    assert assembly.reservations('alg') == []
    for operation in [lambda: assembly.create(**args),
                      lambda: assembly.claim('request', 'hash', 'owner', 'new'),
                      lambda: assembly.finalize('request', 'owner', {})]:
        with pytest.raises(ValidationError), atomic_transaction(core.con):
            operation()
    assert assembly.items('request') == snapshots
    assert assembly.get('request')['state'] == state


def test_v11_upgrade_preserves_existing_data(assembly_storage, monkeypatch):
    core, assembly, args = assembly_storage
    with atomic_transaction(core.con):
        assembly.create(**args)
        for state in ['failed', 'published']:
            current = dict(args, request_id=state, assessment_id=state,
                items=[dict(args['items'][0], item_id=state)])
            assembly.create(**current)
            if state == 'failed':
                assembly.fail(state, 'owner')
            else:
                assembly.finalize(state, 'owner', {'assessment_id': state,
                    'pdf_path': '/final/student.pdf', 'summary': 'saved'})
        version = args['items'][0]['exercise_version_id']
        for state in ['open', 'paused', 'completed']:
            AssessmentRepository(core.con).create_assessment(
                Assessment(id=state, course_id='alg', title=state, status=state),
                [AssessmentItem(id=state, assessment_id=state, exercise_version_id=version,item_order=1)])
    historical = {table: [tuple(r) for r in core.con.execute('SELECT * FROM '+table)]
        for table in ['assessments', 'assessment_items', 'operation_receipts']}
    core.con.execute('DROP TABLE reservation_releases')
    core.con.execute('DELETE FROM schema_migrations WHERE version=12')
    before = [tuple(row) for row in core.con.execute('SELECT * FROM assembly_jobs')]
    snapshots = assembly.items('request')
    migrations.run_migrations(core.con)
    migrations.run_migrations(core.con)
    assert before == [tuple(row) for row in core.con.execute('SELECT * FROM assembly_jobs')]
    assert snapshots == assembly.items('request')
    assert ReservationRepository(core.con).get('exam') is None
    assert len(assembly.pending('alg')) == 1

    for table, rows in historical.items():
        assert rows == [tuple(r) for r in core.con.execute('SELECT * FROM '+table)]


def test_identity_sources_and_assessment_collision(assembly_storage):
    core, assembly, args = assembly_storage
    repo = ReservationRepository(core.con)
    with atomic_transaction(core.con):
        assembly.create(**args)
        assessment = Assessment(id='exam', course_id='alg', title='Collision', learner_id='bob')
        AssessmentRepository(core.con).create_assessment(assessment, [])
    with pytest.raises(ValidationError), atomic_transaction(core.con):
        release(repo)
    with pytest.raises(ValidationError), atomic_transaction(core.con):
        assembly.create(**dict(args, request_id='different'))


def test_released_published_snapshot_replay(assembly_storage):
    core, assembly, args = assembly_storage
    receipt = {'assessment_id': 'exam', 'pdf_path': '/final/student.pdf', 'summary': 'saved'}
    with atomic_transaction(core.con):
        assembly.create(**args)
        assembly.finalize('request', 'owner', receipt)
        release(ReservationRepository(core.con))
        assert assembly.finalize('request', 'owner', receipt) == receipt
        assert assembly.create(**args)['state'] == 'published'
    assert len(AssessmentRepository(core.con).get_items('exam')) == 1


from datetime import datetime, timedelta, timezone
import os
from course_tutor.assessment import reservations, assembly as publication
from course_tutor.errors import IdempotencyConflictError
from course_tutor.storage.repositories import ReceiptRepository


def coordinated(core, request_id='release', **kwargs):
    return reservations.release_reservation(core, 'alg', 'alice', 'exam', request_id, **kwargs)


def test_release_receipt_replay_conflicts_and_preservation(saved):
    core, repo = saved
    original = [tuple(r) for r in core.con.execute('SELECT * FROM assessment_items')]
    first = coordinated(core, reason='cancelled')
    assert first['data']['reason'] == 'cancelled'
    assert coordinated(core, reason='cancelled')['idempotent_replay'] is True
    with pytest.raises(IdempotencyConflictError):
        coordinated(core)
    with pytest.raises(IdempotencyConflictError):
        reservations.expire_reservations(core, 'alg', 'alice', 'release')
    assert original == [tuple(r) for r in core.con.execute('SELECT * FROM assessment_items')]
    assert not core.con.in_transaction


def test_release_transaction_and_detachment_guards(saved, monkeypatch):
    core, repo = saved
    with atomic_transaction(core.con), pytest.raises(ValidationError):
        coordinated(core)
    def detached():
        raise ValidationError('detached')
    monkeypatch.setattr(core, '_verify_not_detached', detached)
    with pytest.raises(ValidationError):
        coordinated(core)
    assert repo.get('exam') is None


def test_expiry_boundary_timestamp_safety_and_stable_replay(saved, monkeypatch):
    core, repo = saved
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    monkeypatch.setattr(reservations, '_now', lambda: now)
    version = core.con.execute('SELECT exercise_version_id FROM assessment_items').fetchone()[0]
    with atomic_transaction(core.con):
        for aid, created, state in [
            ('boundary', (now-timedelta(days=7)).isoformat(), 'paused'),
            ('recent', (now-timedelta(days=7)+timedelta(microseconds=1)).isoformat(), 'open'),
            ('naive', '2020-01-01T00:00:00', 'open'),
            ('malformed', 'bad', 'open'),
            ('finished', '2020-01-01T00:00:00+00:00', 'completed')]:
            AssessmentRepository(core.con).create_assessment(
                Assessment(id=aid, course_id='alg', title=aid, learner_id='alice',
                           created_at=created, status=state),
                [AssessmentItem(id=aid, assessment_id=aid, exercise_version_id=version, item_order=1)])
    result = reservations.expire_reservations(core, 'alg', 'alice', 'expiry')
    assert [r['assessment_id'] for r in result['data']['released']] == ['boundary']
    reasons = {r['assessment_id']: r['reason'] for r in result['data']['skipped']}
    assert reasons == {'exam':'recent', 'finished':'completed', 'malformed':'invalid_timestamp',
                       'naive':'invalid_timestamp', 'recent':'recent'}
    monkeypatch.setattr(reservations, '_now', lambda: now+timedelta(days=20))
    replay = reservations.expire_reservations(core, 'alg', 'alice', 'expiry')
    assert replay['data'] == result['data']
    assert replay['idempotent_replay']


def test_expiry_rolls_back_all_releases_and_receipt(saved, monkeypatch):
    core, repo = saved
    core.con.execute("UPDATE assessments SET created_at='2000-01-01T00:00:00+00:00'")
    def fail(self, receipt):
        raise RuntimeError('receipt failed')
    monkeypatch.setattr(ReceiptRepository, 'record_receipt', fail)
    with pytest.raises(RuntimeError):
        reservations.expire_reservations(core, 'alg', 'alice', 'expiry')
    assert repo.get('exam') is None
    assert not core.con.in_transaction
    assert core.con.execute("SELECT 1 FROM operation_receipts WHERE request_id='expiry'").fetchone() is None


def test_live_publication_lock_protects_release_and_expiry(assembly_storage):
    core, jobs, args = assembly_storage
    with atomic_transaction(core.con):
        jobs.create(**args)
        core.con.execute("UPDATE assembly_jobs SET created_at='2000-01-01T00:00:00+00:00'")
    fd = publication._lock(core, 'request', create=True)
    try:
        with pytest.raises(ValidationError) as error:
            coordinated(core)
        assert error.value.details['reason'] == 'active'
        result = reservations.expire_reservations(core, 'alg', 'alice', 'expiry')
        assert result['data']['skipped'] == [{'assessment_id':'exam', 'reason':'active'}]
        assert ReservationRepository(core.con).get('exam') is None
    finally:
        os.close(fd)
    coordinated(core)
    probe = publication._lock(core, 'request')
    os.close(probe)


def test_recovery_required_and_cancellation_never_delete_files(assembly_storage, tmp_path):
    core, jobs, args = assembly_storage
    final, stage = tmp_path/'final', tmp_path/'stage'
    args = dict(args, final_path=str(final), staging_path=str(stage))
    with atomic_transaction(core.con):
        job = jobs.create(**args)
        core.con.execute("UPDATE assembly_jobs SET created_at='2000-01-01T00:00:00+00:00'")
    final.mkdir()
    stage.mkdir()
    manifest = final/'presentation.json'
    manifest.write_text('{}')
    marker = dict(publication._identity(job), manifest_sha256=publication.hashlib.sha256(manifest.read_bytes()).hexdigest())
    (final/'.assembly-owner.json').write_text(json.dumps(marker))
    (stage/'keep').write_text('keep')
    with pytest.raises(ValidationError) as error:
        coordinated(core)
    assert error.value.details['reason'] == 'recovery_required'
    result = reservations.expire_reservations(core, 'alg', 'alice', 'expiry')
    assert result['data']['skipped'] == [{'assessment_id':'exam', 'reason':'recovery_required'}]
    # Incomplete artifacts belong to the original job and remain untouched.
    manifest.write_text('{"incomplete":true}')
    coordinated(core, reason='cancelled')
    assert (stage/'keep').read_text() == 'keep'
    assert manifest.exists()
    assert not publication._lock_path(core, 'request').exists()


def test_receipt_exception_releases_publication_lock(assembly_storage, monkeypatch):
    core, jobs, args = assembly_storage
    with atomic_transaction(core.con):
        jobs.create(**args)
    fd = publication._lock(core, 'request', create=True)
    os.close(fd)
    def fail(self, receipt):
        raise RuntimeError('failure')
    monkeypatch.setattr(ReceiptRepository, 'record_receipt', fail)
    with pytest.raises(RuntimeError):
        coordinated(core)
    assert not core.con.in_transaction
    assert ReservationRepository(core.con).get('exam') is None
    fd = publication._lock(core, 'request')
    os.close(fd)


def test_assembly_tombstone_checked_before_render_or_recovery(assembly_storage, monkeypatch):
    core, jobs, args = assembly_storage
    blueprint = {'slots': []}
    canonical = json.dumps({'course_id':'alg', 'learner_id':'alice', 'blueprint':blueprint,
        'seed':42, 'title':None, 'policy':'strict_weighted_priority_v1'}, sort_keys=True, allow_nan=False)
    args = dict(args, input_hash=publication.hashlib.sha256(canonical.encode()).hexdigest())
    with atomic_transaction(core.con):
        jobs.create(**args)
    coordinated(core)
    def forbidden(*args, **kwargs):
        pytest.fail('terminal job reached preparation/rendering/recovery')
    monkeypatch.setattr(publication, '_classify', forbidden)
    monkeypatch.setattr(publication, 'render_staged_paper', forbidden)
    with pytest.raises(ValidationError, match='terminal disposition'):
        publication.assemble_exam(core, 'alg', 'alice', blueprint, 42, 'request')


def test_lock_held_by_other_process(assembly_storage):
    import subprocess
    import sys
    core, jobs, args = assembly_storage
    with atomic_transaction(core.con):
        jobs.create(**args)
    fd = publication._lock(core, 'request', create=True)
    os.close(fd)
    script = '''import fcntl, sys
with open(sys.argv[1], 'r+') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    print('ready', flush=True)
    sys.stdin.readline()
'''
    process = subprocess.Popen([sys.executable, '-c', script,
        str(publication._lock_path(core, 'request'))], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'ready'
        with pytest.raises(ValidationError) as error:
            coordinated(core)
        assert error.value.details['reason'] == 'active'
    finally:
        process.communicate('\n', timeout=5)
    coordinated(core)


def test_release_race_rechecked_after_assembly_lock(assembly_storage, monkeypatch):
    core, jobs, args = assembly_storage
    blueprint = {'slots': []}
    canonical = json.dumps({'course_id':'alg', 'learner_id':'alice', 'blueprint':blueprint,
        'seed':42, 'title':None, 'policy':'strict_weighted_priority_v1'}, sort_keys=True, allow_nan=False)
    with atomic_transaction(core.con):
        jobs.create(**dict(args, input_hash=publication.hashlib.sha256(canonical.encode()).hexdigest()))
    monkeypatch.setattr(publication, '_validate_saved', lambda *args: None)
    original_lock = publication._lock
    def raced_lock(target, rid, *, create=False):
        if create:
            coordinated(core)
        return original_lock(target, rid, create=create)
    monkeypatch.setattr(publication, '_lock', raced_lock)
    with pytest.raises(ValidationError, match='terminal disposition'):
        publication.assemble_exam(core, 'alg', 'alice', blueprint, 42, 'request')
    assert jobs.get('request')['owner_token'] == 'owner'
    assert not core.con.in_transaction


def test_recheck_used_state_after_lock_acquisition(assembly_storage, monkeypatch):
    core, jobs, args = assembly_storage
    with atomic_transaction(core.con):
        jobs.create(**args)
    original_lock = publication._lock
    def changed_state(target, rid, **kwargs):
        # Simulate a completed recovery between candidate discovery and the lock.
        with atomic_transaction(core.con):
            jobs.finalize('request', 'owner', {'assessment_id':'exam', 'pdf_path':'/final/test.pdf', 'summary':'saved'})
            core.con.execute("UPDATE assessment_items SET points_awarded=0")
        return original_lock(target, rid, **kwargs)
    monkeypatch.setattr(publication, '_lock', changed_state)
    with pytest.raises(ValidationError) as error:
        coordinated(core)
    assert error.value.details['reason'] == 'used'
    assert ReservationRepository(core.con).get('exam') is None


def test_pending_assembly_request_id_collision(assembly_storage):
    core, jobs, args = assembly_storage
    with atomic_transaction(core.con):
        jobs.create(**args)
    with pytest.raises(IdempotencyConflictError):
        coordinated(core, request_id='request')
    assert ReservationRepository(core.con).get('exam') is None


def test_expiry_published_age_uses_original_job_creation(assembly_storage, monkeypatch):
    core, jobs, args = assembly_storage
    with atomic_transaction(core.con):
        jobs.create(**args)
        core.con.execute("UPDATE assembly_jobs SET created_at='2000-01-01T00:00:00+00:00'")
        jobs.finalize('request', 'owner', {'assessment_id':'exam', 'pdf_path':'/final/test.pdf', 'summary':'saved'})
    result = reservations.expire_reservations(core, 'alg', 'alice', 'expiry')
    assert [r['assessment_id'] for r in result['data']['released']] == ['exam']


from course_tutor.cli import main as cli_main


def cli_result(core, capsys, operation, payload, request='cli-request', extra=()):
    argv = [operation, '-w', str(core.workspace_root), '-j', json.dumps(payload)]
    if request is not None:
        argv += ['-r', request]
    argv += list(extra)
    with pytest.raises(SystemExit) as result:
        cli_main(argv)
    return result.value.code, json.loads(capsys.readouterr().out)


def test_public_facade_release_and_expiry(saved):
    core, repo = saved
    result = core.release_reservation('alg', 'alice', 'exam', 'public', 'cancelled')
    assert result['data']['reason'] == 'cancelled'
    assert core.release_reservation('alg', 'alice', 'exam', 'public', 'cancelled')['idempotent_replay']
    assert core.expire_reservations('alg', 'alice', 'public-expiry')['status'] == 'success'
    with pytest.raises(TypeError):
        core.expire_reservations(course_id='alg', request_id='missing-owner')


def test_cli_cancellation_replay_and_private_content(saved, capsys):
    core, repo = saved
    payload = {'course_id': 'alg', 'learner_id': 'alice', 'assessment_id': 'exam', 'reason': 'cancelled'}
    code, result = cli_result(core, capsys, 'release-reservation', payload)
    assert code == 0 and result['data']['reason'] == 'cancelled'
    assert result['receipt']['operation_name'] == 'release_reservation'
    text = json.dumps(result)
    for private in ['Question', 'reference_solution', 'rubric', 'private_answer', 'question_text']:
        assert private not in text
    code, result = cli_result(core, capsys, 'release-reservation', payload)
    assert code == 0 and result['idempotent_replay']
    code, result = cli_result(core, capsys, 'expire-reservations', {'course_id':'alg', 'learner_id':'alice'})
    assert code == 1 and result['error_code'] == 'IDEMPOTENCY_CONFLICT'


def test_cli_expiry_replay(saved, capsys):
    core, repo = saved
    with atomic_transaction(core.con):
        core.con.execute("UPDATE assessments SET created_at='2000-01-01T00:00:00+00:00'")
    payload = {'course_id':'alg', 'learner_id':'alice'}
    code, result = cli_result(core, capsys, 'expire-reservations', payload)
    assert code == 0 and result['data']['ttl_days'] == 7
    assert result['data']['released'][0]['reason'] == 'expired'
    code, replay = cli_result(core, capsys, 'expire-reservations', payload)
    assert code == 0 and replay['idempotent_replay'] and replay['data'] == result['data']


@pytest.mark.parametrize('patch,mutation_id', [
    ({'learner_id': ''}, 'bad'), ({'learner_id': None}, 'bad'),
    ({'learner_id': 'bob'}, 'bad'), ({'assessment_id': None}, 'bad'),
    ({'assessment_id': []}, 'bad'), ({'reason': 'expired'}, 'bad'),
    ({'course_id': None}, 'bad'), ({}, None),
])
def test_cli_invalid_release(saved, capsys, patch, mutation_id):
    core, repo = saved
    payload = {'course_id':'alg', 'learner_id':'alice', 'assessment_id':'exam', **patch}
    code, result = cli_result(core, capsys, 'release-reservation', payload, mutation_id)
    assert code == 1 and result['error_code'] == 'VALIDATION_ERROR'
    assert repo.get('exam') is None


def test_cli_missing_owner_conflicts_and_sanitized_errors(saved, capsys, monkeypatch):
    core, repo = saved
    code, result = cli_result(core, capsys, 'expire-reservations', {'course_id':'alg'})
    assert code == 1 and result['error_code'] == 'VALIDATION_ERROR'
    for extra, patch in [(['-c', 'different'], {}), ([], {'request_id':'different'})]:
        code, result = cli_result(core, capsys, 'expire-reservations',
            {'course_id':'alg', 'learner_id':'alice', **patch}, extra=extra)
        assert code == 1 and result['error_code'] == 'CONFLICTING_PARAMETERS'
    def fail(*args, **kwargs):
        raise OSError('/private/question-text/secret')
    monkeypatch.setattr(CourseTutor, 'expire_reservations', fail)
    code, result = cli_result(core, capsys, 'expire-reservations', {'course_id':'alg', 'learner_id':'alice'})
    assert code == 1 and result['error_code'] == 'RESERVATION_FAILED'
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('raw', ['{', '[]', '{"learner_id":NaN}', '{"learner_id":1e999}'])
def test_cli_reservation_rejects_malformed_or_nonfinite_json(saved, capsys, raw):
    core, repo = saved
    with pytest.raises(SystemExit) as result:
        cli_main(['expire-reservations', '-w', str(core.workspace_root), '-j', raw])
    assert result.value.code == 1
    assert json.loads(capsys.readouterr().out)['error_code'] == 'INVALID_JSON_INPUT'
    assert repo.get('exam') is None


def test_cli_explicit_null_targets_unowned_only(saved, capsys):
    core, repo = saved
    with atomic_transaction(core.con):
        core.con.execute('UPDATE assessments SET learner_id=NULL WHERE id=?', ('exam',))
    code, result = cli_result(core, capsys, 'release-reservation',
        {'course_id':'alg', 'learner_id':None, 'assessment_id':'exam'})
    assert code == 0 and result['data']['learner_id'] is None
