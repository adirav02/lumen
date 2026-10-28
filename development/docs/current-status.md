TL;DR: Local reliability candidate and explicit remaining educational/host gates.
Status: locally verified candidate; date: 2026-10-28.

# Current evidence

Candidate: uncommitted diff based on `634ca6be165d5ec9809259544fd1ebf8a67cd1fd`.
Verification on 2026-10-28: initial focused 24-test reliability run passed, including
real PDF reference re-export. Full-suite results and artifact hashes are in the
local report below. Baseline: Python 3.14.8, 785 passing tests, no skips.
The baseline wrapper warned about concurrent working-tree edits; its pass count
is observed execution evidence, not a matching final-tree receipt.

Implemented: reviewed source/version/part-bound local question references,
immutable assembly presentation snapshots, conservative whitespace span trimming,
catalog processor version 4, and local link/anchor checks on named active entry
points. Follow-up fixes preserve structured manual subparts, scope references by
source part, and omit extractor-confirmed empty pages. Source materials and accepted historical catalogs stay unchanged.

Fresh HN101 solo evidence and final commands are recorded locally in
`development/work/20261028-reliability-20261028/report.md`; this ignored private
report is deliberately not a Markdown link in public navigation.

Remaining release gates:

- Live Claude Code discovery, invocation, source image access and resume: not run.
  Use [the current live-host handoff](live-host-handoff.md) on a host with Claude.
- Bounded same-machine Codex → Antigravity 1.4.7 handover: verified on an
  isolated restored synthetic attempt. Earlier independent work and hint IDs were
  preserved; new work was assisted. Actual CLI/tool streams and post-state are in
  the private task. Antigravity core invocation and source-image access also ran.
  Native discovery is host-reported; the final resume invocation timed out after
  its successful core write, before a second image read/final response completed.
  Claude routes, other machines and the full host matrix remain open.
- Independent unseen educational evaluation: open. Solo recomputation and PDF
  review are local evidence, not an independent held-out assessment.
- Usage/billing completeness: open. Dedicated project-matched session snapshots
  include prior session counters; they are not per-task or billing totals.

Dependabot PR #1 remains separate maintenance. No commits, pushes, merges,
remote-setting changes or releases are part of this candidate.
