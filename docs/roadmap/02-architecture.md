TL;DR: Verbatim legacy roadmap: 2. Architecture.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 2. Architecture

Use a local Python core and a SQLite database per learner workspace containing multiple courses. Keep course data separate from code and native instruction files. Original sources, student attachments, and derived image assets are immutable files referenced by the database. FTS5 and topic-state projections are rebuildable derived data.

| Component | Owns |
|---|---|
| Shared instructions | Tutor behavior, development rules, and truthful reporting |
| Host adapter | Instruction discovery, invoking tools, passing stable request IDs, and exposing files/images |
| Shared core | Validation, migrations, source registration, retrieval, attempts, evidence, assessment policy, backup, and export |
| SQLite | Processed knowledge, versions, attempts, evidence, preferences, operation receipts, and derived state |
| Immutable file store | Exact originals, submitted images, and generated assets with content hashes |

Adapters must not contain independent grading policies, mastery calculations, storage schemas, or private copies of learner state. The host model interprets and teaches; ordinary code performs filtering, aggregation, persistence, and policy computation.

### Proposed code organization

| Path | Responsibility |
|---|---|
| `src/course_tutor/` | Shared core and CLI |
| `src/course_tutor/storage/` | Connections, migrations, repositories, transactions, and backups |
| `src/course_tutor/ingestion/` | Format handlers, extraction checkpoints, provenance, and validation |
| `src/course_tutor/retrieval/` | FTS5, topic aliases, dependency expansion, and result formatting |
| `src/course_tutor/learning/` | Attempts, evidence correction, diagnostic blueprints, and policy projections |
| `src/course_tutor/adapters/` | Host capability and transport integration only |
| `tests/` | Storage, retrieval, educational fixtures, and adapter contract tests |
| `docs/` | Shared instructions and detailed references loaded on demand |

The delivered package uses `src/course_tutor/` with `api.py`, `cli.py`, and modules for storage, ingestion, retrieval, learning, assessment, questions, backup, and usage measurement. `src/lumen/` preserves the public package alias. The table above is the architectural grouping, not a literal current tree; split modules when the responsibility exists. No server, vector database, agent fleet, or custom chat interface is required for the initial implementation.

