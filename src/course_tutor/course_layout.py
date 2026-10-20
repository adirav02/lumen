"""Resolve course artifact folders from registered import provenance, never scans."""

import hashlib
import json
from pathlib import Path
import re

from .errors import ValidationError


def directory_key(identifier):
    key = re.sub(r'[^A-Za-z0-9_-]', '-', identifier).strip('-')[:80]
    if key != identifier:
        key = (key or 'course')+'-'+hashlib.sha256(identifier.encode()).hexdigest()[:12]
    return key


def course_directory(con, workspace_root, course_id):
    rows = con.execute('''SELECT DISTINCT json_extract(metadata_json,'$.import_origin') origin
        FROM question_occurrences WHERE course_id=?
        AND json_type(metadata_json,'$.import_origin')='text' ''', (course_id,)).fetchall()
    roots = {Path(row['origin']).resolve() for row in rows}
    if len(roots) > 1:
        raise ValidationError('Course has multiple import directories; choose output_directory explicitly.')
    if roots:
        root = roots.pop()
        try:
            manifest = json.loads((root/'course.json').read_text())
        except (OSError, ValueError):
            raise ValidationError('Registered course directory is unavailable; choose output_directory explicitly.') from None
        if not isinstance(manifest, dict) or manifest.get('course_id') != course_id:
            raise ValidationError('Registered course directory belongs to a different course.')
        return root
    return Path(workspace_root).resolve()/'courses'/directory_key(course_id)


def test_directory(con, workspace_root, course_id, assessment_id):
    return course_directory(con, workspace_root, course_id)/'tests'/directory_key(assessment_id)
