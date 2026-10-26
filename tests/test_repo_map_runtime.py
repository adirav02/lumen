"""Local test logs and CI reports must not make the public map stale."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development/scripts'))
from gen_repo_map import generate


def test_repo_map_is_stable_after_local_and_ci_validation(tmp_path):
    (tmp_path / 'docs').mkdir()
    assert generate(tmp_path)
    for name in ('.tmp', 'test-results'):
        directory = tmp_path / name
        directory.mkdir()
        (directory / 'report').write_text('runtime output')
    assert generate(tmp_path, check=True)


def test_map_matches_clean_checkout_without_ignored_or_empty_directories(tmp_path):
    import shutil
    import subprocess

    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    (repo / '.gitignore').write_text('examples/private/\n')
    public = repo / 'examples/public/README.md'
    public.parent.mkdir(parents=True)
    public.write_text('Public synthetic example\n')
    private = repo / 'examples/private/source.txt'
    private.parent.mkdir(parents=True)
    private.write_text('Local ignored example\n')
    (repo / 'docs/roadmap').mkdir(parents=True)  # Left empty by a tracked move.
    assert generate(repo)
    snapshot = tmp_path / 'clean'
    names = subprocess.check_output(
        ['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=repo).decode()
    for name in filter(None, names.split('\0')):
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
    assert generate(snapshot, check=True)
    result = (repo / 'development/docs/repo-map.md').read_text()
    assert '    public/' in result
    assert 'private/' not in result and 'roadmap/' not in result
