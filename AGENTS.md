TL;DR: Shared project loader and compact development workflow entry point.
Status: active; date: 2026-10-19.

# Project instructions loader

Before working on this project, read and follow [docs/agents.md](docs/agents.md).
It is the canonical shared instruction file for this project. Use `goal.md` for
product requirements when needed. For roadmap context, load only
[docs/roadmap/INDEX.md](docs/roadmap/INDEX.md) by default; open individual parts
only when the task needs their historical milestones or implementation detail.

## Development workflow

Start at [docs/INDEX.md](docs/INDEX.md). The main session is the manager
(`agents/manager.md`); never spawn a manager. Keep one writer per file.
Each task lives in `work/<task-id>/`. At task start, write `mode: solo|delegated`
and a one-line `reason` in `status.json`; default to solo when files are known
and the brief has testable acceptance criteria.

Use an explorer only for unfamiliar territory requiring more than about ten files
of reading and a small returned result. Use dev_planner only for real design
ambiguity or when several modules are affected. Use a reviewer for risky changes or
at the end of a feature. Delegate only the roles needed. When used, the planner
writes `plan.md` before implementation. Keep one writer per file.
Pass artifact paths, not content; each subagent returns a path plus at most five
lines. After two failed worker attempts, replan. When the main context gets large,
write `handoff.md` and continue in a fresh session instead of spawning agents to
manage context. Use one reviewer pass; re-review only for high-severity findings,
scoped to the corrective diff and touched contracts. Details: `docs/conventions.md`.

Run tests only through `scripts/run_tests.py`, with the environment's Python.
Read `.tmp/test-last.log` only when the compact summary is insufficient.

## Verified Development Commands

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/lumen capabilities
.venv/bin/python scripts/run_tests.py
.venv/bin/python demo.py
python3 scripts/sync_agents.py --check
python3 scripts/check_docs.py
```

<!-- AGENTS:BEGIN -->
<!-- GENERATED from agents/ - edit the source -->
TL;DR: Development-only roles; manager is the main session.
Status: generated; date: 2026-10-19; source: be25cc0eee8d.

| Role | Model | Reasoning | Soft turns | Source |
|---|---|---|---|---|
| dev_explorer | gpt-5.6-terra | low | 15 | agents/dev_explorer.md |
| dev_worker | gpt-6.1-sol | low | 20 | agents/dev_worker.md |
| dev_planner | gpt-6.1-sol | high | 10 | agents/dev_planner.md |
| dev_reviewer | gpt-6.1-sol | medium | 8 | agents/dev_reviewer.md |
| manager | gpt-6.1-sol | medium | 30 | agents/manager.md |

These roles develop the repo; tutoring uses the separate course-* profiles.
Read agents/manager.md for main-session routing; never spawn a manager.
dev_worker medium reasoning requires an explicitly hard task-plan step and host override.
Claude native reasoning/model acceptance and AGY: see docs/dev-hosts.md.
<!-- AGENTS:END -->