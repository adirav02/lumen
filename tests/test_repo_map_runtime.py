"""Local test logs and CI reports must not make the public map stale."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from gen_repo_map import generate


def test_repo_map_is_stable_after_local_and_ci_validation(tmp_path):
    (tmp_path / 'docs').mkdir()
    assert generate(tmp_path)
    for name in ('.tmp', 'test-results'):
        directory = tmp_path / name
        directory.mkdir()
        (directory / 'report').write_text('runtime output')
    assert generate(tmp_path, check=True)
