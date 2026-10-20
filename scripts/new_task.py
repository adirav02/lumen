# TL;DR: Create a dated development task from the tracked template.
# Status: active; date: 2026-10-19.
"""Usage: python3 scripts/new_task.py <lowercase-slug>."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
from _devtools import ROOT, commit, now, task_path, write_json


def create_task(root, slug):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        raise ValueError('Use a lowercase slug with letters, digits and single hyphens')
    task_id = datetime.now(timezone.utc).strftime('%Y%m%d') + '-' + slug
    target = task_path(root, task_id)
    if target.exists():
        raise ValueError(f'Task already exists: {target}')
    updated, revision = now(), commit(root)
    shutil.copytree(root / 'work/_template', target)
    values = {'TASK_ID': task_id, 'TITLE': slug.replace('-', ' '),
              'UPDATED': updated, 'COMMIT': revision}
    for path in target.glob('*.md'):
        text = path.read_text()
        for key, value in values.items():
            text = text.replace('{{' + key + '}}', value)
        path.write_text(text)
    import json
    state = json.loads((target / 'status.json').read_text())
    state.update(task_id=task_id, title=values['TITLE'], updated=updated,
                 based_on_commit=revision, started_utc=updated, ended_utc=None)
    write_json(target / 'status.json', state)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('slug')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(create_task(args.root.resolve(), args.slug))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
