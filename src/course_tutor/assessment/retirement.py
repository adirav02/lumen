"""Mark owned exports superseded while preserving immutable artifacts and jobs."""
import json
import os
from pathlib import Path
import uuid

from ..errors import ValidationError
from ..storage.repositories import AssemblyRepository, ReservationRepository


def validate_directory(directory, assessment_id):
    directory = Path(directory)
    manifest = directory / 'presentation.json'
    marker = directory / '.assembly-owner.json'
    if directory.is_symlink() or manifest.is_symlink() or marker.is_symlink():
        raise ValidationError('Cannot retire an export through symlinks.')
    owner = manifest if manifest.is_file() else marker
    if not owner.is_file() or json.loads(owner.read_text()).get('assessment_id') != assessment_id:
        raise ValidationError('Cannot retire an export without matching ownership metadata.')


def mark_directory(directory, assessment_id, disposition):
    directory = Path(directory)
    if not directory.exists():
        return
    validate_directory(directory, assessment_id)
    target = directory / 'superseded.json'
    if target.is_file() and not target.is_symlink():
        prior = json.loads(target.read_text())
        if prior.get('assessment_id') == assessment_id:
            disposition = {**prior.get('disposition', {}), **disposition}
    content = json.dumps({'assessment_id': assessment_id, 'status': 'superseded',
                          'artifacts': ['test.pdf', 'test.html', 'presentation.json', '.assembly-owner.json'],
                          'disposition': disposition}, sort_keys=True, indent=2)+'\n'
    if target.is_file() and not target.is_symlink() and target.read_text() == content:
        return
    temporary = directory / ('.superseded-'+uuid.uuid4().hex)
    try:
        temporary.write_text(content)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def reconcile(core, course, assessment_id):
    disposition = ReservationRepository(core.con).get(assessment_id)
    if disposition is None:
        return
    from ..course_layout import test_directory
    job = AssemblyRepository(core.con).get_by_assessment(assessment_id)
    directories = {test_directory(core.con, core.workspace_root, course, assessment_id)}
    if job:
        directories.update((Path(job['final_path']), Path(job['staging_path'])))
    for directory in directories:
        if not directory.exists():
            continue
        try:
            validate_directory(directory, assessment_id)
        except ValidationError:
            continue  # Foreign/ambiguous files are never adopted or modified.
        mark_directory(directory, assessment_id, disposition)


def export_status(core, assessment_id, output=None):
    disposition = ReservationRepository(core.con).get(assessment_id)
    if disposition:
        if output:
            mark_directory(output, assessment_id, disposition)
        return {'export_status': 'superseded', 'disposition': disposition}
    if output:
        marker = Path(output) / 'superseded.json'
        if marker.is_file():
            record = json.loads(marker.read_text())
            if record.get('assessment_id') == assessment_id:
                return {'export_status': 'superseded', 'disposition': record['disposition']}
    return {'export_status': 'current'}
