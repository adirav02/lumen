#!/usr/bin/env python3
# TL;DR: Build public packages without leaking local archive ownership metadata.
# Status: active; date: 2026-10-20.
"""Usage: python development/scripts/build_public.py [--outdir dist]."""
import argparse
import gzip
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


def anonymize_sdist(path):
    """Preserve member names/content; discard owner, timestamp and PAX metadata."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            with tarfile.open(path, 'r:gz') as source:
                with gzip.GzipFile(filename='', mode='wb', fileobj=file, mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as output:
                        for member in source.getmembers():
                            member.uid = member.gid = member.mtime = 0
                            member.uname = member.gname = ''
                            member.pax_headers = {}
                            content = source.extractfile(member) if member.isfile() else None
                            try:
                                output.addfile(member, content)
                            finally:
                                if content is not None:
                                    content.close()
        os.chmod(temporary, path.stat().st_mode)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outdir', type=Path, default=Path('dist'))
    args = parser.parse_args()
    result = subprocess.run([sys.executable, '-m', 'build', '--outdir', str(args.outdir)])
    if result.returncode:
        return result.returncode
    for archive in args.outdir.glob('*.tar.gz'):
        anonymize_sdist(archive)
    print('Public distribution archive metadata anonymized.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
