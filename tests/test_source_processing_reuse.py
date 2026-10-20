"""Synthetic regression coverage for whole-ingestion processing reuse."""
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import ValidationError
from course_tutor.ingestion.extractors import TextExtractor
from course_tutor.ingestion import processing


@pytest.fixture
def sample(tmp_path):
    core = LumenCore(tmp_path / 'workspace')
    core.create_course('Test', course_id='c')
    path = tmp_path / 'exam.txt'
    path.write_text('Question 1\nWhat is 2 + 2?\nA. 4\nB. 5\n')
    yield core, path
    core.close()


@pytest.mark.parametrize('direct', [False, True])
def test_exact_reuse_skips_extractor_builder_and_catalog(sample, monkeypatch, direct):
    core, path = sample
    ingest = core.ingestion.ingest_file if direct else lambda *a, **kw: core.ingest_source(*a, **kw)['data']
    first = ingest('c', path, role='exam')
    def forbidden(*args, **kwargs):
        raise AssertionError('Expensive processing was repeated')
    monkeypatch.setattr(TextExtractor, 'extract', forbidden)
    monkeypatch.setattr('course_tutor.ingestion.pipeline.parse_structured_unit_blocks', forbidden)
    monkeypatch.setattr('course_tutor.questions.catalog.QuestionCatalog.catalog', forbidden)
    second = ingest('c', path, role='exam')
    assert second['source_version_id'] == first['source_version_id']
    assert second['processing_fingerprint'] == first['processing_fingerprint']
    assert second['status'] == 'existing_content_reused'
    assert not list(core.file_store.staging_dir.iterdir())


def test_configuration_and_processor_changes_create_versions(sample, monkeypatch):
    core, path = sample
    unit = {'kind': 'definition', 'title': 'A', 'content': 'one'}
    def ingest(**kwargs):
        return core.ingest_source('c', path, **kwargs)['data']
    first = ingest(structured_units=[unit])
    equivalent = ingest(structured_units=[dict(reversed(list(unit.items())))])
    assert equivalent['source_version_id'] == first['source_version_id']
    changed = ingest(structured_units=[{**unit, 'content': 'two'}])
    assert changed['source_version_id'] != first['source_version_id']
    monkeypatch.setattr(processing, 'UNIT_BUILDER_VERSION', 'next')
    upgraded = ingest(structured_units=[unit])
    assert upgraded['source_version_id'] not in {first['source_version_id'], changed['source_version_id']}
    assert core.con.execute('SELECT COUNT(*) FROM source_processing').fetchone()[0] == 3


def test_explicit_id_collision_rolls_back(sample):
    core, path = sample
    unit = {'id': 'fixed', 'kind': 'definition', 'title': 'A', 'content': 'one'}
    first = core.ingest_source('c', path, structured_units=[unit])['data']
    with pytest.raises(ValidationError, match='ID already exists'):
        core.ingest_source('c', path, structured_units=[{**unit, 'content': 'changed'}], request_id='collision')
    assert core.con.execute('SELECT COUNT(*) FROM source_versions').fetchone()[0] == 1
    assert core.con.execute('SELECT COUNT(*) FROM source_processing').fetchone()[0] == 1
    assert core.knowledge_repo.get_unit('fixed').content == 'one'
    assert not list(core.file_store.staging_dir.iterdir())


def test_role_conflict_and_course_logical_scope(sample):
    core, path = sample
    first = core.ingest_source('c', path)['data']
    with pytest.raises(ValidationError, match='different role'):
        core.ingest_source('c', path, role='exam')
    other = core.ingest_source('c', path, logical_name='another')['data']
    core.create_course('Other', course_id='other')
    foreign = core.ingest_source('other', path)['data']
    assert len({first['source_version_id'], other['source_version_id'], foreign['source_version_id']}) == 3


def test_unknown_and_legacy_identity_reprocess(sample, monkeypatch):
    core, path = sample
    first = core.ingest_source('c', path)['data']
    core.con.execute('DELETE FROM source_processing')
    core.con.commit()
    second = core.ingest_source('c', path)['data']
    assert first['source_version_id'] != second['source_version_id']
    monkeypatch.setitem(processing.EXTRACTOR_VERSIONS, TextExtractor, None)
    third = core.ingest_source('c', path)['data']
    fourth = core.ingest_source('c', path)['data']
    assert third['source_version_id'] != fourth['source_version_id']


def test_alias_requires_equal_processing_identity(sample, monkeypatch):
    core, path = sample
    first = core.ingest_source('c', path, role='exam', logical_name='one')['data']
    second = core.ingest_source('c', path, role='exam', logical_name='two')['data']
    assert second['question_catalog']['canonical_source_version_id'] == first['source_version_id']
    monkeypatch.setattr(processing, 'CATALOG_VERSION', 'next')
    changed = core.ingest_source('c', path, role='exam', logical_name='three')['data']
    assert not changed['question_catalog'].get('duplicate_upload')


def test_catalog_flag_and_unresolved_topic_are_configuration(sample):
    core, path = sample
    first = core.ingest_source('c', path, role='exam')['data']
    no_catalog = core.ingest_source('c', path, role='exam', catalog_questions=False)['data']
    unresolved = core.ingest_source('c', path, role='exam', topic_slugs=['missing'])['data']
    assert len({first['source_version_id'], no_catalog['source_version_id'], unresolved['source_version_id']}) == 3
    assert no_catalog['question_catalog'] is None


def test_resolved_topic_mapping_changes_identity(sample):
    core, path = sample
    first = core.ingest_source('c', path, topic_slugs=['new'])['data']
    core.create_topic('c', 'New topic', slug='new')
    second = core.ingest_source('c', path, topic_slugs=['new'])['data']
    assert first['processing_fingerprint'] != second['processing_fingerprint']
    assert first['source_version_id'] != second['source_version_id']


def test_dependency_change_and_missing_dependency_miss(sample, monkeypatch):
    from pypdf import PdfWriter
    core, path = sample
    pdf = path.with_suffix('.pdf')
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    first = core.ingest_source('c', pdf)['data']
    original_version = processing.metadata.version
    monkeypatch.setattr(processing.metadata, 'version', lambda name: 'future' if name == 'pypdf' else original_version(name))
    second = core.ingest_source('c', pdf)['data']
    assert first['source_version_id'] != second['source_version_id']
    def missing(name):
        raise processing.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(processing.metadata, 'version', missing)
    third = core.ingest_source('c', pdf)['data']
    fourth = core.ingest_source('c', pdf)['data']
    assert third['source_version_id'] != fourth['source_version_id']


def test_pdf_inline_image_pillow_restoration_reprocesses(sample, monkeypatch):
    """Installed metadata alone cannot make degraded image detection reusable."""
    import builtins
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    from course_tutor.ingestion.extractors import PDFExtractor

    core, path = sample
    pdf = path.with_suffix('.pdf')
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = DecodedStreamObject()
    stream.set_data(b'q 10 0 0 10 0 0 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x00\nEI Q')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(pdf)
    original_import = builtins.__import__
    def missing_pillow(name, *args, **kwargs):
        if name == 'PIL' or name.startswith('PIL.'):
            raise ImportError('Pillow unavailable despite installed metadata')
        return original_import(name, *args, **kwargs)
    with monkeypatch.context() as unavailable:
        unavailable.setattr(builtins, '__import__', missing_pillow)
        first = core.ingest_source('c', pdf)['data']
        assert first['extraction_status'] == 'empty'
        assert first['processing_descriptor']['dependencies']['Pillow']
        assert first['processing_descriptor']['dependency_availability']['Pillow'] is False
        metadata = core.ingestion.source_repo.get_source_processing('c', first['source_version_id'])
        assert metadata['reuse_eligible'] == 0
    assert PDFExtractor().extract(pdf)[0].quality_flag == 'uncertain_scanned'
    restored = core.ingest_source('c', pdf)['data']
    assert restored['extraction_status'] == 'uncertain'
    assert restored['source_version_id'] != first['source_version_id']
    assert restored['processing_fingerprint'] != first['processing_fingerprint']
    assert core.get_extracted_sections(restored['source_version_id'])[0]['quality_flag'] == 'uncertain_scanned'
    assert core.get_extracted_sections(first['source_version_id'])[0]['quality_flag'] == 'empty'
    again = core.ingest_source('c', pdf)['data']
    assert again['source_version_id'] == restored['source_version_id']
    assert again['status'] == 'existing_content_reused'
    with monkeypatch.context() as unavailable_again:
        unavailable_again.setattr(builtins, '__import__', missing_pillow)
        degraded = core.ingest_source('c', pdf)['data']
        assert degraded['source_version_id'] != restored['source_version_id']
        assert degraded['status'] == 'success'
        assert degraded['processing_descriptor']['dependency_availability']['Pillow'] is False
    original_version = processing.metadata.version
    monkeypatch.setattr(processing.metadata, 'version', lambda name: 'future-pillow' if name == 'Pillow' else original_version(name))
    upgraded = core.ingest_source('c', pdf)['data']
    assert upgraded['source_version_id'] != restored['source_version_id']
    assert upgraded['processing_fingerprint'] != restored['processing_fingerprint']
    assert upgraded['extraction_status'] == 'uncertain'
