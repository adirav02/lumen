---
name: manager
description: Development only; coordinate the main session using compact task state and references.
tier: mid
reasoning: medium
tools: scoped-edit
max_turns: 30
returns: artifact paths plus at most 5 lines
---
TL;DR: This is the main session's instruction set, not a separately spawned agent.
Status: active; date: 2026-10-19.

- For delegated work, hold the approved plan and read task status.json plus
  subagent summaries; for solo work inspect the files needed for implementation.
- Resume from brief + status + handoff only; do not load broad code or documents.
- At task start, write `mode: solo|delegated` and a one-line `reason` in
  status.json. Default to solo when files are known and the brief has testable
  acceptance criteria; routine or obvious changes stay inline.
- Use an explorer only for unfamiliar territory requiring more than about ten
  files of reading with a small returned result.
- Use dev_planner only for real design ambiguity or when several modules are
  affected; use a reviewer for risky changes or at the end of a feature.
- When the main context gets large, write handoff.md and continue in a fresh
  session instead of spawning agents to manage context.
- Give each subagent a complete assignment up front: named inspection files/directories,
  bounded questions, ownership, acceptance checks and output path. Use fresh contexts.
- Do not send scope-expanding follow-ups or "finish promptly" messages.
- Use one long blocking wait for subagents; never poll with repeated short waits.
- Collect benchmark usage externally after the run with the existing collector;
  agents must not read or edit measurement tooling during benchmark tasks.
- Assign one writer per file, including task artifacts. Own status.json and handoff.md.
- dev_planner runs once unless replanning is requested. After two failed dev_worker
  attempts on a step, return it to the dev_planner before trying again.
- Workers default to low reasoning; request medium only for a step marked hard
  in work/<id>/plan.md. Report an unsupported host override rather than guessing it.
- Before delegating review, run the full suite once at the end, then generate
  `review-packet.md` with `scripts/make_review_packet.py <task-id>`.
- Spawn a fresh-context dev_reviewer with a complete assignment: packet path,
  scope, touched contracts, acceptance checks and report ownership. Never spawn a manager.
- Use one reviewer pass. Re-review only for high-severity findings such as
  privacy or data integrity; scope it to the corrective diff, prior finding and
  touched contracts. Do not reopen the full task.
- Keep state and next_step current; do not claim tests or saves without receipts.
- Keep all returns to paths plus at most 5 lines. Follow docs/conventions.md.

- Run tests only through `scripts/run_tests.py` with the environment's Python.
  Read `.tmp/test-last.log` only when the summary is insufficient.
