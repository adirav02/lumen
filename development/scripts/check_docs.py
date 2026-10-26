# TL;DR: Check Markdown limits, headers and complete docs index coverage.
# Status: active; date: 2026-10-19.
"""Validate docs/, development/agents/ and development/work/ Markdown, including archived tasks."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import unquote
from _devtools import ROOT


def legacy_rgignore(legacy):
    return ("# GENERATED from development/scripts/legacy_docs.json; regenerate with:\n"
            "# python3 development/scripts/check_docs.py --write-rgignore\n"
            + ''.join(f'/{name}\n' for name in sorted(legacy)))


def check(root):
    errors = []
    baseline = root / 'development/scripts/legacy_docs.json'
    legacy = set(json.loads(baseline.read_text())['files']) if baseline.exists() else set()
    if legacy:
        ignore = root / '.rgignore'
        expected = legacy_rgignore(legacy)
        if not ignore.is_file() or ignore.read_text() != expected:
            errors.append('Missing or stale .rgignore; run development/scripts/check_docs.py --write-rgignore')
    for folder in ('docs', 'development/docs', 'development/agents', 'development/work'):
        for path in sorted((root / folder).rglob('*.md')):
            if '.tmp' in path.relative_to(root).parts:
                continue  # Verification clones and scratch files are never documentation.
            if path.relative_to(root).as_posix() in legacy:
                continue  # Existing contracts keep their original layout and links.
            lines = path.read_text().splitlines()
            limit = 60 if folder == 'development/agents' and path.stem in {
                'dev_explorer', 'dev_worker', 'dev_planner', 'dev_reviewer', 'manager'} else 150
            if len(lines) > limit:
                errors.append(f'{path}: {len(lines)} lines > {limit}')
            offset = 0
            if lines and lines[0] == '---':
                try:
                    offset = lines.index('---', 1) + 1
                except ValueError:
                    errors.append(f'{path}: unclosed frontmatter')
            body = lines[offset:]
            if not body or not body[0].startswith('TL;DR:'):
                errors.append(f'{path}: must start with TL;DR (after frontmatter)')
            statuses = [i for i, line in enumerate(body[:6]) if line.startswith('Status:')]
            if not statuses or not re.search(r'\d{4}-\d{2}-\d{2}|\{\{UPDATED\}\}', body[statuses[0]]):
                errors.append(f'{path}: missing early status/date line')
            if folder == 'development/work' and path.name == 'plan.md' and len(lines) > 120:
                errors.append(f'{path}: task plan exceeds 120 lines')
    for folder in ('docs', 'development/docs'):
        directory = root / folder
        index = directory / 'INDEX.md'
        if not index.is_file():
            errors.append(f'Missing {folder}/INDEX.md')
            continue
        links = {unquote(link.split('#', 1)[0]) for link in
                 re.findall(r'\]\(([^)]+)\)', index.read_text())}
        for path in directory.rglob('*'):
            if '.tmp' in path.relative_to(root).parts:
                continue
            if path.is_file() and path.relative_to(directory).as_posix() not in links:
                errors.append(f'INDEX misses {path.relative_to(root)}')
    if (root / 'development/scripts/roadmap_manifest.json').is_file():
        from check_roadmap import check as check_roadmap
        errors.extend(check_roadmap(root))
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--write-rgignore', action='store_true',
                        help='regenerate root-anchored legacy search exclusions')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.write_rgignore:
        legacy = json.loads((root / 'development/scripts/legacy_docs.json').read_text())['files']
        (root / '.rgignore').write_text(legacy_rgignore(legacy))
    errors = check(root)
    print('\n'.join(errors) if errors else 'Documentation checks passed')
    raise SystemExit(bool(errors))
