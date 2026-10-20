TL;DR: Development task commands, file ownership and compact artifact contracts.
Status: active; date: 2026-10-19; based on commit: 935d1ab.

# Development conventions

Run from the repository root, using Python 3.10+ and stdlib-only helper scripts:

```sh
python3 scripts/sync_agents.py
python3 scripts/sync_agents.py --check
python3 scripts/new_task.py fix-slug
python3 scripts/task_status.py
python3 scripts/make_review_packet.py YYYYMMDD-fix-slug
python3 scripts/archive_task.py YYYYMMDD-fix-slug
python3 scripts/gen_repo_map.py
python3 scripts/gen_doc_index.py
python3 scripts/check_docs.py
.venv/bin/python scripts/run_tests.py tests/test_dev_tooling.py
```

## File and context rules

- `agents/` is the development role source; generated native profiles are copies.
- `docs/INDEX.md` is generated, one entry per docs file. Read only relevant docs.
- `work/<UTC-YYYYMMDD>-<slug>/` holds a task; only `_template/` is tracked.
- One writer per file. Manager owns status/handoff; assign plan, findings, changes
  and review explicitly. Shared changes.md requires serialized dev_worker writes.
- Pass paths, not content; return a path plus at most 5 lines. Use fresh contexts.
- Each Markdown file starts with TL;DR (at most 5 lines), then status/date; role
  YAML frontmatter precedes this header. Findings cite file:line and based-on commit/date.
- Cap all files at 150 lines, roles at 60, task plans at 120. Split with links.
  JSON/frontmatter/.gitkeep use their native syntax rather than invalid prose headers.
- Scripts generate metadata, indexes, maps and host copies. Never hand-edit generated files.
- Legacy docs are skipped by default `rg` searches; use `rg --no-ignore` to include them (regenerate `.rgignore` with `python3 scripts/check_docs.py --write-rgignore`).
- Existing docs listed in `scripts/legacy_docs.json` retain their original layout;
  only new docs/roles/task files must meet the new cap and header rules. The fixed
  baseline does not exempt new files. All docs, including legacy ones, stay indexed.
- Read-only roles may write their assigned report; dev_reviewer tests may create scratch
  artifacts. Tool labels are behavioral scope, not an operating-system sandbox.
- Manager is the main session. At task start write `mode: solo|delegated` and a
  one-line `reason` in status.json; default to solo when files are known and
  the brief has testable acceptance criteria.
- Use an explorer only for unfamiliar territory requiring more than about ten
  files of reading with a small returned result. Use dev_planner only for real
  design ambiguity or when several modules are affected. Use a reviewer for
  risky changes or at the end of a feature. Delegate only the needed roles.
- When the main context gets large, write handoff.md and continue in a fresh
  session instead of spawning agents to manage context.
- Two failed dev_worker attempts require replanning. Mark hard steps in task
  plan.md before medium reasoning.
- Run tests only through `scripts/run_tests.py` with the environment's Python;
  optional paths and `-k expression` target a run. Read `.tmp/test-last.log` only
  when the summary is insufficient. The wrapper preserves pytest's exit code.
- Turn caps are soft prompt instructions, including dev_explorer's 15; record actual
  turns in benchmarks. No native hard cap has been verified.
- Existing `docs/agents.md` remains the application/tutoring contract. This workflow
  adds development tooling only; it does not change runtime policies or learner state.
- Development roles are labeled in their descriptions and use task artifacts;
  course-* profiles remain separate and unchanged. The application does not load
  development profile files, and these helper scripts do not import its runtime.

## Benchmark measurement

Usage is collected externally after the run with the existing collector. Agents
never read or edit telemetry, usage or measurement files/tooling during a benchmark
task; measurement is outside their assignments. Preserve per-response identity and
task boundaries when aggregating main-session and subagent usage.

Append a row to [the usage log](evaluation/usage-log.md) after each measured task.

## status.json schema

All fields below are required; do not insert full findings or code into status.

| Field | Type / values |
|---|---|
| task_id | `YYYYMMDD-lowercase-slug` |
| title | short string |
| state | `planned`, `in_progress`, `review`, `done`, `blocked` |
| mode | `solo` (default) or `delegated` |
| reason | nonempty one-line explanation of the chosen mode |
| owner_role | `manager`, `dev_explorer`, `dev_worker`, `dev_planner`, `dev_reviewer` |
| host | host name or null until assigned |
| model | exact model ID or null until assigned |
| started_utc | UTC timestamp recorded by new_task.py |
| ended_utc | UTC timestamp recorded on archive, or null until finished |
| updated | ISO 8601 timestamp with timezone |
| based_on_commit | Git HEAD at creation; `unknown` outside a Git checkout |
| next_step | one short action |

Helpers assume one coordinator process per task/log. new_task refuses collisions;
archive requires `done` and `Verdict: PASS`, logs TL;DRs, then moves the directory.
The native usage collector uses started_utc/ended_utc as its default task window.
If interrupted after logging, retry deduplicates by task ID. Do not delete work
until its archive move succeeds. Task log rotation/index updates are generated.

## Review cost controls

- Manager runs the full suite once after implementation, generates
  `work/<id>/review-packet.md`, then supplies a complete fresh-context reviewer
  assignment: packet path, scope, touched contracts, acceptance and report ownership.
- Use one reviewer pass. Re-review only for high-severity findings (privacy, data
  integrity); scope it to the corrective diff, prior finding and touched contracts.
- Reviewer reads the packet first. Do not load general agents.md, INDEX.md,
  conventions.md or roadmap unless the packet points to a specific document/section.
- Success writes `.tmp/test-receipt.json`: HEAD, SHA256 of the working-tree diff
  including untracked files, passed count, UTC time, arguments and suite scope.
  Staged changes are included; ignored task artifacts/caches are excluded. A tree
  changed during testing is flagged. Failure removes prior successful evidence.
- A matching full-suite receipt prevents another full-suite run by the reviewer;
  run focused tests only through scripts/run_tests.py. Missing/stale evidence goes
  back to the manager for refresh. A focused receipt does not prove full coverage.
- Reviewer reports cover EVERY brief acceptance criterion in a yes/no table with
  evidence (test name or file:line), followed by findings.
- The packet contains brief TL;DR/numbered acceptance checklist, base-to-tree diff stat, receipt match
  and prior findings. It is at most 80 lines, with scoped references on overflow.
- Never poll commands: use blocking execution and, if yielded, one blocking wait
  for completion. Batch bounded inspection reads. Write review.md in one heredoc.
- Soft call targets: about 8 for first review and 5 for re-review; explain overruns.
