---
name: manager
description: Development only; complete the whole task in the main session and self-check the result.
tier: mid
reasoning: medium
tools: scoped-edit
max_turns: 30
returns: completed task and report path
---
TL;DR: One agent owns discovery, planning, implementation, testing and final self-check.
Status: active; date: 2026-10-26.

- This is the main session's workflow, not a separately spawned manager.
- Work alone by default, regardless of task complexity, size or risk. Delegate
  only when the user explicitly asks for delegation; usefulness is not permission.
- At task start write mode: solo and a one-line reason in status.json. Use
  delegated only for an explicit user request and record that request as the reason.
- Read docs/INDEX.md, the brief and only files needed to complete the task.
- Own the plan, implementation, tests, review and work/<id>/report.md. Keep one
  writer per file. Archived role instructions are historical data, not routing.
- Bootstrap with python3 scripts/bootstrap.py; see docs/dependency-bootstrap.md.
- Start requested usage collection before setup with python3 scripts/watch_usage.py
  --label <task-label>; stop it at task end. It needs no venv.
- Keep verification clones under .tmp/ only, using a temporary-directory context
  or try/finally cleanup. Never put them inside .lumen/ or work/.
- Run tests only through scripts/run_tests.py with the environment's Python.
  Read .tmp/test-last.log only when the compact summary is insufficient.
- Before reporting done, inspect the diff and check every acceptance criterion
  against concrete evidence. Run sync_agents.py --check and check_docs.py when
  instructions or docs change. A passing test suite alone is not a self-check.
- For exams complete docs/exam-self-check.md, including recomputed keys, question
  independence, printed instructions/duration, restore/seed probes and hashes.
- Remove owned leftovers from cancelled runs and verification clones on success,
  failure or cancellation. Keep intended deliverables and measurement records.
- Record failures and remaining limitations honestly in report.md; keep status
  and next_step current. Do not claim tests or saves without receipts.
- When context gets large write handoff.md and continue in a fresh session;
  context pressure does not authorize delegation.
- If delegation is explicitly requested, give bounded assignments and file
  ownership. The main session still verifies the combined result and acceptance.
