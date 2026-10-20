"""Validation must work before the clean public repository's first commit."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from _test_receipt import tree_identity


def test_unborn_identity_covers_staged_untracked_and_ignored_files(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    (tmp_path / '.gitignore').write_text('.tmp/\n')
    file = tmp_path / 'sample.txt'
    file.write_text('before')
    before = tree_identity(tmp_path)
    assert before['head_commit'] == 'unborn'
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    assert tree_identity(tmp_path) == before
    file.write_text('after')
    assert tree_identity(tmp_path) != before
    unchanged = tree_identity(tmp_path)
    (tmp_path / '.tmp').mkdir()
    (tmp_path / '.tmp/ignored').write_text('cache')
    assert tree_identity(tmp_path) == unchanged
    file.unlink()
    assert tree_identity(tmp_path) != unchanged


def test_wrapper_runs_and_saves_receipt_before_first_commit(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    (tmp_path / '.gitignore').write_text('.tmp/\n__pycache__/\n.pytest_cache/\n')
    (tmp_path / 'pytest.ini').write_text('[pytest]\n')
    (tmp_path / 'test_sample.py').write_text('def test_sample():\n    pass\n')
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    original = Path(__file__).resolve().parents[1] / 'scripts'
    for name in ('run_tests.py', '_test_receipt.py', '_devtools.py'):
        shutil.copyfile(original / name, scripts / name)
    result = subprocess.run([sys.executable, str(scripts / 'run_tests.py')],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((tmp_path / '.tmp/test-receipt.json').read_text())
    assert receipt['head_commit'] == 'unborn'
    assert receipt['passed'] == 1 and receipt['tree_unchanged']
