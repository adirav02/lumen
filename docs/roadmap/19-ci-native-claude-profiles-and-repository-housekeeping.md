TL;DR: Verbatim legacy roadmap: 19. CI, native Claude profiles and repository housekeeping.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 19. CI, native Claude profiles and repository housekeeping

The CI workflow is reusable by tagged releases; publication requires the complete
Python 3.10–3.14 matrix and package checks, and prepares the validated artifact as a draft release pending M5 evidence.
Tag/distribution identity is checked before publication. Read-only build tokens,
credential-free checkouts, job timeouts, SHA-pinned Actions and Dependabot updates
bound the workflow. See [CI review](docs/ci-review.md) for verification limits.

Claude-native Markdown/YAML profiles mirror the existing bounded algorithms roles.
Both shared skills have thin Claude discovery pointers with matching metadata;
canonical workflows remain under `.agents/skills` and `docs/workflows`. Static
schema/routing checks do not establish live Claude loading or host conformance.

The real-course simulation passes export paths explicitly and defaults to isolated
run output rather than modifying reference snapshots. Its renderer accepts an
exported course and invalidates old print checks when rebuilding HTML. Regression
checks cover default/custom output, unchanged checked-in snapshots, native profile
and skill routing, and release identity/gating. Example and documentation indexes
explain fixture, evidence and generated-output ownership. Original uploads,
learner state and historical review evidence are preserved.

