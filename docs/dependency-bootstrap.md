TL;DR: Diagnose dependencies before tests; provision an offline wheelhouse in advance.
Status: active; date: 2026-10-20.

# Dependency bootstrap

Run `PYTHONPATH=src .venv/bin/python -m course_tutor.cli doctor`. This lists runtime,
dev and build declarations, their import results, and an exact missing-package
install command. A missing import exits nonzero. `scripts/run_tests.py` uses the
same preflight. Importability does not certify package version compatibility;
the real test suite and render probe are separate checks.

On a connected machine with the same Python version, platform and architecture:

```sh
python3 -m venv .venv
.venv/bin/python -m pip download --dest wheelhouse '.[dev]'
```

Copy the repository and wheelhouse to the offline machine, then run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --find-links wheelhouse setuptools wheel
.venv/bin/python -m pip install --no-index --find-links wheelhouse -e '.[dev]'
.venv/bin/python -m course_tutor.cli doctor
.venv/bin/python scripts/run_tests.py
.venv/bin/python -m course_tutor.cli capabilities
```

Keep wheelhouse outside git. Download all build and transitive wheels, including
`setuptools` and `wheel`, and verify the offline install on a clean environment.
No core command downloads packages. PDF rendering additionally requires a locally
installed Chrome, Chromium or Edge (`LUMEN_BROWSER_EXECUTABLE` can select it).
The capability command renders a tiny math document and parses the PDF; browser
discovery alone does not establish export readiness.
