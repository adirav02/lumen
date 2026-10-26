TL;DR: Verbatim legacy roadmap: 1. Deliverables and document precedence.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 1. Deliverables and document precedence

| File | Purpose |
|---|---|
| `goal.md` | Product outcomes, fixed requirements, scope, and release criteria |
| `plan.md` | Architecture, proposed contracts, milestones, and acceptance checks |
| `docs/agents.md` | Canonical operating instructions for implementation and tutoring |
| `AGENTS.md` | Short native loader for Codex and supported Antigravity versions |
| `CLAUDE.md` | Native Claude Code loader importing the canonical instructions |

The requested lowercase `agents.md` lives in `docs/`. Keeping it separate from root `AGENTS.md` avoids a case-only filename collision on case-insensitive filesystems. Extract the complete package and open its project root to retain the loaders. If only the three requested files are copied, instruction discovery must be configured explicitly; lowercase `agents.md` alone is not a portable automatic-loading guarantee.

Host/system instructions and explicit user directions keep their normal precedence. Within this project, use `goal.md` for requirements, this plan for implementation, and `docs/agents.md` for operating behavior. When approved scope changes, update all affected documents. Do not resolve contradictions by adding a different rule to a provider wrapper.

