TL;DR: Verbatim legacy roadmap: 22. Native Claude and Antigravity CLI measurement.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 22. Native Claude and Antigravity CLI measurement

`configure-usage` installs scoped native status-line callbacks, preserving existing
display commands and unrelated settings with locked, backed-up atomic writes.
Claude uses ignored project-local settings; Antigravity CLI uses its documented
user settings, with capture filtered to this project. Callbacks record counters
without retaining payload text. Claude also has project-transcript discovery,
message-ID deduplication, cache-inclusive normalization and separate child files.

The Antigravity headless launcher relays stream JSON, verifies initialization and
conversation identity, and captures terminal cumulative counters without adding
per-step updates. Native raw cache counters are preserved when inclusive input
cannot be established. Missing results fail capture; native exit failures remain
failures. The shared summary selects latest values per host/session/scope so
context-window samples cannot hide cumulative totals or be added as new charges.
Estimated native costs remain estimates; billed cost stays unknown. Ledger history
validation now uses an index per scan, supporting frequent native updates without
quadratic duplicate checks.

Acceptance: 273 local tests; actual Antigravity CLI 1.4.2 headless and resumed-TUI
callback checks; Claude fixture/subprocess tests and installed configuration only.
See [native adapter evidence](docs/evaluation/host-usage-2026-10-19.json) and
[setup/accounting guide](docs/usage-measurement.md). Live Claude, IDE measurement,
full retries/images/cost attribution and broader release gates remain open.

