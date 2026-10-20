# Course agent profiles

General course profiles live in `.codex/agents/` and `.claude/agents/`.
They apply to every subject and use the shared Lumen core. Obsolete imported
subject-specific profiles, skills and routing notes have been removed.

| Role | Model / reasoning | Responsibility |
|---|---|---|
| `course_lookup` | `gpt-6.1-sol` / low | Find existing questions, source metadata and history; no solving or writes |
| `course_practice` | `gpt-6.1-sol` / medium | Bounded practice, extraction review and routine checking of exact versions |
| `course_reasoning` | `gpt-6.1-sol` / high | A specifically unresolved proof, disputed key or substantive edge case |

Use one focused delegation when useful, with minimal source excerpts and explicit
ownership. Prefer direct execution for trivial work. Child agents do not spawn
more agents. The parent coordinates the writer, validates returned evidence, and
commits learner state using Lumen's public operations and receipts. A source key
is retrieved evidence, not an independently proved answer. Preserve the learner's
language and assistance preferences.

Choose a matching custom `agent_type` when the host exposes it. Otherwise read the
TOML and explicitly pass its model, effort and instructions with no full-history
fork. A task name alone does not establish the configured role. These optional
Codex profiles do not change the parent model or the shared assessment policy.

Standalone project profiles follow the [official custom-agent contract](https://learn.chatgpt.com/docs/agent-configuration/subagents).
File/schema validation and an actual lookup delegation are recorded separately
from claiming that a new Codex conversation hot-loaded the project copies.

## Claude Code profiles

Claude Code uses Markdown with YAML frontmatter in `.claude/agents/`, as specified
in [its native subagent format](https://code.claude.com/docs/en/sub-agents).
These share the responsibilities above and use Claude model aliases:

| Claude name | Model | Tools |
|---|---|---|
| `course-lookup` | `haiku` | Read, Glob, Grep, Bash for catalog/history queries |
| `course-practice` | `sonnet` | Read, Glob, Grep, Bash, Write, Edit for assigned artifacts |
| `course-reasoning` | `opus` | Read, Glob, Grep, Bash for focused verification |

The profiles preserve host permissions. Bash access is needed for Lumen CLI
queries; a read-only role instruction is not a filesystem security sandbox.
No profile creates a separate learner memory or assessment policy. Only the
assigned writer commits changes through the shared core. Restart an existing
Claude session after first adding `.claude/agents/`, then inspect available
profiles and perform an actual bounded lookup invocation. `/agents` is version-sensitive: older versions show an inspector,
while newer versions may show a reminder. Follow the [live test handoff](claude-handoff.md)
and capture installed-version behavior to confirm discovery. Claude Code is not
installed in this review environment, so native loading and delegation still
require a live smoke test.

## Shared skill layout

- `.agents/skills/<name>/SKILL.md` holds the canonical skill, discovered by Codex
  and supported Antigravity versions.
- `.claude/skills/<name>/SKILL.md` holds only matching discovery metadata and an
  explicit instruction to read the canonical skill before acting. Claude's native
  project discovery path is `.claude/skills`, not `.claude/.skills`.
- `docs/workflows/` holds the provider-neutral tutoring workflows; `docs/agents.md`
  remains the shared operating contract.


Both discovery directories are intentional, but workflow content is maintained
only once. Plain pointers avoid symlink checkout/archive portability issues.
When adding a shared skill, add its Claude pointer with the same name and
description; resolve the canonical skill's internal links from its own directory.
Do not copy full workflow instructions into provider folders. See
[Claude skill discovery](https://code.claude.com/docs/en/skills).
