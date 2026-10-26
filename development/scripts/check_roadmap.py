# TL;DR: Verify verbatim roadmap preservation against its original Git blob identity.
# Status: active; date: 2026-10-19.
"""Check ordered payload bytes without requiring history in a shallow checkout."""
import argparse
import hashlib
import json
from pathlib import Path
from _devtools import ROOT


def check(root):
    errors = []
    try:
        manifest = json.loads((root / 'development/scripts/roadmap_manifest.json').read_text())
        folder = root / 'development/docs/roadmap'
        parts = manifest['parts']
        actual = sorted(path.name for path in folder.glob('[0-9]*.md'))
        if parts != actual or len(parts) != len(set(parts)):
            errors.append('Roadmap parts missing, extra, duplicated or out of order')
        payloads = []
        for name in parts:
            if Path(name).name != name:
                raise ValueError('Part name must be a basename')
            lines = (folder / name).read_bytes().splitlines(keepends=True)
            if len(lines) >= 150:
                errors.append(f'{name}: must have fewer than 150 lines')
            if (len(lines) < 4 or not lines[0].startswith(b'TL;DR:')
                    or not lines[1].startswith(b'Status:') or lines[2] != b'\n'
                    or lines[3] != b'<!-- ROADMAP:ORIGINAL -->\n'):
                raise ValueError(f'{name}: invalid four-line preservation header')
            payloads.append(b''.join(lines[4:]))
        original = b''.join(payloads)
        if hashlib.sha256(original).hexdigest() != manifest['original_sha256']:
            errors.append('Concatenated roadmap differs from original SHA-256')
        blob = b'blob ' + str(len(original)).encode() + b'\0' + original
        if hashlib.sha1(blob).hexdigest() != manifest['original_git_blob']:
            errors.append('Concatenated roadmap differs from original Git blob')
        if len(original.splitlines()) != manifest['original_lines']:
            errors.append('Concatenated roadmap differs from original line count')
        if len((folder / 'INDEX.md').read_bytes().splitlines()) > 60:
            errors.append('Roadmap INDEX exceeds 60 lines')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f'Roadmap preservation check failed: {exc}')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    errors = check(args.root.resolve())
    print('\n'.join(errors) if errors else 'Roadmap preservation checks passed')
    raise SystemExit(bool(errors))
