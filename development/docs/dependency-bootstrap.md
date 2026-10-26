TL;DR: Bootstrap with one command, offline from readable local pip caches or a prepared wheelhouse.
Status: active; date: 2026-10-26.

# Dependency bootstrap

From the repository root with Python 3.10+ and its venv/ensurepip support:

```sh
python3 development/scripts/bootstrap.py
```

This creates `.venv`, stages wheels from the local pip wheel and HTTP caches,
installs build/runtime/dev dependencies and editable Lumen without build isolation,
and runs `doctor`. It disables package indexes/network access by default and does
not write to the cache. Read-only caches work; pip's `cache list` is not required.
Staged wheel copies live under `.tmp/bootstrap-*` and are deleted on exit, including
installation failure. A failed install leaves the venv available for a retry.

Cache lookup honors `PIP_CACHE_DIR`, otherwise `XDG_CACHE_HOME/pip` or
`~/.cache/pip`. Select another cache or wheelhouse explicitly:

```sh
python3 development/scripts/bootstrap.py --cache-dir /path/to/pip-cache
python3 development/scripts/bootstrap.py --wheelhouse /path/to/wheelhouse
```

Offline success requires compatible wheels for every build and transitive package.
An empty/incomplete cache reports missing distributions and fails; it cannot create
absent packages. HTTP cache layout is pip-specific; the script reads ZIP wheel
metadata without extracting arbitrary archives. It also accepts ordinary cached
`.whl` files. Use `--online` explicitly to allow downloads when connectivity returns.

To provision a portable wheelhouse on a connected machine with matching Python,
platform and architecture:

```sh
python3 -m pip download --only-binary=:all: --dest /path/to/wheelhouse \
  setuptools wheel 'pypdf>=4' 'python-pptx>=1' 'latex2mathml>=3.77,<4' \
  'pytest>=8' 'PyYAML>=6'
```

Keep wheelhouse outside Git. The pyproject dependency declarations remain the
source of truth; refresh wheels when those change. Verify a clean offline install:
`python3 development/scripts/bootstrap.py --venv .tmp/offline-venv --wheelhouse /path/to/wheelhouse`,
then remove that verification venv when done.

After setup use `.venv/bin/python development/scripts/run_tests.py` and
`.venv/bin/lumen capabilities`. Doctor checks importability, not package-version
compatibility or rendering. PDF export additionally needs a local Chrome, Chromium
or Edge; `LUMEN_BROWSER_EXECUTABLE` can select it. Capabilities renders a math probe.
Usage collection can start before any of this:
`python3 development/scripts/watch_usage.py --label solo-default`; stop with Ctrl-C at task end.
