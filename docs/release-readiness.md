# Release readiness — 2026-10-19

The core is implemented and locally tested. Release validation is **open**.
Claude Code is not available to the owner yet; a friend's future run can supply
the missing evidence using the prepared handoff. Adding features or passing CI
does not close live integration or educational measurement gates.

| State | Check | Evidence / action |
|---|---|---|
| Complete locally | Core storage/retrieval/evidence, course import, CI/package configuration | Historical [205-test local validation](ci-review.md); this change's run is recorded below |
| Complete, bounded live evidence | Antigravity integration and fresh-session resume | [Recorded report](antigravity-integration-report.md); new features not inferred tested there |
| Complete, bounded live evidence | Real-course Codex image-review workflow | [Recorded report](real-course-integration-report.md) |
| Open; instructions ready | Claude native instructions, skills/profiles, CLI, image access, new conversation resume | [Friend-ready protocol](claude-handoff.md), [report template](templates/host-smoke-report.md); no Claude runtime run yet |
| Open | Same real attempt across two actual hosts | [Cross-host handover](claude-handoff.md#cross-host-handover); environment-marker tests are simulation |
| Partial | Broader educational correctness | [16 generated reviewed cases](../examples/educational_evaluation/README.md), [results](evaluation/education-2026-10-19.json); independent unseen real-host review still needed |
| Partial; three measurement adapters implemented | Codex and Antigravity CLI verified; Claude native runtime, per-call/retry/image/billing completeness remain open | [Commands/protocol](usage-measurement.md), [Codex report](evaluation/codex-usage-2026-10-19.json), [native adapter report](evaluation/host-usage-2026-10-19.json) |
| Draft-only workflow | Tag CI uses checked artifacts without declaring release readiness | `.github/workflows/release.yml` creates drafts; no stable release published here |

## Local validation for this change

Local Linux / Python 3.14.8 / SQLite 3.51.2 validation on 2026-10-19:

- Full pytest suite: **234 passed** (prior baseline: 205). New checks cover ledger
  retries, images, unknown/estimated costs, task corrections, concurrent CLI
  processes, corrupt log rejection, educational reference/policy cases, failure
  retention and critical false confirmations.
- Synthetic probability demo and capabilities inspector passed.
- Educational run: **16/16** captured judgments/policy cases passed; **0 critical
  failures**. Both generated graph images were visually inspected. Exact fractions,
  path enumeration and finite graph probes support the checked derivations.
- Built sdist and wheel offline with cached setuptools/wheel; Twine and
  distribution/tag identity checks passed. The wheel installed into a separate
  temporary venv using cached extraction dependencies, passed `pip check`, and
  ran both CLI entrypoints, the demo and usage logging/summary outside the checkout.
  This is local package evidence, not a fresh network dependency-install test.
- Local documentation links, workflow YAML/embedded Bash syntax and diff whitespace
  passed. Static workflow checks verify draft creation and CI/artifact dependencies;
  they do not execute hosted Actions or change repository settings.

The automatic-collection follow-up passed the full **251-test** suite. It adds
project-scoped Codex snapshots and a continuous watcher, exercised against eight
actual local sessions and a bounded polling run. Repeated collection appended no
duplicate snapshots. Focused checks cover live-file tails, invalid counters,
concurrent writers, mixed models and separate fork sessions. The reader copies
no conversation text; a reviewed numeric report is linked above. The earlier
blanket statement that no host token data was accessible has been corrected.
The updated sdist/wheel also passed metadata checks; its installed collector and
bounded watcher passed outside the checkout with no broken dependencies.
Per-call attribution, all internal retries/images and actual billing remain open.

The native-adapter follow-up passed **273 tests**. It adds Claude transcript
discovery and native callbacks for Claude and Antigravity CLI, plus an Antigravity
headless launcher. A real CLI 1.4.2 run captured terminal usage (14,324 reported
input, 143 output, 137 thinking, no cache reads); a resumed TUI invoked the
configured callback and saved a distinct context-window snapshot. The rebuilt
sdist/wheel, metadata/dependencies and installed-wheel callbacks also passed
outside the checkout using generated payloads. Those counters
are not added together. The run also verifies project binding, metadata-only
persistence and repeated callback handling. Claude remains fixture/subprocess
verified and configured, not live tested. Both callback setup and tests preserve
existing display settings. This does not close the real-Claude, cross-host or
educational accuracy gates. See the numeric report linked above.

The educational runner compares captured judgments and exercises deterministic
core policy; no model/API is invoked by that runner or the polling/callback collectors. The
Antigravity measured launcher intentionally runs its requested host task.
Unknown billing has not become a zero-cost measurement.

## Stable publication decision

Tagged builds always prepare a draft, even if every CI job passes. Before a human
publishes it as stable, review this table against the exact candidate revision:

- All three actual hosts have recorded discovery, invocation, source-image and
  fresh-session evidence, with scoped host/version limitations.
- A real cross-host handover preserves attempt identity, submitted work and
  assistance, confirmed by receipts/history at both ends.
- Independently checked unseen submissions cover formulas, diagrams, ambiguous
  regions, alternate reasoning and versioned questions. Retain inaccurate
  judgments and critical failures; unresolved grading stays pending.
- A run records real provider usage where available, all calls/retries/images,
  reviewed outcomes and measured/estimated/unavailable billing separately.
  Unavailable billing may remain unavailable; it cannot support a cost claim.
- Core recovery, byte-identical originals, retrieval assumptions and uncertainty
  checks pass on the candidate. Existing local tests support these guarantees.

Link returned reports and date the decision here. A draft is reviewable while
these gates are open; it is not evidence that they passed. Stable publication is
a manual evidence decision. There is no bypass input that auto-publishes a stable
release when CI alone is green.
