TL;DR: Shared project loader and compact development workflow entry point.
Status: active; date: 2026-10-19.

# Project instructions loader

Before working on this project, read and follow [docs/agents.md](docs/agents.md).
It is the canonical shared instruction file for this project. Use `goal.md` for
product requirements when needed. For roadmap context, load only
[docs/roadmap/INDEX.md](docs/roadmap/INDEX.md) by default; open individual parts
only when the task needs their historical milestones or implementation detail.

## Development workflow

Start at [docs/INDEX.md](docs/INDEX.md) and [the main-session workflow](agents/manager.md).
One agent does discovery, planning, implementation, tests and self-check by default.
Delegate only when the user explicitly asks for delegation. Complexity or risk does
not authorize spawning a reviewer or another agent. Archived profiles are inactive.

Each task lives in `work/<task-id>/`. At task start write `mode: solo` and a one-line
`reason` in `status.json`; use delegated only for an explicit user request.
Before reporting done, check every acceptance criterion and write `report.md`.
For exam creation follow [the end-of-task self-check](docs/exam-self-check.md).
Keep verification clones under `.tmp/` and delete them at the end, including failures.
Details: [docs/conventions.md](docs/conventions.md).

Run tests only through `scripts/run_tests.py`, with the environment's Python.
Read `.tmp/test-last.log` only when the compact summary is insufficient.

## Verified Development Commands

```bash
python3 scripts/bootstrap.py
.venv/bin/lumen capabilities
.venv/bin/python scripts/run_tests.py
.venv/bin/python demo.py
python3 scripts/sync_agents.py --check
python3 scripts/check_docs.py
```

<!-- AGENTS:BEGIN -->
<!-- GENERATED from agents/ - edit the source -->
TL;DR: One agent completes the whole task by default.
Status: generated; date: 2026-10-19; source: 8eefa55adb32.

Read agents/manager.md for the main-session workflow.
Delegate only when the user explicitly asks for delegation.
Development subagent profiles are preserved in archive/delegated-agents/.
sync_agents.py deploys no Codex, Claude Code or AGY development subagents.
<!-- AGENTS:END -->