# TL;DR: Create a development venv from cached wheels without network access by default.
# Status: active; date: 2026-10-26.
"""One-command setup; reads pip's wheel and HTTP caches, never modifies them."""
import argparse
from email.parser import Parser
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def stage_cached_wheels(cache, target):
    """Recover wheel filenames from ZIP metadata; never extract cached archives."""
    count = 0
    for path in sorted(cache.rglob('*')) if cache.is_dir() else []:
        if path.suffix not in {'.whl', '.body'} or not path.is_file():
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                wheels = [n for n in archive.namelist() if n.count('/') == 1 and n.endswith('.dist-info/WHEEL')]
                if len(wheels) != 1:
                    continue
                info = Parser().parsestr(archive.read(wheels[0]).decode())
                # dist-info basename already has wheel-normalized name/version.
                stem = wheels[0].rsplit('/', 1)[0].removesuffix('.dist-info')
                tag = info.get('Tag', '')
                build = info.get('Build')
                filename = f'{stem}{"-" + build if build else ""}-{tag}.whl'
                if not re.fullmatch(r'[A-Za-z0-9_.+!-]+\.whl', filename) or not tag:
                    continue
                shutil.copyfile(path, target / filename)
                count += 1
        except (zipfile.BadZipFile, KeyError, UnicodeError):
            continue  # Most HTTP cache bodies are package indexes, not wheels.
    return count


def bootstrap(root, target, cache, *, online=False, wheelhouse=None):
    root, target = root.resolve(), target.resolve()
    if not (target / 'pyvenv.cfg').exists():
        venv.EnvBuilder(with_pip=True).create(target)
    python = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    scratch = root / '.tmp'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bootstrap-', dir=scratch) as directory:
        wheels = Path(directory)
        count = stage_cached_wheels(cache, wheels)
        print(f'Staged {count} cached wheels; network {"allowed" if online else "disabled"}.', flush=True)
        pip = [str(python), '-m', 'pip', '--disable-pip-version-check', '--no-cache-dir', 'install']
        options = ['--find-links', str(wheels)]
        if wheelhouse:
            options += ['--find-links', str(wheelhouse.resolve())]
        if not online:
            options += ['--no-index']
        subprocess.run([*pip, *options, 'setuptools>=61', 'wheel'], cwd=root, check=True)
        subprocess.run([*pip, *options, '--no-build-isolation', '-e', '.[dev]'], cwd=root, check=True)
        subprocess.run([str(python), '-m', 'course_tutor.cli', 'doctor'], cwd=root, check=True)
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv', type=Path, default=ROOT / '.venv')
    cache = Path(os.environ.get('PIP_CACHE_DIR') or
                 Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'pip')
    parser.add_argument('--cache-dir', type=Path, default=cache)
    parser.add_argument('--wheelhouse', type=Path)
    parser.add_argument('--online', action='store_true', help='Allow package downloads if cache is incomplete')
    args = parser.parse_args()
    try:
        python = bootstrap(ROOT, args.venv, args.cache_dir, online=args.online, wheelhouse=args.wheelhouse)
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Bootstrap failed: {exc}\nOffline setup needs compatible cached wheels for all dependencies; '
                    'see docs/dependency-bootstrap.md or explicitly use --online.\n')
    print(f'Ready: {python} scripts/run_tests.py')


if __name__ == '__main__':
    main()
