"""Explicitly reviewed whole-PNG sources, bound to content identity and snapshots.

No external URLs, local path inputs, arbitrary original expansion or automatic
image approval. The instructor must inspect the entire asset and its question.
"""
import base64
import binascii
import hashlib
import json
from pathlib import Path
import struct
import zlib

from ..errors import ValidationError

MAX_BYTES = 2 * 1024 * 1024
PUBLIC_FIELDS = ('source_version_id', 'sha256', 'mime_type', 'original_filename',
                 'version_num', 'region', 'alt', 'caption')
BOUND_FIELDS = set(PUBLIC_FIELDS) | {'review_notes'}


def _png(raw):
    if len(raw) > MAX_BYTES or raw[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValidationError('Student assets require a PNG no larger than 2 MiB.')
    offset, first, image, ended = 8, True, False, False
    while offset + 12 <= len(raw):
        size = struct.unpack('>I', raw[offset:offset+4])[0]
        kind = raw[offset+4:offset+8]
        end = offset + 12 + size
        if end > len(raw) or zlib.crc32(raw[offset+4:end-4]) != struct.unpack('>I', raw[end-4:end])[0]:
            raise ValidationError('Student PNG chunk integrity check failed.')
        if first:
            if kind != b'IHDR' or size != 13:
                raise ValidationError('Student PNG requires an IHDR header.')
            width, height = struct.unpack('>II', raw[offset+8:offset+16])
            if not width or not height or width * height > 10_000_000:
                raise ValidationError('Student PNG dimensions exceed the reviewed image limit.')
            first = False
        if kind == b'acTL':
            raise ValidationError('Animated student assets are unsupported; use a reviewed static PNG.')
        image |= kind == b'IDAT'
        offset = end
        if kind == b'IEND':
            ended = True
            break
    if not ended or not image or offset != len(raw):
        raise ValidationError('Student PNG is incomplete or has trailing content.')


def bind_assets(con, course_id, assets):
    if not isinstance(assets, list) or len(assets) > 4:
        raise ValidationError('student_assets must be a list of at most four reviewed PNG sources.')
    result = []
    seen = set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) - BOUND_FIELDS:
            raise ValidationError('Student assets accept source_version_id and reviewed text only; paths and URLs are forbidden.')
        sid = asset.get('source_version_id')
        if not isinstance(sid, str) or not sid.strip() or sid in seen:
            raise ValidationError('Each student asset requires a distinct source_version_id.')
        seen.add(sid)
        source = con.execute('SELECT * FROM source_versions WHERE id=? AND course_id=?', (sid, course_id)).fetchone()
        if source is None or source['mime_type'] != 'image/png' or source['byte_size'] > MAX_BYTES:
            raise ValidationError('Student asset must be an existing PNG source version in this course, at most 2 MiB.')
        for name in ('alt', 'review_notes'):
            if not isinstance(asset.get(name), str) or not asset[name].strip():
                raise ValidationError('Student asset requires nonempty alt and private review_notes from actual visual inspection.')
        if not isinstance(asset.get('caption', ''), str):
            raise ValidationError('Student asset caption must be text.')
        bound = {'source_version_id': sid, 'sha256': source['file_hash'], 'mime_type': 'image/png',
                 'original_filename': Path(source['original_filename']).name, 'version_num': source['version_num'],
                 'region': 'whole_image', 'alt': asset['alt'], 'caption': asset.get('caption', ''),
                 'review_notes': asset['review_notes']}
        for name in ('sha256', 'mime_type', 'original_filename', 'version_num', 'region'):
            if name in asset and asset[name] != bound[name]:
                raise ValidationError('Student asset identity changed; review the exact source version again.')
        result.append(bound)
    return result


def snapshot_assets(con, course_id, rubric, file_store):
    bindings = bind_assets(con, course_id, rubric.get('student_assets', []))
    if bindings and file_store is None:
        raise ValidationError('Reviewed diagram snapshots require the workspace FileStore.')
    result = []
    for asset in bindings:
        row = con.execute('SELECT storage_relpath FROM source_versions WHERE id=?', (asset['source_version_id'],)).fetchone()
        try:
            with file_store.get_absolute_path(row['storage_relpath']).open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
        except OSError:
            raise ValidationError('Reviewed diagram is missing; restore the original source before assembly.') from None
        if hashlib.sha256(raw).hexdigest() != asset['sha256']:
            raise ValidationError('Reviewed diagram hash changed; restore the exact immutable source before assembly.')
        _png(raw)
        result.append({**{key: asset[key] for key in PUBLIC_FIELDS},
                       'data_base64': base64.b64encode(raw).decode('ascii')})
    return result


def student_assets(assets):
    """Allowlist and verify detached snapshot bytes, never resolve a path or URL."""
    if not isinstance(assets, list) or len(assets) > 4:
        raise ValidationError('Invalid student asset snapshot.')
    result = []
    for asset in assets:
        if not isinstance(asset, dict) or asset.get('mime_type') != 'image/png' or asset.get('region') != 'whole_image':
            raise ValidationError('Only reviewed whole-PNG snapshots may enter a student paper.')
        encoded = asset.get('data_base64')
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
            raise ValidationError('Invalid student PNG snapshot encoding.')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValidationError('Invalid student PNG snapshot encoding.') from None
        _png(raw)
        if hashlib.sha256(raw).hexdigest() != asset.get('sha256'):
            raise ValidationError('Student diagram snapshot hash changed.')
        public = {key: asset[key] for key in PUBLIC_FIELDS if key in asset}
        if any(not isinstance(public.get(key), str) for key in ('source_version_id', 'alt', 'caption', 'original_filename')):
            raise ValidationError('Student asset provenance and text must be strings.')
        public['original_filename'] = Path(public['original_filename']).name
        result.append({**public, 'data_base64': encoded})
    return result


def visual_context_hash(rubric):
    """Public visual inputs only; unrelated points/private review notes are excluded."""
    assets = rubric.get('student_assets', [])
    if not assets:
        return None
    projected = [{key: asset.get(key) for key in PUBLIC_FIELDS} for asset in assets]
    return hashlib.sha256(json.dumps(projected, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()
