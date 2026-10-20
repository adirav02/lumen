# TL;DR: Scan Git history without displaying sensitive matching text.
# Status: active; date: 2026-10-20.
"""History plumbing for the public hygiene checker."""
import ast
import re


def scan_history(root, git, paths, matches, report, private, strict):
    # NUL-delimited paths retain whitespace, tabs, and newlines exactly.
    revision = ''
    log = git(root, 'log', '--all', '-m', '--root', '--no-renames', '--name-only',
              '-z', '--format=%x00%H')
    for field in log.split(b'\0'):
        if not field:
            continue
        value = field.decode('utf-8', 'surrogateescape')
        if re.fullmatch(r'[0-9a-f]{40,64}', value):
            revision = value
        else:
            paths('history', revision, value.removeprefix('\n'))
    patch = git(root, 'log', '--all', '-m', '-p', '--root', '--no-renames',
                '--no-ext-diff', '--no-textconv', '--format=%x00%H')
    for section in patch.split(b'\0')[1:]:
        lines = section.decode('utf-8', 'replace').splitlines()
        revision, path, in_hunk = lines[0], '(commit)', False
        for line in lines[1:]:
            if line.startswith('diff --git '):
                in_hunk = False
                path = line.split(' b/', 1)[-1]
                if path.startswith('"'):
                    path = '(quoted path)'
            elif line.startswith('@@'):
                in_hunk = True
            elif not in_hunk and line.startswith(('--- ', '+++ ')):
                name = line[4:]
                if name.startswith(chr(34)):
                    name = ast.literal_eval(name)
                if name != '/dev/null':
                    path = name[2:]
            elif in_hunk and line.startswith(('+', '-', ' ')):
                matches('history', 'blocked_text', revision, path, line[1:])
    # Include authors, committers, messages and annotated tag metadata.
    objects = [(oid, 'commit') for oid in
               git(root, 'log', '--all', '--format=%H').decode().splitlines()]
    for row in git(root, 'for-each-ref', '--format=%(objecttype) %(objectname)').decode().splitlines():
        kind, oid = row.split()
        if kind == 'tag':
            objects.append((oid, kind))
    for oid, kind in objects:
        text = git(root, 'cat-file', kind, oid).decode('utf-8', 'replace')
        matches('history', 'blocked_metadata', oid, f'({kind} metadata)', text)
        if strict and private.search(text):
            report('history', 'private_metadata', oid, f'({kind} metadata)')
