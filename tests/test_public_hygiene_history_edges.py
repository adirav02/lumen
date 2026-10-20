"""Regression coverage for unusual Git paths and patch text."""
from test_public_hygiene import TERM, check, commit, git, repo, write


def test_history_patch_text_cannot_impersonate_a_file_header(repo):
    write(repo, 'sample.txt', '++ ' + TERM + '\n')
    revision = commit(repo)
    git(repo, 'rm', 'sample.txt')
    commit(repo)
    code, output = check(repo, '--history')
    assert code == 1
    assert f'{revision} sample.txt term #1' in output


def test_history_paths_with_newlines_and_quotes(repo):
    name = 'odd\n"name.txt'
    write(repo, name, TERM)
    revision = commit(repo)
    git(repo, 'rm', name)
    commit(repo)
    code, output = check(repo, '--history')
    assert code == 1
    assert revision in output
    assert 'odd\\n\\"name.txt' in output


def test_untracked_forbidden_extension_is_gated(repo):
    write(repo, 'untracked.zip')
    assert check(repo)[0] == 1


def test_unicode_casefold_path_is_redacted(repo):
    (repo / '.local-blocklist.txt').write_text('strasse\n')
    write(repo, 'stra\u00dfe.txt')
    commit(repo)
    code, output = check(repo, '--history')
    assert code == 1
    assert '[redacted path]' in output
    assert 'stra\\u00dfe' not in output


def test_blocked_author_and_message_are_gated(repo):
    git(repo, 'config', 'user.name', TERM)
    git(repo, 'commit', '--allow-empty', '-qm', TERM)
    code, output = check(repo, '--history')
    assert code == 1 and 'history.blocked_metadata' in output


def test_annotated_tag_metadata_is_gated(repo):
    git(repo, 'tag', '-a', 'example-tag', '-m', TERM)
    code, output = check(repo, '--history')
    assert code == 1 and '(tag metadata)' in output


def test_strict_mode_checks_commit_email(repo):
    email = 'fixture' + '@' + 'example.invalid'
    git(repo, 'config', 'user.email', email)
    git(repo, 'commit', '--allow-empty', '-qm', 'synthetic')
    assert check(repo, '--history')[0] == 0
    code, output = check(repo, '--history', '--strict')
    assert code == 1 and 'history.private_metadata' in output
    assert email not in output


def test_strict_mode_gates_working_email(repo):
    write(repo, 'untracked.txt', 'fixture' + '@' + 'example.invalid')
    assert check(repo)[0] == 0
    assert check(repo, '--strict')[0] == 1


def test_unborn_repository_can_use_external_private_rules(tmp_path):
    public = tmp_path / 'public'
    public.mkdir()
    git(public, 'init', '-q')
    rules = tmp_path / 'private-rules.txt'
    rules.write_text(TERM + '\n')
    options = ('--history', '--strict', '--blocklist', str(rules))
    write(public, 'sample.txt', 'synthetic public fixture')
    assert check(public, *options)[0] == 0
    write(public, 'sample.txt', TERM)
    assert check(public, *options)[0] == 1
