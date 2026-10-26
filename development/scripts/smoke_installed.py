#!/usr/bin/env python3
# TL;DR: Exercise a built wheel in a fresh venv outside the source checkout.
# Status: active; date: 2026-10-26.
"""Usage: python development/scripts/smoke_installed.py --wheel dist/lumen-*.whl [--wheelhouse DIR]."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[2]


def smoke(wheel, wheelhouse=None):
    wheel = wheel.resolve(strict=True)
    if wheel.suffix != '.whl':
        raise ValueError('Expected a built wheel')
    # Ignore source import overrides and pip user configuration in child processes.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'PIP_'))}
    env['PIP_CONFIG_FILE'] = os.devnull
    with tempfile.TemporaryDirectory(prefix='lumen-wheel-') as directory:
        scratch = Path(directory).resolve()
        if scratch.is_relative_to(ROOT):
            raise ValueError('Wheel smoke temporary directory must be outside the checkout; set TMPDIR')
        venv.EnvBuilder(with_pip=True).create(scratch / 'env')
        python = scratch / 'env' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        copied_wheel = scratch / wheel.name
        shutil.copyfile(wheel, copied_wheel)
        source = scratch / 'lecture_bayes.txt'
        shutil.copyfile(ROOT / 'tests/fixtures/installed/lecture.txt', source)
        probe = scratch / 'probe.py'
        shutil.copyfile(ROOT / 'development/scripts/_installed_probe.py', probe)
        options = ['--no-index', '--find-links', str(wheelhouse.resolve())] if wheelhouse else []
        def run(*args):
            subprocess.run([str(python), '-I', *args], cwd=scratch, env=env, check=True, timeout=180)
        run('-m', 'pip', '--isolated', '--disable-pip-version-check', 'install', *options, str(copied_wheel))
        run('-m', 'pip', '--isolated', 'check')
        run(str(probe), str(ROOT), str(source))
    print('PASS installed wheel: entrypoints, provenance, retrieval, backup/restore')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path, help='Install dependencies offline from this directory')
    args = parser.parse_args()
    smoke(args.wheel, args.wheelhouse)


if __name__ == '__main__':
    main()
