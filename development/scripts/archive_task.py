# TL;DR: Log a completed, passing task and move its directory into the archive.
# Status: active; date: 2026-10-19.
"""Usage: python3 development/scripts/archive_task.py YYYYMMDD-slug."""
import argparse
import json
from pathlib import Path
import re
import shutil
from _devtools import ROOT, header, task_path, tldr, now, write_json


def archive(root, task_id):
    task = task_path(root, task_id)
    state = json.loads((task / 'status.json').read_text())
    review = (task / 'review.md').read_text()
    if state['task_id'] != task_id or state['state'] != 'done':
        raise ValueError('Only a matching task with state done can be archived')
    if not re.search(r'^Verdict: PASS\s*$', review, re.M):
        raise ValueError('Review must contain Verdict: PASS')
    destination = root / 'development/work/_archive' / task_id
    if destination.exists():
        raise ValueError(f'Archive exists: {destination}')
    logs = [root / 'development/docs/task-log.md'] + sorted((root / 'development/docs').glob('task-log-*.md'))
    if not any(f'`{task_id}`' in p.read_text() for p in logs if p.exists()):
        log = logs[-1]
        if len(log.read_text().splitlines()) + 2 > 150:
            log = root / f'development/docs/task-log-{len(logs):03d}.md'
            if log.exists():
                raise ValueError(f'Log rotation collision: {log}')
            log.write_text(header('Finished development tasks, continued.', 'active') +
                           '# Task log (continued)\n')
        paragraph = (f"\n`{task_id}` ({state['updated']}; based on {state['based_on_commit']}): "
                     f"{tldr(task / 'brief.md')} Review: {tldr(task / 'review.md')}\n")
        with log.open('a') as stream:
            stream.write(paragraph)
    state['ended_utc'] = state.get('ended_utc') or now()
    write_json(task / 'status.json', state)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(task), str(destination))
    from gen_doc_index import generate
    generate(root)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task_id')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(archive(args.root.resolve(), args.task_id))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'{exc}\n')
