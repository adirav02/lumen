TL;DR: Legacy roadmap status and detail routing; load this index by default.
Status: historical roadmap summary; date: 2026-10-19.

# Roadmap index

Read only the linked part needed for the task. These statuses summarize the
roadmap itself, not a new implementation audit. “Done locally” follows its overall
implemented/audited-core status; individual milestone exit gates are not separately
signed off. Not started: no phase is explicitly labelled this way; do not infer it
from proposed contracts or open gates. Original relative links in verbatim parts
still refer to the repository root; their text has deliberately not been rewritten.

M0 — Shared contract/discovery: implemented locally; live completion unclear because Claude discovery/invocation remains open. Open [milestones](10-milestones-and-completion-gates.md), [host contract](03-universal-support-contract.md).

M1 — Storage/originals: done locally at core level; individual exit-gate sign-off unclear. Open [milestones](10-milestones-and-completion-gates.md), [storage](09-persistence-backup-and-migration.md), [data model](05-data-model.md).

M2 — Ingestion/retrieval: done locally with reviewed examples and pending material; general OCR and fully automatic verified extraction remain unsupported. Open [ingestion](04-source-preservation-and-course-ingestion.md), [retrieval](07-retrieval-and-token-efficiency.md), [extraction follow-up](18-organized-course-extraction-and-real-material-simulation.md).

M3 — Evidence/corrections: done locally at core level; individual exit-gate sign-off unclear. Open [tutoring](08-tutoring-and-evaluation.md), [milestones](10-milestones-and-completion-gates.md), [audit](15-october-2026-audit.md).

M4 — Diagnostics/practice: done locally, extended by source-bound tracking; detectable text similarity is heuristic, not general semantic equivalence. Open [practice](16-generalized-tutoring-and-practice-workflows.md), [tracking](17-source-bound-question-tracking.md), [milestones](10-milestones-and-completion-gates.md).

M5 — Host conformance/efficiency: in progress. Live Antigravity resume and one real-course Codex visual workflow passed; live Claude, cross-host handover, broader held-out education and measured usage/cost remain open. Open [original status](00-preamble.md), [milestones](10-milestones-and-completion-gates.md), [release/evaluation](20-release-evidence-usage-ledger-and-educational-evaluation.md).

M6 — Correctness/reliability repairs: done locally under the overall audited-core status; the table lists exit criteria, not a separate phase sign-off. Open [milestones](10-milestones-and-completion-gates.md), [failure fixtures](11-failure-scenarios-and-acceptance-fixtures.md).

M7 — Final correctness verification: done locally under the overall audited-core status; the historical 77-test exit gate is not a fresh result. Open [milestones](10-milestones-and-completion-gates.md).

M8 — Reliability/security repairs: done locally under the overall audited-core status; individual exit-gate sign-off unclear. Open [milestones](10-milestones-and-completion-gates.md), [failure fixtures](11-failure-scenarios-and-acceptance-fixtures.md).

M9 — Underlying invariants repairs: done locally under the overall audited-core status; individual exit-gate sign-off unclear. Open [milestones](10-milestones-and-completion-gates.md).

M10 — Provenance/scoring repairs: done locally under the overall audited-core status; individual exit-gate sign-off unclear. Open [milestones](10-milestones-and-completion-gates.md), [audit](15-october-2026-audit.md).

CI/profiles/housekeeping follow-up: implemented with regression checks; static routing does not prove live Claude conformance. Open [CI follow-up](19-ci-native-claude-profiles-and-repository-housekeeping.md).

Usage follow-ups: in progress. Actual Codex counters and Antigravity CLI checks exist; live Claude and full cost attribution remain open. Desktop fallback captured practice counters; native hook delivery remains open. Open [Codex collection](21-automatic-local-codex-usage-collection.md), [native CLI adapters](22-native-claude-and-antigravity-cli-measurement.md), [desktop collection](23-antigravity-standalone-desktop-usage.md).

Course discovery/workflow cleanup: implemented; public imports replayed without duplicate records, with probability questions pending. Open [course discovery](24-course-discovery-and-general-workflow-cleanup.md).

PDF delivery/replies/export follow-ups: implemented locally; subsequent actual AGY printing and three page inspections passed. Fresh native use of revised folder/discovery defaults remains pending. Open [PDF delivery](25-default-pdf-test-delivery-and-task-usage-wording.md), [exports/replies](26-minimal-delivery-replies-and-course-local-test-exports.md).

Other reference detail: [precedence](01-deliverables-and-document-precedence.md), [architecture](02-architecture.md), [proposed tools](06-shared-tool-contract.md), [evaluation protocol](12-evaluation-protocol.md), [unresolved decisions](13-remaining-decisions.md), [historical external references](14-documentation-references.md).

Preservation: `python3 development/scripts/check_roadmap.py` concatenates numbered parts after
removing their four-line headers and checks the original SHA-256, Git blob identity
and line count recorded in `development/scripts/roadmap_manifest.json`. It also enforces the
part/index line limits. The original commit is recorded there for direct comparison.
