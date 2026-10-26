"""Public retirement operations preserve old artifact bytes, snapshots and receipts."""
import hashlib
import json
from pathlib import Path

import pytest

from course_tutor.errors import IdempotencyConflictError, ValidationError
from course_tutor.assessment import retirement
from test_exam_assembly import publish_core, selection_core, assemble, job


def test_cancel_marks_complete_export_and_job_superseded(publish_core):
    core = publish_core
    result = assemble(core)['data']
    original_job = job(core)
    directory = Path(result['pdf_path']).parent
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
    cancelled = core.release_reservation('alg', 'alice', result['assessment_id'], 'cancel', reason='cancelled')
    marker = json.loads((directory/'superseded.json').read_text())
    assert marker['status'] == 'superseded'
    assert marker['disposition']['reason'] == 'cancelled'
    assert '.assembly-owner.json' in marker['artifacts']
    assert before == {name: hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in before}
    assert job(core) == original_job
    replay = core.release_reservation('alg', 'alice', result['assessment_id'], 'cancel', reason='cancelled')
    assert replay['data'] == cancelled['data'] and replay['idempotent_replay']
    assert core.export_assessment(result['assessment_id'])['export_status'] == 'superseded'
    assert core.course_brief('alg', 'alice')['open_assessments'][0]['export_status'] == 'superseded'
    assert core.con.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0


def test_cancel_marker_failure_recovers_after_commit(publish_core, monkeypatch):
    core = publish_core
    result = assemble(core)['data']
    mark = retirement.mark_directory
    with monkeypatch.context() as patch:
        patch.setattr(retirement, 'mark_directory', lambda *a: (_ for _ in ()).throw(OSError('disk interruption')))
        with pytest.raises(OSError):
            core.release_reservation('alg', 'alice', result['assessment_id'], 'cancel', reason='cancelled')
    assert core.release_reservation('alg', 'alice', result['assessment_id'], 'cancel', reason='cancelled')['idempotent_replay']
    assert (Path(result['pdf_path']).parent/'superseded.json').is_file()


def test_replaced_custom_export_public_operation_and_replay(publish_core, tmp_path):
    core = publish_core
    old = assemble(core)['data']['assessment_id']
    custom = tmp_path/'custom'
    core.export_assessment(old, output_directory=custom)
    core.release_reservation('alg', 'alice', old, 'release')
    replacement = assemble(core, request='replacement')['data']['assessment_id']
    params = dict(course_id='alg', assessment_id=old, output_directory=custom,
                  replacement_assessment_id=replacement, request_id='replace-export')
    result = core.supersede_export(**params)
    assert result['data']['export_status'] == 'superseded'
    assert core.supersede_export(**params)['idempotent_replay']
    assert json.loads((custom/'superseded.json').read_text())['disposition']['replacement_assessment_id'] == replacement
    assert core.export_assessment(old, output_directory=custom)['export_status'] == 'superseded'
    with pytest.raises(IdempotencyConflictError):
        core.supersede_export(**{**params, 'replacement_assessment_id': None})


def test_supersede_wrong_directory_creates_no_receipt(publish_core, tmp_path):
    core = publish_core
    aid = assemble(core)['data']['assessment_id']
    other = tmp_path/'other'
    other.mkdir()
    (other/'presentation.json').write_text('{"assessment_id":"foreign"}')
    before = core.con.total_changes
    with pytest.raises(ValidationError, match='ownership'):
        core.supersede_export('alg', aid, other, 'bad')
    assert core.con.total_changes == before
    assert not (other/'superseded.json').exists()


def test_assembled_settings_are_saved_and_reexported(publish_core):
    core = publish_core
    bp = {'duration_minutes': 75, 'instructions': ['Answer every question.', 'Calculator permitted.'],
          'slots': [{'id': 's', 'count': 2, 'max_points': 12.5}]}
    result = assemble(core, blueprint=bp)['data']
    paper = core.assessment_paper(result['assessment_id'])
    assert paper['duration_minutes'] == 75 and paper['instructions'] == bp['instructions']
    html = (Path(result['pdf_path']).parent/'test.html').read_text()
    assert '75 minutes' in html and '25 total points' in html
    assert all(line in html for line in bp['instructions'])
    core.export_assessment(result['assessment_id'])
    assert core.assessment_paper(result['assessment_id']) == paper
