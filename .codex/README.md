# Codex Integration for Lumen

## Project Overview & Setup

Lumen is an evidence-based course tutor and learning assistant implemented in Python and SQLite.
It exposes a local command-line interface (`lumen`) and operates without external paid API keys.

### Files Loaded by Codex

Codex loads the following workspace configuration and instruction files:
1. **`AGENTS.md`** (Project Root): Canonical entry loader pointing to `docs/agents.md`.
2. **`.agents/skills/lumen/SKILL.md`**: Native Lumen tutoring skill providing progressive workflow instructions.
3. **`.codex/config.toml`**: Project configuration inheriting user preferences without overriding sandboxing or approvals.

### Trust & Sandboxing Requirements

- Lumen executes local CLI commands (`lumen <operation>`) inside the project environment.
- Writable workspace access is needed for SQLite database creation (`lumen.db`) and content-addressed original storage (`originals/`).
- No elevated root permissions, cloud services, or network listeners are required.
- Do not disable Codex approvals or sandboxing.

### Verified Commands

```bash
# Verify environment and capabilities
.venv/bin/lumen capabilities

# Run full automated test suite
.venv/bin/pytest
```

### Course profiles

The three project-scoped profiles are in `.codex/agents/`:
`course_lookup`, `course_practice`, and `course_reasoning`.
See [profile responsibilities and routing](../docs/agent-profiles.md).
They use the shared Lumen workflows and SQLite history for any course.
User-level configuration belongs to other projects and is not imported here.
