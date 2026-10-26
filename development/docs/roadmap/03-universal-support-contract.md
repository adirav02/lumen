TL;DR: Verbatim legacy roadmap: 3. Universal support contract.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 3. Universal support contract

All required hosts access the same workspace and shared tool behavior. "Same workspace" means the same durable data location or an explicitly restored snapshot, not three independently diverging database copies.

### Instruction discovery

| Host | Initial entry point | Routing | Required verification |
|---|---|---|---|
| Codex | Root `AGENTS.md` | Instructs the agent to read `docs/agents.md` | Check applicable global/override instructions, working directory, instruction limits, and successful reading of the shared file |
| Claude Code | Root `CLAUDE.md` | Imports `@docs/agents.md` | Check import loading, memory/instruction settings, and the actual shared file in loaded context |
| Google Antigravity | Root `AGENTS.md` in documented current versions | Instructs the agent to read `docs/agents.md` | Check installed IDE/CLI version, active workspace rules, and successful reading of the shared file |

Current official documentation also describes additional host-specific rule locations and Claude's AGENTS.md fallback. Keep the explicit loaders above as the baseline. Do not install global rules or modify a user's global settings as part of ordinary workspace setup. If an installed version uses a different supported workspace rule mechanism, generate a thin local pointer and document/test it; do not silently duplicate the full policy.

The root Codex/Antigravity loader is an instruction to read the canonical file, not a claim that generic Markdown links are automatically expanded. Claude's `@` import is host-native. Long plans and course documents are not imported at every startup.

### Tool access

Implement a shared CLI with structured JSON input/output first. An optional MCP transport can expose the same operations where it improves integration. A host without CLI access may use a supported transport adapter; a host without either transport or durable storage is unsupported for persistent tutoring until configured.

Do not assume Bash, symlinks, Unix paths, lifecycle hooks, background processes, a particular model, or API credentials. Use Python filesystem/process interfaces and relative workspace paths. If a host can invoke the core but cannot display source images, report text capability separately from visual-source capability.

### Capability and conformance checks

Record host identity/version, shared contract version, SQLite runtime/features, instruction loading, core access, writable durable workspace, source-file access, image handling, and available extraction formats. Distinguish:

- verified by an actual host smoke test;
- implemented but not smoke-tested in that host;
- unavailable in the current environment.

For each of Codex, Claude Code, and Antigravity, the smoke test must open a fixture workspace, retrieve a cited unit, record an attempt, preserve assistance ordering, retry a write without duplication, pause/resume, correct evidence, and read the same committed state from another host. Also test access to a source-page image when visual support is claimed. Record deterministic core results separately from model-dependent grading differences.

Instruction presence alone does not constitute a passing integration test. Hooks may enhance reliability, but explicit core writes are the baseline persistence mechanism.

