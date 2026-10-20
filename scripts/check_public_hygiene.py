#!/usr/bin/env python3
# TL;DR: Deterministic public-data checks; sensitive matches are never displayed.
# Status: active; date: 2026-10-20.
"""Scan HEAD, changed/untracked public files, and optionally all reachable history. Stdlib only."""
import argparse
import os
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
from _public_hygiene_history import scan_history

FORBIDDEN = 'examples/real_course_test/courses/'
EXTENSIONS = {'.docx', '.doc', '.xlsx', '.zip'}
HEBREW = re.compile(r'[\u05d0-\u05ea]+(?:[\u0591-\u05c7]*[\u05d0-\u05ea]*)*')
PRIVATE = re.compile(r'/' + r'home/[^/\s]+/|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.quotepath=false', *args], cwd=root, stderr=subprocess.PIPE)


def scan(root, history=False, strict=False, blocklist=None):
    counts = Counter()
    terms_file = blocklist if blocklist is not None else root / '.local-blocklist.txt'
    if not terms_file.is_file():
        print('gate missing_blocklist: .local-blocklist.txt')
        return 1
    terms = [s.strip().casefold() for s in terms_file.read_text(encoding='utf-8').splitlines()
             if s.strip()]
    seen = set()

    def safe(path):
        # A blocked term may itself occur in a path; redact it there too.
        if any(term in path.casefold() for term in terms):
            return '[redacted path]'
        return json.dumps(path, ensure_ascii=True)[1:-1]

    def report(scope, category, revision, path, number=None, line=None):
        key = (scope, category, revision, path, number, line)
        if key in seen:
            return
        seen.add(key)
        counts[f'{scope}.{category}'] += 1
        if line is not None:
            print(f'{scope}.{category} {safe(path)}:{line}')
        else:
            suffix = f' term #{number}' if number else ''
            print(f'{scope}.{category} {revision} {safe(path)}{suffix}')

    def matches(scope, category, revision, path, text):
        for number, term in enumerate(terms, 1):
            if term in text.casefold():
                report(scope, category, revision, path, number)

    def paths(scope, revision, path):
        if path.startswith(FORBIDDEN):
            report(scope, 'course_path', revision, path)
        if Path(path).suffix.lower() in EXTENSIONS:
            report(scope, 'extension', revision, path)
        matches(scope, 'blocked_path', revision, path, path)

    try:
        head = git(root, 'rev-parse', '--verify', 'HEAD').decode().strip()
    except subprocess.CalledProcessError:
        head = None
    snapshots = []
    originals = {}
    tree = git(root, 'ls-tree', '-rz', '--full-tree', 'HEAD') if head else b''
    for record in tree.split(b'\0'):
        if not record:
            continue
        info, raw_path = record.split(b'\t', 1)
        path = raw_path.decode('utf-8', 'surrogateescape')
        paths('head', head, path)
        mode, kind, oid = info.split()
        if kind == b'blob':
            originals[path] = git(root, 'cat-file', 'blob', oid.decode())
            snapshots.append(('head', path, originals[path]))
    public = git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
    for raw_path in sorted(set(public.split(b'\0')) - {b''}):
        path = raw_path.decode('utf-8', 'surrogateescape')
        file = root / path
        if not file.is_symlink() and not file.is_file():
            continue
        data = os.fsencode(os.readlink(file)) if file.is_symlink() else file.read_bytes()
        if originals.get(path) != data:
            paths('working', head or '(unborn)', path)
            snapshots.append(('working', path, data))
    for scope, path, data in snapshots:
        if b'\0' in data:
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            continue
        matches(scope, 'blocked_text', head, path, text)
        # Whitespace-separated Hebrew words; punctuation ends a run.
        run = 0
        for line_number, line in enumerate(text.splitlines(), 1):
            for word in line.split():
                run = run + 1 if HEBREW.fullmatch(word) else 0
                if run >= 12 and not path.startswith('examples/beta_courses/'):
                    report(scope, 'review', head, path, line=line_number)
            if PRIVATE.search(line):
                report(scope, 'warning', head, path, line=line_number)

    if history and git(root, 'for-each-ref', '--format=%(refname)').strip():
        scan_history(root, git, paths, matches, report, PRIVATE, strict)
    print('counts ' + json.dumps(dict(sorted(counts.items())), sort_keys=True))
    gates = any(n for k, n in counts.items() if not k.endswith(('.review', '.warning')))
    if strict and any(n for k, n in counts.items() if k.endswith('.warning')):
        gates = True
    reviews = counts['head.review'] + counts['working.review']
    return 1 if gates else 2 if reviews else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--strict', action='store_true', help='Gate path/email warnings too')
    parser.add_argument('--blocklist', type=Path, help='Private rules outside the public checkout')
    args = parser.parse_args()
    root = Path(git(Path.cwd(), 'rev-parse', '--show-toplevel').decode().strip())
    return scan(root, args.history, args.strict, args.blocklist)


if __name__ == '__main__':
    raise SystemExit(main())
