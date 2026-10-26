TL;DR: Verbatim legacy roadmap: 21. Automatic local Codex usage collection.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 21. Automatic local Codex usage collection

`collect-usage` imports observed cumulative counters from local Codex rollout
logs whose metadata matches the requested project directory. `watch-usage` polls
for changes and writes idempotent host-reported snapshots to the existing usage
ledger. The reader retains no conversation text. Summaries select the latest
snapshot per session; they never add successive cumulative snapshots to calls,
or pool potentially inherited fork histories into a grand total. Cache and
reasoning counts remain subsets, and mixed model contexts remain visible.

This was exercised against actual local Codex logs, correcting the earlier claim
that no host counters were available. Per-request completeness, hidden retries,
image counts, latency, actual charges and cost-per-correct-task attribution remain
unknown. At that milestone native Claude/Antigravity collection was unverified;
section 22 records the native-adapter follow-up. The documented OTel routes can
support richer adapters after actual host testing. No
global host settings or automatically installed background services are added;
the user starts one continuous watcher. See [measurement protocol](docs/usage-measurement.md).

