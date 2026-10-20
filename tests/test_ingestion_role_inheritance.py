"""Omitted roles preserve logical source identity across both ingestion APIs."""
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import ValidationError


@pytest.fixture(params=[False, True], ids=['core', 'pipeline'])
def ingestion(tmp_path, request):
    with LumenCore(tmp_path / 'workspace') as core:
        core.create_course('Test', course_id='c')
        path = tmp_path / 'lecture.txt'
        path.write_text('Original lecture content')
        ingest = (core.ingestion.ingest_file if request.param else
                  lambda *args, **kwargs: core.ingest_source(*args, **kwargs)['data'])
        yield core, path, ingest


def test_omitted_role_inherits_for_reuse_and_new_bytes(ingestion):
    core, path, ingest = ingestion
    first = ingest('c', path, logical_name='Lecture', role='lecture')
    reused = ingest('c', path, logical_name='Lecture')
    assert reused['source_version_id'] == first['source_version_id']
    assert reused['processing_fingerprint'] == first['processing_fingerprint']
    path.write_text('Revised lecture content')
    revised = ingest('c', path, logical_name='Lecture')
    assert revised['source_id'] == first['source_id']
    assert revised['version_num'] == 2
    assert core.ingestion.source_repo.get_source('c', 'Lecture').role == 'lecture'
    explicit = ingest('c', path, logical_name='Lecture', role='lecture')
    assert explicit['source_version_id'] == revised['source_version_id']


@pytest.mark.parametrize('different_role', ['reference', 'exam'])
def test_explicit_different_role_still_errors(ingestion, different_role):
    core, path, ingest = ingestion
    first = ingest('c', path, logical_name='Lecture', role='lecture')
    path.write_text('Revised lecture content')
    with pytest.raises(ValidationError, match='Existing logical source has a different role'):
        ingest('c', path, logical_name='Lecture', role=different_role)
    assert core.ingestion.source_repo.get_source('c', 'Lecture').role == 'lecture'
    assert core.con.execute('SELECT COUNT(*) FROM source_versions').fetchone()[0] == 1
    assert core.ingestion.source_repo.get_source_version(first['source_version_id']) is not None
    assert not list(core.file_store.staging_dir.iterdir())


def test_new_source_defaults_to_reference(ingestion):
    core, path, ingest = ingestion
    ingest('c', path)
    assert core.ingestion.source_repo.get_source('c', path.name).role == 'reference'
