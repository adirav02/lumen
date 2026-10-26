TL;DR: Verbatim legacy roadmap: 16. Generalized tutoring and practice workflows.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 16. Generalized tutoring and practice workflows

Three provider-neutral workflows are routed by the general Lumen skill:
[tutoring](docs/workflows/tutoring.md), [answer review](docs/workflows/answer-review.md)
and [practice building](docs/workflows/practice-building.md). They cover every
course, with preferences and constraints taken from that course and learner.
Obsolete subject-specific skill/profile archives and their routing note were
removed after they were mistakenly used in a real desktop practice session.

M4 now includes `propose-practice` / `LumenCore.propose_practice`: a read-only
selection of validated questions, scoped to the learner/course, excluding prior
attempted or reserved families by default and reporting shortages. It supports
topic filters, current-batch exclusions and explicitly requested repeats. It does
not establish conceptual novelty beyond recorded family labels, enforce source
dates, import external history, or automatically shuffle/grade multiple choice.
Course-specific dates, exam composition, languages, paths and model names remain
preferences rather than universal defaults. SQLite remains authoritative.

Acceptance evidence: 12 practice-proposal tests, the full 158-test suite, skill
schema/link validation, and five independently forward-reviewed hypothetical
tutoring/checking/practice cases. These behavioral reviews do not replace live
host integration or the broader educational evaluation in M5.

