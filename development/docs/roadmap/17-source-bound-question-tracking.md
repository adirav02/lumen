TL;DR: Verbatim legacy roadmap: 17. Source-bound question tracking.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 17. Source-bound question tracking

Extend M2/M4 with the [question tracking contract](docs/question-tracking.md).
Migration 9 adds exam catalogs, immutable source occurrences, indexed fingerprints
and reviewable relations, plus an append-only ordinary-practice grade ledger.
Existing exam sources are cataloged from stored sections; unsupported/ambiguous
material stays pending. Only explicit review of original pages and accepted counts
can establish whole-exam coverage. Each exam appearance retains its source/version,
locators and extraction snapshot even when its text duplicates another exam.

Learner/course history reports presentation, submission, historical/current grading
and complete correctness separately, with paginated events/evidence/score revisions.
Numeric practice grades reuse current evidence eligibility and required-subpart
rules. Corrections preserve previous scores/feedback and invalidate dependent
current grades. Existing diagnostic score policy and history remain authoritative.

Default practice selection now also considers indexed exact text and unrejected
similarity candidates; the earlier family-only limitation in section 16 is
superseded for those detectable text patterns. Mistake focus intentionally permits
revisits and uses the latest applicable family/skill/subpart evaluation. Candidate
matching is bounded and heuristic; general semantic equivalence, scan OCR and
fully automatic verified extraction remain unsupported. See the tracking contract
for pagination, revision guards, index design and explicit limitations.

