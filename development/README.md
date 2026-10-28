TL;DR: Developer setup, workflow, verification and historical roadmap navigation.
Status: active; date: 2026-10-26.

# Development

See [current verified status](docs/current-status.md).

From the repository root:

```sh
python3 development/scripts/bootstrap.py
.venv/bin/lumen capabilities
python3 development/scripts/new_task.py my-task
.venv/bin/python development/scripts/run_tests.py
.venv/bin/python demo.py
python3 development/scripts/sync_agents.py --check
python3 development/scripts/check_docs.py
python3 development/scripts/gen_doc_index.py --check
python3 development/scripts/gen_repo_map.py --check
python3 development/scripts/check_roadmap.py
```

Read the [shared instructions](../docs/agents.md), [main-session workflow](agents/manager.md)
and [conventions](docs/conventions.md). Tasks run solo unless explicitly delegated.
See [dependency setup](docs/dependency-bootstrap.md) for offline wheelhouse options.

| Location | Purpose |
|---|---|
| [agents/](agents/manager.md) | Main-session workflow and host configuration |
| [work/_template/](work/_template/brief.md) | Shared task template; local task instances are ignored |
| [bench/](bench/README.md) | Development benchmarks; educational fixtures remain in examples/tests |
| [docs/INDEX.md](docs/INDEX.md) | Architecture, conventions, core contracts and implementation status |
| [docs/reports/](docs/reports/) | Preserved audits, handoffs, integration and verification evidence |
| [docs/roadmap/INDEX.md](docs/roadmap/INDEX.md) | Historical milestone status and navigation; open parts only on demand |
| [archive/](archive/) | Historical development profiles and material |
| [scripts/](scripts/) | Task, indexing, testing, synchronization and packaging tools |
| [goal.md](goal.md) | Product requirements, preserved verbatim |

Application usage, course organization and tutoring workflows remain in [docs/](../docs/README.md).
The course collection importer stays at `scripts/import_course_collection.py` for
existing course workflows; application source and installed packages do not depend
on this development directory. Course examples and educational fixtures stay in place.
Native host discovery remains in `.agents/`, `.claude/` and `.codex/`.

Historical evidence and product requirements preserve their original bytes. Paths
quoted in those documents describe their original repository layout; use this map
and the generated indexes for current locations. The old root `plan.md` navigation
is consolidated into the roadmap link above. Numbered roadmap parts are guarded by
the original SHA-256, Git blob and line-count checks.

Build and verify distributions from the root (use an empty output directory):

```sh
.venv/bin/python development/scripts/build_public.py
.venv/bin/python -m twine check dist/*
.venv/bin/python development/scripts/check_release_version.py
.venv/bin/python development/scripts/smoke_installed.py --wheel dist/*.whl
```

The installed smoke needs runtime dependency wheels or package-index access.
See [distribution verification](docs/conventions.md#distribution-verification).
