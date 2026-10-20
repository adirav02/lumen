"""Synthetic identity, completion and migration boundary checks."""
from dataclasses import replace

import pytest

from course_tutor.ingestion import processing
from course_tutor.models import Course
from course_tutor.errors import CrossCourseViolationError, ValidationError
from course_tutor.storage.db import get_connection, atomic_transaction
from course_tutor.storage import migrations
from course_tutor.storage.repositories import CourseRepository, SourceRepository


def identity(**configuration):
    return processing.processing_identity('notes.txt', processing.snapshot_configuration(**configuration))


def test_canonical_snapshot_detaches_and_preserves_all_unit_fields():
    units = [{"id": "fixed", "content": "x", "metadata": {"b": 2, "a": 1}}]
    config = processing.snapshot_configuration(structured_units=units, topic_slugs=['z', 'a', 'z'], resolved_topics={'a': 'topic-a'})
    first = processing.processing_identity('notes.txt', config)
    reordered = [{"metadata": {"a": 1, "b": 2}, "content": "x", "id": "fixed"}]
    assert first == identity(structured_units=reordered, topic_slugs=['a', 'z'], resolved_topics={'a': 'topic-a'})
    units[0]['content'] = 'mutated'
    assert config['structured_units'][0]['content'] == 'x'
    assert config['resolved_topics'] == {'a': 'topic-a', 'z': None}
    assert identity() == identity(structured_units=[], topic_slugs=[])
    assert identity(structured_units=[{'content': 'a'}, {'content': 'b'}]) != identity(structured_units=[{'content': 'b'}, {'content': 'a'}])


@pytest.mark.parametrize('config', [
    {'role': 'exam'}, {'catalog_questions': False},
    {'structured_units': [{'id': 'specific', 'content': 'text'}]},
    {'topic_slugs': ['missing']},
    {'topic_slugs': ['a'], 'resolved_topics': {'a': 'id-a'}},
])
def test_effective_configuration_changes_identity(config):
    assert identity().fingerprint != identity(**config).fingerprint


def test_versions_and_dependencies_and_unknown_implementations(monkeypatch):
    original = identity()
    monkeypatch.setattr(processing, 'UNIT_BUILDER_VERSION', '2')
    assert identity().fingerprint != original.fingerprint
    unit_changed = identity()
    monkeypatch.setattr(processing, 'CATALOG_VERSION', '2')
    assert identity().fingerprint != unit_changed.fingerprint
    catalog_changed = identity()
    monkeypatch.setattr(processing.platform, 'python_version', lambda: '99.1.0')
    assert identity().fingerprint != catalog_changed.fingerprint
    monkeypatch.setattr(processing.metadata, 'version', lambda package: '1.0')
    pdf = processing.processing_identity('x.pdf', {})
    assert pdf.reuse_eligible
    monkeypatch.setattr(processing.metadata, 'version', lambda package: '2.0')
    assert pdf.fingerprint != processing.processing_identity('x.pdf', {}).fingerprint
    def missing(package):
        raise processing.metadata.PackageNotFoundError(package)
    monkeypatch.setattr(processing.metadata, 'version', missing)
    assert not processing.processing_identity('x.pdf', {}).reuse_eligible
    class Custom(processing.TextExtractor):
        pass
    assert not processing.processing_identity('x.txt', {}, Custom()).reuse_eligible
    monkeypatch.setitem(processing.EXTRACTOR_VERSIONS, processing.TextExtractor, '2')
    assert identity().fingerprint != original.fingerprint


@pytest.mark.parametrize('suffix', ['txt', 'pdf', 'pptx', 'docx', 'png', 'unknown'])
def test_builtin_descriptors(suffix, monkeypatch):
    monkeypatch.setattr(processing.metadata, 'version', lambda package: '1.0')
    result = processing.processing_identity('x.' + suffix, {})
    assert result.reuse_eligible
    assert result.descriptor['suffix'] == '.' + suffix
    if suffix == 'pptx':
        assert result.descriptor['dependencies'] == {'lxml': '1.0', 'python-pptx': '1.0'}


def make_version(repo, course='a', name='notes', status='extracted', hash='a' * 64):
    source = repo.get_or_create_source(course, name)
    return repo.add_source_version(source.id, course, hash, 'notes.txt', 'text/plain', 4, 'originals/notes.txt', status)


@pytest.fixture
def database():
    con = get_connection(':memory:')
    migrations.run_migrations(con)
    courses = CourseRepository(con)
    courses.create_course(Course(id='a', name='A'))
    courses.create_course(Course(id='b', name='B'))
    yield con, SourceRepository(con)
    con.close()


def test_completed_lookup_scope_and_transaction_rollback(database):
    con, repo = database
    known = identity()
    with atomic_transaction(con):
        version = make_version(repo)
        repo.record_source_processing('a', version.id, known)
    assert repo.find_reusable_version('a', 'notes', 'a' * 64, known.fingerprint).id == version.id
    assert repo.get_source('a', 'notes').id == version.source_id
    assert repo.get_source('b', 'notes') is None
    for course, name, file_hash, fingerprint in [
        ('b', 'notes', 'a' * 64, known.fingerprint),
        ('a', 'other', 'a' * 64, known.fingerprint),
        ('a', 'notes', 'b' * 64, known.fingerprint),
        ('a', 'notes', 'a' * 64, 'b' * 64),
    ]:
        assert repo.find_reusable_version(course, name, file_hash, fingerprint) is None
    assert repo.get_source_processing('b', version.id) is None
    with pytest.raises(ValidationError):
        repo.record_source_processing('a', version.id, known)
    with atomic_transaction(con):
        with pytest.raises(CrossCourseViolationError):
            repo.record_source_processing('b', version.id, known)
    with pytest.raises(RuntimeError), atomic_transaction(con):
        aborted = make_version(repo, name='aborted')
        repo.record_source_processing('a', aborted.id, known)
        raise RuntimeError('index failure')
    assert repo.get_source_processing('a', aborted.id) is None
    assert repo.get_source_version(aborted.id) is None
    assert not con.execute('PRAGMA foreign_key_check').fetchall()


def test_pending_failed_unknown_and_legacy_never_reused(database):
    con, repo = database
    known = identity()
    for status in ('pending', 'failed'):
        with atomic_transaction(con):
            version = make_version(repo, name=status, status=status)
            with pytest.raises(ValidationError):
                repo.record_source_processing('a', version.id, known)
        assert repo.find_reusable_version('a', status, 'a' * 64, known.fingerprint) is None
    with atomic_transaction(con):
        unknown = make_version(repo, name='unknown')
        repo.record_source_processing('a', unknown.id, replace(known, reuse_eligible=False))
        make_version(repo, name='legacy')
    assert repo.find_reusable_version('a', 'unknown', 'a' * 64, known.fingerprint) is None
    assert repo.find_reusable_version('a', 'legacy', 'a' * 64, known.fingerprint) is None


def test_v12_upgrade_retains_every_existing_row_and_reruns(monkeypatch):
    con = get_connection(':memory:')
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', [m for m in all_migrations if m[0] <= 12])
    migrations.run_migrations(con)
    CourseRepository(con).create_course(Course(id='a', name='A'))
    repo = SourceRepository(con)
    with atomic_transaction(con):
        legacy = make_version(repo)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%_fts%' AND name != 'schema_migrations'")]
    snapshots = {table: [tuple(row) for row in con.execute('SELECT * FROM "' + table + '"')] for table in tables}
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations)
    migrations.run_migrations(con)
    migrations.run_migrations(con)
    for table, rows in snapshots.items():
        assert [tuple(row) for row in con.execute('SELECT * FROM "' + table + '"')] == rows
    assert repo.get_source_version(legacy.id).extraction_status == 'extracted'
    assert repo.get_source_processing('a', legacy.id) is None
    assert not con.execute('PRAGMA foreign_key_check').fetchall()
    assert con.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 13
    with atomic_transaction(con):
        fresh = make_version(repo)
        repo.record_source_processing('a', fresh.id, identity())
    assert repo.get_source_processing('a', fresh.id)['reuse_eligible'] == 1
    con.close()


@pytest.mark.parametrize('status', ['extracted', 'uncertain', 'empty', 'unsupported'])
def test_all_completed_states_reusable_without_review_claim(database, status):
    con, repo = database
    with atomic_transaction(con):
        version = make_version(repo, status=status)
        repo.record_source_processing('a', version.id, identity())
    assert repo.find_reusable_version('a', 'notes', 'a' * 64, identity().fingerprint).extraction_status == status


def test_metadata_fingerprint_must_match_and_is_immutable(database):
    import sqlite3
    con, repo = database
    with atomic_transaction(con):
        version = make_version(repo)
        with pytest.raises(ValidationError):
            repo.record_source_processing('a', version.id, replace(identity(), fingerprint='0' * 64))
        repo.record_source_processing('a', version.id, identity())
        with pytest.raises(sqlite3.IntegrityError):
            repo.record_source_processing('a', version.id, identity(role='exam'))
    assert repo.get_source_processing('a', version.id)['processing_fingerprint'] == identity().fingerprint


def test_pdf_pillow_version_and_runtime_availability(monkeypatch):
    import builtins
    monkeypatch.setattr(processing.metadata, 'version', lambda name: '1.0')
    first = processing.processing_identity('x.pdf', {})
    assert first.reuse_eligible
    assert first.descriptor['dependencies']['Pillow'] == '1.0'
    assert first.descriptor['dependency_availability']['Pillow'] is True
    monkeypatch.setattr(processing.metadata, 'version', lambda name: '2.0' if name == 'Pillow' else '1.0')
    upgraded = processing.processing_identity('x.pdf', {})
    assert upgraded.fingerprint != first.fingerprint
    original_import = builtins.__import__
    def missing_pillow(name, *args, **kwargs):
        if name == 'PIL' or name.startswith('PIL.'):
            raise ImportError('Pillow unavailable despite installed metadata')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing_pillow)
    unavailable = processing.processing_identity('x.pdf', {})
    assert not unavailable.reuse_eligible
    assert unavailable.descriptor['dependencies']['Pillow'] == '2.0'
    assert unavailable.descriptor['dependency_availability']['Pillow'] is False
    assert unavailable.fingerprint != upgraded.fingerprint
