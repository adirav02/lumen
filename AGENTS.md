TL;DR: Shared project loader and compact development workflow entry point.
Status: active; date: 2026-10-19.

# Project instructions loader

Before working on this project, read and follow [docs/agents.md](docs/agents.md).
It is the canonical shared instruction file for this project. Use `development/goal.md` for
product requirements when needed. For roadmap context, load only
[development/docs/roadmap/INDEX.md](development/docs/roadmap/INDEX.md) by default; open individual parts
only when the task needs their historical milestones or implementation detail.

## Development workflow

Start at [development/README.md](development/README.md) and [the main-session workflow](development/agents/manager.md).
One agent does discovery, planning, implementation, tests and self-check by default.
Delegate only when the user explicitly asks for delegation. Complexity or risk does
not authorize spawning a reviewer or another agent. Archived profiles are inactive.

Each task lives in `development/work/<task-id>/`. At task start write `mode: solo` and a one-line
`reason` in `status.json`; use delegated only for an explicit user request.
Before reporting done, check every acceptance criterion and write `report.md`.
For exam creation follow [the end-of-task self-check](docs/exam-self-check.md).
Keep verification clones under `.tmp/` and delete them at the end, including failures.
Details: [development/docs/conventions.md](development/docs/conventions.md).

Run tests only through `development/scripts/run_tests.py`, with the environment's Python.
Read `.tmp/test-last.log` only when the compact summary is insufficient.

## Verified Development Commands

```bash
python3 development/scripts/bootstrap.py
.venv/bin/lumen capabilities
.venv/bin/python development/scripts/run_tests.py
.venv/bin/python demo.py
python3 development/scripts/sync_agents.py --check
python3 development/scripts/check_docs.py
```

<!-- AGENTS:BEGIN -->
<!-- GENERATED from development/agents/ - edit the source -->
TL;DR: One agent completes the whole task by default.
Status: generated; date: 2026-10-19; source: 48c849e5f0f6.

Read development/agents/manager.md for the main-session workflow.
Delegate only when the user explicitly asks for delegation.
Development subagent profiles are preserved in development/archive/delegated-agents/.
sync_agents.py deploys no Codex, Claude Code or AGY development subagents.
<!-- AGENTS:END -->