"""Public hygiene checks use disposable repositories and synthetic private terms."""
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_public_hygiene.py'
TERM = 'synthetic' + '-private-token'


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo).decode().strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Fixture')
    git(tmp_path, 'config', 'user.email', 'redacted-email')
    (tmp_path / '.local-blocklist.txt').write_text(TERM + '\n')
    (tmp_path / '.gitignore').write_text('.local-blocklist.txt\n')
    commit(tmp_path)
    return tmp_path


def commit(repo):
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'fixture')
    return git(repo, 'rev-parse', 'HEAD')


def check(repo, *args):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo,
                            capture_output=True, text=True)
    assert TERM.casefold() not in result.stdout.casefold()
    assert result.stderr == ''
    return result.returncode, result.stdout


def write(repo, name, text='fixture\n'):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_clean_and_missing_blocklist(repo):
    assert check(repo)[0] == 0
    (repo / '.local-blocklist.txt').unlink()
    assert check(repo)[0] == 1


@pytest.mark.parametrize('name', ['examples/real_course_test/courses/a/test.txt',
                                 'a.docx', 'a.DOC', 'a.xlsx', 'a.zip'])
def test_forbidden_paths(repo, name):
    write(repo, name)
    commit(repo)
    assert check(repo)[0] == 1


@pytest.mark.parametrize('in_path', [False, True])
def test_fixed_case_insensitive_terms_and_redaction(repo, in_path):
    write(repo, TERM.upper() + '.txt' if in_path else 'sample.txt',
          'fixture' if in_path else TERM.upper())
    commit(repo)
    code, output = check(repo)
    assert code == 1
    assert 'term #1' in output


def test_terms_are_fixed_strings(repo):
    (repo / '.local-blocklist.txt').write_text('fixture.*token\n')
    write(repo, 'sample.txt', 'fixture123token')
    commit(repo)
    assert check(repo)[0] == 0
    write(repo, 'sample.txt', 'FIXTURE.*TOKEN')
    commit(repo)
    assert check(repo)[0] == 1


@pytest.mark.parametrize('folder,code', [('notes', 2), ('examples/beta_courses', 0)])
def test_hebrew_run_and_safe_locations(repo, folder, code):
    word = chr(0x5d0) + chr(0x5d1)
    write(repo, folder + '/sample.txt', ' '.join([word] * 12))
    commit(repo)
    actual, output = check(repo)
    assert actual == code
    if code:
        assert f'{folder}/sample.txt:1' in output
        assert word not in output


def test_hebrew_threshold_and_cross_line_run(repo):
    word = chr(0x5d0) + chr(0x5d1)
    write(repo, 'sample.txt', ' '.join([word] * 11))
    commit(repo)
    assert check(repo)[0] == 0
    write(repo, 'sample.txt', ' '.join([word] * 11) + '\n' + word)
    commit(repo)
    assert check(repo)[0] == 2


def test_warnings_do_not_gate_or_leak_content(repo):
    home = '/' + 'home/fixture/private'
    email = 'fixture' + '@' + 'example.invalid'
    write(repo, 'sample.txt', home + '\n' + email + '\n')
    commit(repo)
    code, output = check(repo)
    assert code == 0
    assert 'sample.txt:1' in output and 'sample.txt:2' in output
    assert home not in output and '@' not in output


def test_history_deleted_content_and_files(repo):
    write(repo, 'sample.txt', TERM.upper())
    write(repo, 'removed.zip')
    revision = commit(repo)
    git(repo, 'rm', 'sample.txt', 'removed.zip')
    commit(repo)
    assert check(repo)[0] == 0
    code, output = check(repo, '--history')
    assert code == 1
    assert revision in output
    assert 'history.extension' in output and 'history.blocked_text' in output
    assert 'term #1' in output


def test_history_scans_other_refs_and_paths(repo):
    git(repo, 'checkout', '-qb', 'other')
    write(repo, TERM + '.txt')
    revision = commit(repo)
    git(repo, 'checkout', '-')
    code, output = check(repo, '--history')
    assert code == 1
    assert revision in output and 'history.blocked_path' in output


def test_changed_and_untracked_content_is_checked(repo):
    write(repo, 'sample.txt')
    commit(repo)
    write(repo, 'sample.txt', TERM)
    assert check(repo)[0] == 1
    write(repo, 'sample.txt', 'clean')
    write(repo, 'untracked.txt', TERM)
    assert check(repo)[0] == 1
    (repo / 'untracked.txt').unlink()
    write(repo, 'local-courses/private.txt', TERM)
    with (repo / '.gitignore').open('a') as f:
        f.write('local-courses/\n')
    assert check(repo)[0] == 0
