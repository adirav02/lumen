"""Catalog boundaries retain real continuation and conservative visual locations."""
import uuid
import pytest
from course_tutor.api import LumenCore
from course_tutor.models import SourceSection
from course_tutor.storage.repositories import SourceRepository


@pytest.mark.parametrize('middle,quality,expected', [('\n\n', 'good', [1]),
    ('Continuation: x=7.', 'good', [1, 2]), ('', 'has_images', [1, 2])])
def test_boundary_whitespace_continuation_and_visual(tmp_path, middle, quality, expected):
    with LumenCore(tmp_path/'w') as c:
        c.create_course('C', course_id='c')
        source = tmp_path/'exam.txt'; source.write_text('Cover')
        sid = c.ingest_source('c', source, catalog_questions=False)['data']['source_version_id']
        repo = SourceRepository(c.con)
        for i, text, flag in [(1, 'Question 1: Calculate x.', 'good'), (2, middle, quality),
                              (3, '\n\nQuestion 2: Calculate y.', 'good')]:
            repo.add_source_section(SourceSection(id=str(uuid.uuid4()), source_version_id=sid, course_id='c',
                section_index=i, label=f'Page {i}', text=text, quality_flag=flag))
        c.catalog_exam_questions('c', sid)
        q = next(q for q in c.list_questions('c', sid)['questions'] if q['question_key']=='1')
        assert [s['section_index'] for s in q['source_spans']] == expected


def test_extractor_confirmed_empty_page_is_not_an_uncertain_visual(tmp_path):
    test_boundary_whitespace_continuation_and_visual(tmp_path, '\n', 'empty', [1])
