# TL;DR: Wheel-only runtime assertions; copied outside the checkout by smoke_installed.py.
# Status: active; date: 2026-10-26.
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import subprocess
import sys


def main(checkout, source):
    import course_tutor
    import lumen
    checkout, source = Path(checkout).resolve(), Path(source).resolve()
    prefix = Path(sys.prefix).resolve()
    assert sys.prefix != sys.base_prefix, 'A dedicated virtual environment is required'
    for module in (course_tutor, lumen):
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(prefix) and not path.is_relative_to(checkout), path
    dist = distribution('lumen')
    direct = json.loads(dist.read_text('direct_url.json') or '{}')
    assert not direct.get('dir_info', {}).get('editable'), direct
    assert source.is_file() and not source.is_relative_to(checkout)
    assert not Path.cwd().resolve().is_relative_to(checkout)
    workspace = Path.cwd() / 'workspace'
    scripts = Path(sys.executable).parent

    def cli(op, payload=None, *, ws=workspace, entry='lumen', course=True):
        executable = scripts / (entry + ('.exe' if sys.platform == 'win32' else ''))
        args = [str(executable), op, '-w', str(ws)]
        if course:
            args += ['-c', 'wheel-probability']
        result = subprocess.run(args, input=json.dumps(payload or {}), capture_output=True,
                                text=True, timeout=30, check=False)
        assert result.returncode == 0, (op, result.stdout, result.stderr)
        envelope = json.loads(result.stdout)
        assert envelope['status'] == 'success', envelope
        return envelope['data']

    for entry in ('lumen', 'course-tutor'):
        caps = cli('capabilities', entry=entry, course=False)
        assert caps['runtime']['fts5_supported'] is True
    assert not (workspace / 'lumen.db').exists(), 'Capabilities must not initialize learner state'
    created = cli('create-course', {'name': 'Wheel Probability', 'request_id': 'create'})
    assert cli('create-course', {'name': 'Wheel Probability', 'request_id': 'create'}) == created
    original = source.read_bytes()
    ingested = cli('ingest-source', {'file_path': str(source), 'role': 'lecture'})
    assert ingested['file_hash'] == hashlib.sha256(original).hexdigest()
    assert ingested['extraction_status'] == 'extracted'
    results = cli('search', {'query': "Bayes' Theorem"})['results']
    hit = next(hit for hit in results if hit['title'] == "Bayes' Theorem")
    read = cli('read-units', {'unit_ids': [hit['unit_id']], 'expand_dependencies': True})
    unit = next(u for u in read['units'] if u['id'] == hit['unit_id'])
    assert 'P(B) > 0' in unit['assumptions']
    assert 'P(B|A)' in unit['content']
    assert unit['provenance'][0]['source_version_id'] == ingested['source_version_id']
    assert read['closure_complete'] is True
    assert read['total_units_returned'] == 3  # Bayes and its two maintained prerequisites
    region = cli('read-source-region', {'source_version_id': ingested['source_version_id']})
    assert region['hash_verified'] is True
    assert Path(region['absolute_path']).read_bytes() == original
    archive = Path.cwd() / 'snapshot.zip'
    assert cli('backup', {'output_path': str(archive)})['source_count'] == 1
    restored = Path.cwd() / 'restored'
    receipt = cli('restore', {'backup_path': str(archive), 'target_workspace': str(restored)}, course=False)
    assert receipt['sources_verified'] == 1 and receipt['courses'] == ['wheel-probability']
    assert cli('course-brief', ws=restored)['course']['name'] == 'Wheel Probability'
    assert cli('read-units', {'unit_ids': [hit['unit_id']], 'expand_dependencies': True}, ws=restored) == read
    region = cli('read-source-region', {'source_version_id': ingested['source_version_id']}, ws=restored)
    assert region['hash_verified'] is True and Path(region['absolute_path']).read_bytes() == original
    assert source.read_bytes() == original


if __name__ == '__main__':
    main(*sys.argv[1:])
