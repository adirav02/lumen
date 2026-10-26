TL;DR: One agent completes each task, records evidence and self-checks before reporting done.
Status: active; date: 2026-10-26.

# Development conventions

Run from the repository root with Python 3.10+:

```sh
python3 scripts/watch_usage.py --label my-task
# In a separate terminal; stop the watcher with Ctrl-C after the task:
python3 scripts/bootstrap.py
python3 scripts/new_task.py fix-slug
.venv/bin/python scripts/run_tests.py
python3 scripts/sync_agents.py --check
python3 scripts/check_docs.py
```

The watcher needs no venv or installed dependencies. Bootstrap uses local cached
wheels offline by default; see [dependency setup](dependency-bootstrap.md).

## Ownership and context

- One agent owns discovery, planning, implementation, tests, review and report.
  Delegate only when the user explicitly asks for delegation. Complexity, risk,
  unfamiliar files or context pressure do not authorize spawning another agent.
- `agents/manager.md` is the main-session workflow; never spawn a manager.
  Four historical development profiles live in `archive/delegated-agents/`.
  Sync deploys none to Codex, Claude Code or AGY. Course profiles are optional
  for explicit delegation requests, not automatic subject routing.
- At task start write `mode: solo` and a one-line reason in status.json. Record an
  explicit user delegation request in the reason before using delegated mode.
- One writer per file. If delegation is explicitly requested, assign bounded
  responsibilities and paths; the main session verifies the combined result.
- `work/<UTC-YYYYMMDD>-<slug>/` holds the task; only `_template/` is tracked.
  Write a brief, optional plan, self-check in review.md and final report.md.
- Read only needed docs via `docs/INDEX.md`. When context gets large, write
  handoff.md and continue in a fresh session without spawning a context helper.
- Each new Markdown file starts with TL;DR (at most 5 lines), then status/date;
  role YAML frontmatter precedes this header. Cite file:line and revision/date.
- Cap files at 150 lines, active role files at 60 and task plans at 120.
- Scripts generate metadata, indexes, maps and host sections. Edit their sources.
- Legacy docs keep their layout under `scripts/legacy_docs.json`. They remain
  indexed but are skipped by default searches via generated `.rgignore`.
- Existing `docs/agents.md` remains the shared application/tutoring contract.
  Development tooling does not change runtime policies or learner state.

## Verification and cleanup

- Run tests only through `scripts/run_tests.py` with the environment's Python.
  Optional paths and `-k expression` target a run. Read `.tmp/test-last.log` only
  when the summary is insufficient. The wrapper preserves pytest's exit code.
- Before reporting done, inspect the final diff and check every acceptance
  criterion with evidence. Record exact checks and limitations in report.md.
- For exam tasks complete [the exam self-check](exam-self-check.md), including
  source/blueprint structure, recomputed keys, independence, printed instructions
  and duration, no source numbering, restored-clone and seed probes, original
  hashes and cancelled-run cleanup. Tests alone do not establish exam quality.
- Verification clones belong only under gitignored `.tmp/`, never `.lumen/` or
  `work/`. Use a temporary-directory context or try/finally and delete them at
  the end even on failure/cancellation. Remove only owned cancelled-run files;
  preserve intended deliverables and measurement records.
- `check_docs.py` ignores `.tmp/` scratch trees, including nested copies.
- Successful tests write `.tmp/test-receipt.json` with HEAD, working-tree hash,
  pass count, time, arguments and scope. Changed trees or focused runs do not
  establish full-suite coverage. Refresh only when changes require it.
- `scripts/make_review_packet.py <id>` remains an optional compact evidence tool
  for self-check or an explicitly requested external review, not a spawn trigger.

## Benchmark measurement

Use the existing collector and preserve response identity and task boundaries.
When a benchmark excludes measurement work from the assignment, leave that work
to the external harness. An explicit request to start/stop collection or repair
measurement tooling authorizes that work. Do not invent unavailable costs.
Append a row to [the usage log](evaluation/usage-log.md) after a measured comparison.

## status.json schema

| Field | Type / values |
|---|---|
| task_id | `YYYYMMDD-lowercase-slug` |
| title | short string |
| state | `planned`, `in_progress`, `review`, `done`, `blocked` |
| mode | `solo` (default); `delegated` only on explicit user request |
| reason | nonempty one-line explanation; identify delegation request if applicable |
| owner_role | `manager` for the main session; historical role labels remain readable |
| host / model | host name / exact model ID or null until assigned |
| started_utc | UTC timestamp recorded by new_task.py |
| ended_utc | UTC timestamp on completion/archive, or null until finished |
| updated | ISO 8601 timestamp with timezone |
| based_on_commit | Git HEAD at creation; `unknown` outside a checkout |
| next_step | one short action |

Helpers assume one coordinating process per task/log. new_task refuses collisions;
archive requires `done` and `Verdict: PASS` from the main agent's self-check, logs
TL;DRs, then moves the directory. Native usage collection uses started_utc/ended_utc
as its default task window. Retry deduplicates task IDs after interrupted logging;
do not delete work until its archive move succeeds.
