TL;DR: Verbatim legacy roadmap: 14. Documentation references.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 14. Documentation references

Checked on 2026-10-09. These references establish documented file discovery or technical behavior, not completed runtime conformance for this project. Re-check them when implementing against an installed version.

- [Codex project instructions](https://developers.openai.com/codex/agent-configuration/agents-md): native AGENTS.md discovery and override behavior.
- [Claude Code memory and imports](https://code.claude.com/docs/en/memory): CLAUDE.md and relative `@path` imports; instruction settings can affect loading.
- [Google Antigravity rules](https://antigravity.google/docs/rules/): documented workspace rule locations, including AGENTS.md in current IDE/CLI versions.
- [SQLite FTS5](https://www.sqlite.org/fts5.html): full-text indexing and BM25.
- [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html): connection-level enforcement.
- [SQLite backup API](https://www.sqlite.org/backup.html): consistent database snapshots.
- [SQLite WAL](https://www.sqlite.org/wal.html): concurrency, runtime considerations, and network filesystem constraints.
- [Context-efficient tool execution](https://www.anthropic.com/engineering/code-execution-with-mcp): filter and process data before returning it to the model.

