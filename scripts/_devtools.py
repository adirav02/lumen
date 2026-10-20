# TL;DR: Shared stdlib helpers for repository development scripts only.
# Status: active; date: 2026-10-19.
"""Small path, metadata and generated-file helpers; no application imports."""
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DATE = '2026-10-19'  # Scaffold/source review date, not a live validation claim.


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def commit(root):
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else 'unknown'


def header(summary, status='active'):
    return f'TL;DR: {summary}\nStatus: {status}; date: {DATE}.\n\n'


def task_path(root, name):
    if not re.fullmatch(r'\d{8}-[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError('Expected YYYYMMDD-lowercase-task-slug')
    path = root / 'work' / name
    if path.is_symlink():
        raise ValueError('Task directories must not be symlinks')
    return path


def tldr(path):
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith('TL;DR:'):
            found = [line.removeprefix('TL;DR:').strip()]
            for extra in lines[i+1:i+5]:
                if not extra.strip() or extra.startswith(('Status:', '#')):
                    break
                found.append(extra.strip())
            return ' '.join(found)
    raise ValueError(f'{path}: missing TL;DR')


def write_generated(path, text, check=False):
    """Never replace an unmarked, hand-maintained file."""
    old = path.read_text() if path.exists() else None
    if old == text:
        return True
    if check:
        print(f'OUTDATED {path}')
        return False
    if old is not None and 'GENERATED' not in '\n'.join(old.splitlines()[:15]):
        raise ValueError(f'Refusing to replace hand-maintained {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def write_json(path, data):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)
