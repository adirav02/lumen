# TL;DR: Identify the tested Git tree, including staged changes and untracked files.
# Status: active; date: 2026-10-19.
import hashlib
import json
from pathlib import Path
import subprocess
from _devtools import now, write_json


def git(root, *args):
    result = subprocess.run(['git', *args], cwd=root, capture_output=True)
    if result.returncode:
        raise ValueError('Git tree identity unavailable')
    return result.stdout


def tree_identity(root):
    try:
        head = git(root, 'rev-parse', '--verify', 'HEAD').decode().strip()
    except ValueError:
        git(root, 'rev-parse', '--git-dir')  # Fail outside a Git repository.
        head = 'unborn'
    digest = hashlib.sha256()
    if head != 'unborn':
        digest.update(git(root, 'diff', '--binary', '--no-ext-diff', '--no-textconv', 'HEAD', '--'))
    arguments = ['--cached'] if head == 'unborn' else []
    # Ignored task artifacts, receipts and caches do not invalidate evidence.
    names = git(root, 'ls-files', *arguments, '--others', '--exclude-standard', '-z')
    for name in sorted(set(names.split(b'\0'))):
        if not name:
            continue
        path = Path(root) / name.decode('utf-8', errors='surrogateescape')
        if not path.is_symlink() and not path.exists():
            continue
        data = path.readlink().as_posix().encode() if path.is_symlink() else path.read_bytes()
        digest.update(b'\0' + name + b'\0' + str(path.lstat().st_mode).encode() + b'\0')
        digest.update(hashlib.sha256(data).digest())
    return {'head_commit': head, 'diff_hash': digest.hexdigest()}


def save_receipt(root, before, passed, args):
    after = tree_identity(root)
    receipt = {**before, 'passed': passed, 'timestamp_utc': now(),
               'args': list(args), 'full_suite': not args, 'tree_unchanged': before == after}
    write_json(Path(root) / '.tmp/test-receipt.json', receipt)
    return receipt


def receipt_status(root):
    path = Path(root) / '.tmp/test-receipt.json'
    if not path.exists():
        return None, False
    receipt = json.loads(path.read_text())
    identity = tree_identity(root)
    matches = (receipt.get('tree_unchanged') is True and
               all(receipt.get(k) == v for k, v in identity.items()) and
               type(receipt.get('passed')) is int and receipt['passed'] >= 0)
    return receipt, matches
