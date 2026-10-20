TL;DR: Repository boundaries and where to find implementation knowledge.
Status: scaffold overview; date: 2026-10-19; based on commit: 935d1ab.

# Repository architecture

Product requirements remain in [goal.md](../goal.md); implementation milestones
remain in [plan.md](../plan.md). This overview does not redefine either contract.

- `src/course_tutor/` contains the shared Python application core and CLI.
- `src/lumen/` exposes the public Lumen package alias.
- `tests/` contains pytest checks; new workflow checks import only dev helpers.
- `examples/` contains demonstrations, fixtures and course evidence.
- `.agents/skills/` and `.claude/skills/` contain existing tutoring discovery files.
- Existing `.codex/agents/course-*` and `.claude/agents/course-*` are tutoring roles.
- `agents/` defines separate development roles; `scripts/sync_agents.py` generates
  their host copies without replacing the course roles or host settings.
- `work/_template/` defines task artifacts; task instances are local and ignored.
- `docs/` holds shared contracts, evidence and development guidance. Start with
  [INDEX.md](INDEX.md), then consult the [generated map](repo-map.md) as needed.

Development helpers use Python stdlib and filesystem/Git metadata. They neither
import application modules nor read/write learner databases. No service, package
dependency, runtime behavior change or new application architecture is introduced.
