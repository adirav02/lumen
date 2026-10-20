# TL;DR: Test bounded first/re-review packets and stale evidence detection.
# Status: active; date: 2026-10-19.
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from _test_receipt import save_receipt, tree_identity
from make_review_packet import make_packet
from test_review_receipts import git_repo


def task(root):
    path = root / 'work/20261019-example'
    path.mkdir(parents=True)
    (path / 'status.json').write_text(json.dumps({'based_on_commit': tree_identity(root)['head_commit']}))
    (path / 'brief.md').write_text('TL;DR: Fix a privacy leak.\nStatus: active.\n\n## Acceptance\n- Public output hides policy.\n')
    (path / 'review.md').write_text('Verdict: PENDING\n')
    return path


def test_packet_reports_base_diff_untracked_receipt_and_prior_findings(git_repo):
    path = task(git_repo)
    (git_repo / '.tmp').mkdir()
    (git_repo / 'tracked').write_text('changed\n')
    (git_repo / 'new.py').write_text('new file\n')
    save_receipt(git_repo, tree_identity(git_repo), 7, [])
    packet = make_packet(git_repo, path.name)
    text = packet.read_text()
    assert 'Tree matches: YES' in text and 'Full suite: True' in text
    assert 'Public output hides policy' in text and 'tracked' in text and 'new.py' in text
    assert 'first review' in text
    (path / 'review.md').write_text('Verdict: FAIL\n\n# Actionable finding\n- P1: api.py:20 leaks policy.\n\n# Checks\n- Passed.\n')
    (git_repo / 'tracked').write_text('corrected\n')
    text = make_packet(git_repo, path.name).read_text()
    assert 'Tree matches: NO' in text and 're-review' in text
    assert 'api.py:20 leaks policy' in text and '- Passed.' not in text
    assert len(text.splitlines()) <= 80


def test_packet_overflow_keeps_scoped_references_and_missing_receipt(git_repo):
    path = task(git_repo)
    (path / 'brief.md').write_text('TL;DR: Big task.\n\n## Acceptance\n' + '- Criterion.\n' * 100)
    (path / 'review.md').write_text('Verdict: FAIL\n\n## Issues\n' + '- Finding.\n' * 100)
    for number in range(40):
        (git_repo / f'new-{number}.py').write_text('x\n')
    text = make_packet(git_repo, path.name).read_text()
    assert len(text.splitlines()) <= 80
    assert 'brief.md#acceptance' in text and 'review.md#findings' in text
    assert 'git diff --stat' in text and 'No successful test receipt' in text


def test_packet_numbers_every_criterion_and_preserves_continuations(git_repo):
    path = task(git_repo)
    (path / 'brief.md').write_text('''TL;DR: Complete acceptance coverage.

## Acceptance criteria
7. Public submissions update weights;
   retries contribute once.
- [x] Saved snapshots remain immutable.
* [ ] Preparation is read-only.

## Out of scope
- New APIs.
''')
    text = make_packet(git_repo, path.name).read_text()
    assert '1. [ ] Public submissions update weights; retries contribute once.' in text
    assert '2. [ ] Saved snapshots remain immutable.' in text
    assert '3. [ ] Preparation is read-only.' in text
    assert text.count('. [ ] ') == 3
    assert 'New APIs' not in text
