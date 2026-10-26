# TL;DR: Build a bounded deterministic review assignment from local task evidence.
# Status: active; date: 2026-10-19.
"""Usage: python3 development/scripts/make_review_packet.py YYYYMMDD-slug."""
import argparse
import json
import re
from pathlib import Path
from _devtools import ROOT, header, task_path, tldr
from _test_receipt import git, receipt_status


def section(text, pattern):
    lines, active = [], False
    for line in text.splitlines():
        if line.startswith('#'):
            if active:
                break
            active = bool(re.search(pattern, line, re.I))
        elif active:
            lines.append(line)
    return lines


def bounded(lines, limit, reference):
    lines = [line for line in lines if line.strip()]
    if len(lines) <= limit:
        return lines
    return lines[:limit-1] + [f'- More: {reference} (read only this section).']


def acceptance_checklist(lines):
    criteria = []
    for line in lines:
        if not line.strip():
            continue
        item = re.match(r'^\s*(?:[-+*]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(.*)', line)
        if item:
            criteria.append(item.group(1))
        elif criteria:
            criteria[-1] += ' ' + line.strip()
        else:
            criteria.append(line.strip())
    return [f'{number}. [ ] {criterion}' for number, criterion in enumerate(criteria, 1)]


def make_packet(root, task_id):
    task = task_path(root, task_id)
    state = json.loads((task / 'status.json').read_text())
    base = state['based_on_commit']
    if not re.fullmatch(r'[0-9a-fA-F]{7,40}', base):
        raise ValueError('Task requires a valid based_on_commit')
    # --stat compares the task base to the actual working tree, including index changes.
    stat = git(root, 'diff', '--stat=100', '--no-ext-diff', base, '--').decode().splitlines()
    untracked = git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
    stat += [f' {name} | untracked (not in Git diff)' for name in untracked if name]
    brief = (task / 'brief.md').read_text()
    acceptance = acceptance_checklist(section(brief, r'acceptance|completion criteria'))
    receipt, matches = receipt_status(root)
    review = task / 'review.md'
    previous = review.read_text() if review.exists() else ''
    rereview = bool(re.search(r'^Verdict: (PASS|FAIL)\s*$', previous, re.M))
    lines = (header('Review packet: scoped task, current diff and test evidence.', 'generated').splitlines()
             + [f'# {task_id}', f'Base commit: `{base}`',
                f'Review: {"re-review" if rereview else "first review"}', '',
                '## Brief', tldr(task / 'brief.md'), '', '## Acceptance'])
    lines += bounded(acceptance or ['- Missing acceptance criteria; consult brief.md.'], 12, 'brief.md#acceptance')
    lines += ['', '## Changed files (base to working tree)', '```']
    lines += bounded(stat or ['No changed files.'], 20, f'git diff --stat {base}') + ['```']
    lines += ['', '## Test receipt', f'Tree matches: {"YES" if matches else "NO"}']
    if receipt:
        lines += [f'HEAD: `{receipt.get("head_commit")}`; diff SHA256: `{receipt.get("diff_hash")}`',
                  f'Passed: {receipt.get("passed")}; UTC: {receipt.get("timestamp_utc")}',
                  f'Full suite: {receipt.get("full_suite") is True}; args: {json.dumps(receipt.get("args"))}']
    else:
        lines += ['No successful test receipt available.']
    lines += ['Skip full suite only with a matching full-suite receipt; use focused tests.',
              '', '## Previous findings']
    if rereview:
        findings = section(previous, r'actionable finding|findings|issues')
        verdict = re.search(r'^Verdict: .*$', previous, re.M).group()
        lines += [verdict] + bounded(findings or ['- See review.md for prior findings.'], 10, 'review.md#findings')
    else:
        lines += ['None: first review.']
    lines += ['', '## Scope', 'Inspect changed code and touched contracts only. General docs require an explicit packet reference.',
              'Re-review only high-severity findings; inspect the corrective diff and touched contracts.']
    if len(('\n'.join(lines)).splitlines()) > 80:
        raise ValueError('Review packet exceeds 80 lines')
    output = task / 'review-packet.md'
    output.write_text('\n'.join(lines) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task_id')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(make_packet(args.root.resolve(), args.task_id))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'{exc}\n')
