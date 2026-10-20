TL;DR: Verbatim legacy roadmap: 20. Release evidence, usage ledger and educational evaluation.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 20. Release evidence, usage ledger and educational evaluation

The [readiness checklist](docs/release-readiness.md) tracks completed local work
separately from live Claude/cross-host and unseen educational/measurement gates.
[Claude handoff instructions](docs/claude-handoff.md) allow a tester with access
to collect discovery, execution, visual and fresh-session evidence without
requiring new features or treating a simulated marker as a host run.

`record-usage` / `usage-summary` maintain a locked append-only JSONL measurement
ledger, independent of learner SQL state. It records per-call provenance, retries,
image counts, latency, reported/estimated/unavailable token counts and
billed/estimated/unavailable USD costs, plus reviewed task outcomes and run
collection declarations. Unknown values stay null. Cost per correct task requires
complete declared collection, finalized outcomes and billed costs for every call;
failures and retries remain in the numerator. See [measurement protocol](docs/usage-measurement.md)
for limitations, corrections, and the ledger's separate backup/transfer requirement.

The [educational evaluation](examples/educational_evaluation/README.md) adds 16
generated submissions with checked derivations, captured judgments, diagrams,
ambiguous inputs, alternate proofs, exact-version Hebrew choices, source-key
conflicts and chronological assistance. The runner retains failed cases and
exercises shared-core evidence policy for matched decisions. These are authored
and reviewed fixtures, not a blind model benchmark or proof of real-host teaching
accuracy. Fresh held-out submissions and actual provider usage remain M5 work.

