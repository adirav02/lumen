# GitHub Actions review — 2026-10-19

Public snapshot validation uses `scripts/run_tests.py`, including before the
first commit. Packages use `scripts/build_public.py` to remove local ownership
and timestamps from source archives. Release validation rejects source archives
with non-anonymous ownership metadata.

The original CI had a useful Python 3.10–3.14 matrix, demo, metadata validation,
and wheel installation. Its release workflow could publish without running the
tests; a version tag could disagree with the package version, manual branch runs
did nothing at publication time, and repository write permission applied to build
steps. The wheel smoke check only ran capabilities and could miss initialization,
migration, ingestion or backup defects in an installed package.

The updated release calls the same CI workflow before publishing, downloads its
validated distributions, and grants repository write access only to the publish
job. It uses the runner's GitHub CLI rather than a third-party release action.
A tag-only precheck rejects branch dispatches; distribution metadata must agree
and the version tag must match. Jobs have timeouts, checkouts do not retain Git
credentials, and workflow permissions default to read-only. Release concurrency
queues tag publications; its group is distinct from called CI to prevent a run
from canceling itself. CI cancels superseded branch runs, but preserves tag runs.
Actions are pinned to full commit IDs and Dependabot checks their updates weekly.

Package validation runs both installed CLI entrypoints and the synthetic demo
outside the checkout in a separate virtual environment. The normal build frontend
builds the wheel through the sdist. Tests cover distribution and tag mismatches.
This distributes Python packages to GitHub Releases; no hosted service or PyPI
deployment is configured.

## Current publication behavior

The release-readiness follow-up on 2026-10-19 adds `--draft` to GitHub release
creation. Passing CI prepares a draft with validated artifacts; stable publication
awaits the [integration/evaluation evidence review](release-readiness.md). The
earlier publication description above records the preceding CI repair.

## Verification boundaries

Local validation passed: 205 tests, sdist/wheel build through a locally available
backend, Twine metadata validation, distribution identity checks, and the demo
using the installed wheel outside the checkout. The wheel smoke run reused local
extraction dependencies because network installs were unavailable. Both skill
pointers passed schema validation; workflow YAML and embedded Bash syntax parsed.
The real-course simulation and offline HTML renderer also passed in isolated
output; a new PDF was not rendered or visually reviewed. These do not establish
successful hosted Actions execution on every matrix version. The review environment
has no GitHub CLI or Claude Code executable, and direct GitHub API access failed,
so live run logs, branch protection, repository action policies and native Claude
profile loading could not be verified. After pushing, inspect the new CI run and
configure required checks in GitHub repository settings as appropriate. No release
was published and no repository settings were changed during this review.


## Runtime deprecation follow-up

After the hosted run reported Node 20 deprecation annotations, all four Action
pins were updated to releases whose exact `action.yml` declares `runs.using: node24`:
checkout v7.0.1, setup-python v7.0.0, upload-artifact v7.0.2 and download-artifact
v8.0.2. Their configured inputs were checked against those pinned manifests.
The artifact upload retains the default archive format consumed by the download.
This follows [GitHub's Node 20 migration guidance](https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/).

All hosted jobs now explicitly select `ubuntu-24.04`, keeping the existing OS
baseline during the [ubuntu-latest migration](https://github.com/actions/runner-images/issues/14748).
This fixes the moving-label notices; it does not freeze the image's installed
software updates. The next hosted run must confirm execution without these
annotations. Local configuration tests and pinned upstream manifest checks passed.

## Assembly pipeline follow-up — 2026-10-19

Each Python matrix job now checks documentation and generated agent profiles,
then requires a supported PDF browser before running the full suite. This ensures
the real assembly and staged-export PDF smoke tests cannot silently skip because
the browser is absent. The selected [Ubuntu 24.04 runner image](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
includes supported browsers; CI checks discovery and executable startup explicitly.
The full suite covers saved-blueprint CLI assembly, shortages, publication/recovery,
snapshot re-export and student artifact privacy. Per-version JUnit reports are
retained for seven days, including after failures when a report was produced.

The existing reusable CI gate applies these checks to draft release preparation
as well. Automated PDF rendering does not establish human visual review. Hosted
matrix execution still needs verification after these changes are pushed.

Local verification for this follow-up: 451 tests passed on Python 3.14, including
real browser PDF checks; documentation/profile checks, workflow YAML and embedded
Bash syntax, the synthetic demo, an isolated sdist-to-wheel build, Twine metadata
validation and distribution identity checks all passed.
