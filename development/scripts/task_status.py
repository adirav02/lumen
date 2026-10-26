# TL;DR: Show task status.json fields only, without reading task documents.
# Status: active; date: 2026-10-19.
"""Compact development task inventory; archives/templates are excluded."""
import argparse
import json
from pathlib import Path
from _devtools import ROOT


REQUIRED_FIELDS = (
    'task_id', 'title', 'state', 'owner_role', 'host', 'model', 'updated',
    'based_on_commit', 'next_step', 'mode', 'reason',
)
STATES = {'planned', 'in_progress', 'review', 'done', 'blocked'}


def read_status(path):
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError('expected a JSON object')
        missing = [field for field in REQUIRED_FIELDS if field not in data]
        if missing:
            raise ValueError('missing required fields: ' + ', '.join(missing))
        if not isinstance(data['state'], str) or data['state'] not in STATES:
            raise ValueError('unknown state; expected ' + ', '.join(sorted(STATES)))
        if not isinstance(data['mode'], str) or data['mode'] not in {'solo', 'delegated'}:
            raise ValueError('unknown mode; expected solo or delegated')
        reason = data['reason']
        if not isinstance(reason, str) or not reason.strip() or len(reason.splitlines()) != 1:
            raise ValueError('reason must be a nonempty one-line string')
    except json.JSONDecodeError as exc:
        raise ValueError(f'{path}: invalid JSON: {exc.msg}') from None
    except (OSError, ValueError) as exc:
        raise ValueError(f'{path}: {exc}') from None
    return data


def table(root):
    rows = ['TASK | STATE | OWNER | HOST/MODEL | NEXT']
    for path in sorted((root / 'development/work').glob('*/status.json')):
        if path.parent.name.startswith('_'):
            continue
        data = read_status(path)
        clean = lambda value: ' '.join(str(value or '-').split())
        rows.append(' | '.join(clean(value) for value in (
            data['task_id'], data['state'], data['owner_role'],
            f"{data['host'] or '-'}/{data['model'] or '-'}", data['next_step'])))
    return '\n'.join(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(table(args.root.resolve()))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'{exc}\n')
