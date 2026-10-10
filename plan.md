# Course Tutor — Implementation Plan

Updated: 2026-10-09.  
Status: specification only. Runtime, database schema, extraction pipeline, and host adapters are not implemented yet.  
Fixed decisions: SQLite; preserved original files; evidence-based assessment; one shared core for Codex, Claude Code, and Google Antigravity.

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

These paths are proposed, not files already delivered. Start with a small package; split modules when the responsibility exists. No server, vector database, agent fleet, or custom chat interface is required for the initial implementation.

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

## 4. Source preservation and course ingestion

### Original files

- Store the exact uploaded bytes before registering a committed reference to them.
- Retain original name, MIME/format, size, SHA-256, logical source ID, source version, upload time, and a relative managed path.
- Use content identity to avoid reprocessing identical bytes uploaded under another name. Keep aliases/upload history distinct from content versions.
- Different content under the same filename creates a new version; do not overwrite the old file.
- Copy through a staging path, verify content, and publish to the managed store before the database refers to the final file. Recover orphaned staged files without deleting referenced originals.
- Store images and derived crops with links to their source version, page index, and region. Source-page index and printed page label are separate fields.

Source-derived units can have multiple provenance entries. Generated explanations, instructor corrections, and generated questions carry explicit origin labels. Faithful extraction does not establish that a statement or reference solution is mathematically correct; track extraction fidelity separately from reference validation.

### Ingestion flow

1. Create/select the course; accept syllabus, lectures, slides, exercises, and optional exams/solutions.
2. Register originals and detect extraction capabilities. Process usable inputs while keeping unsupported inputs available and visibly pending.
3. Extract full page/slide content with locators. Preserve formulas, tables, and diagrams; use a vision/OCR path for uncertain regions when available.
4. Build a course map from supplied material. Treat missing syllabus topics and uncertain mappings as explicit gaps, not inferred coverage.
5. Create semantic units: definition, theorem, formula, method, example, table, or figure. Each mathematical unit retains assumptions, symbol definitions, exceptions, and required dependencies.
6. Validate fidelity against the source where necessary; publish valid units and pending-review items with distinct statuses.
7. Update active-version FTS5 indexes and produce a concise coverage/quality report.

Checkpoint per source version and extraction stage. Cache results by content hash and processor version. New content or a changed processor can be evaluated without discarding checked prior versions. Do not process all files with a model by default if local extraction is sufficient; do not claim local extraction handles every scan.

Source changes identify affected knowledge units, reference solutions, and evidence. Cosmetic changes do not automatically invalidate learner evidence. Changes to assumptions or answers mark dependent evaluations for review, preserving the original assessment history.

## 5. Data model

Implement versioned migrations and enable foreign keys on every connection. Enforce course boundaries with composite constraints or equivalent validated relationships. Keep commonly filtered fields as columns; use JSON for bounded flexible detail, not for one whole-course blob.

| Entity or table group | Required information |
|---|---|
| `courses` | Name, scope, language/notation settings, active state, and course revision |
| `sources`, `source_versions` | Logical source, immutable content identity/path, role, active version, and extraction status |
| `topics`, `topic_links` | Course-scoped hierarchy, aliases, and prerequisites |
| `knowledge_units`, `unit_provenance`, `unit_topics` | Full content, summary, kind, assumptions, symbols, dependencies, origin, versions, locators, and fidelity status |
| `exercises` and versioned definitions | Question/subparts, exercise family, topic/skill mapping, reference solution, rubric version, and validation state |
| `attempts`, `attempt_events` | Exercise version, mode, status, ordered observed submissions, assistance, references, and current revision |
| `evidence` | Skill/subpart, observed fragment/event, correctness, prior assistance, evaluator/reference provenance, and correction/retraction history |
| `assessments`, `assessment_items` | Coverage blueprint, selected question versions, attempts, rubric points, exposure, and progress |
| `topic_state` | Rebuildable projection from active evidence with policy version and last included event |
| `learner_settings` | Teaching preference, chosen language, and explicit goals; not evidence of ability |
| `operation_receipts` | Stable request ID, canonical request hash, and committed response |

Use stable IDs; enforce uniqueness for a logical observation and assessed skill, not merely for a freshly generated request ID. Corrections reference prior evidence and remain auditable. Full transcript storage is not required; preserve the actual observed work needed to explain judgments, including attachments and meaningful assistance events.

FTS5 is derived from active searchable content. Update it with content publication or use a controlled rebuild with a revision check. An index rebuild cannot alter learner evidence.

## 6. Shared tool contract

The operation names below are proposed API names, not currently executable commands. Version the envelope and validate both requests and results.

Every course operation has an explicit workspace/course scope. Mutations include a stable `request_id` and, for changes to existing work, an expected revision. The adapter/core retains a pending operation's ID before execution and reuses it on retry. Same ID with different canonical content is a conflict; same committed request returns its receipt.

| Operation | Input focus | Output focus |
|---|---|---|
| `capabilities` | Workspace/host | Available features and verified persistence access |
| `create_course`, `ingest_source` | Course settings or original-file reference | Course/source version, progress, pending regions |
| `course_brief` | Course, session mode | Preferences, open attempt, observed coverage, a few useful next actions |
| `search` | Query, topic/source filters, detail/budget target | Unit IDs, short descriptions, provenance, explicit continuation |
| `read_units`, `read_source_region` | Unit IDs/dependencies or exact source locator | Complete required content or source region and fidelity status |
| `start_attempt`, `record_attempt_event` | Exercise version, mode, observed work/assistance | Attempt revision and committed event ID |
| `commit_evidence` | Evidence tied to committed events and checked reasoning | Active evidence and affected topic projection |
| `correct_evidence` | Prior evidence, correction, reason, reference version | Correction record and recomputed affected states |
| `pause_attempt`, `resume_attempt` | Attempt and expected revision | Durable checkpoint; unassessed parts remain unassessed |
| `create_assessment`, `assessment_progress` | Coverage blueprint or assessment ID | Selected items, known exposure, progress, observed score and coverage |
| `export_workspace`, `backup_workspace`, `restore_workspace` | Destination or snapshot | Consistent data/source manifest and validation result |

A committed mutation returns a receipt with request ID, affected IDs, and revisions. Responses distinguish committed, pending review, conflict, and failed states. A tool must not truncate a knowledge unit silently or imply that absent results prove the course lacks the concept.

Do not hold write transactions across model calls or extraction. Commit evidence, attempt changes, operation receipt, and affected topic projections consistently. Raw attempt events may be saved before evaluation; after interruption, show them as awaiting review. Respect business revisions even when SQLite serializes writes.

Use short transactions and bounded lock retries. Rollback journaling is sufficient initially; enable WAL only when the access pattern benefits and the installed runtime is appropriate. Neither mode makes live multi-machine file synchronization a supported architecture.

## 7. Retrieval and token efficiency

Start with FTS5/BM25, course/topic/source filters, and a multilingual alias map. BM25 is a lexical ranking score, not a probability of relevance or truth. Keep formula text unchanged; any search normalization is derived data. Evaluate Hebrew phrasing and math notation explicitly.

Load compact context at session startup. Retrieve metadata first, then complete relevant units and their necessary dependencies. Expand to another unit or original page when the retrieved material is insufficient, contradictory, or uncertain. Do not enforce a fixed top-k or token cap that drops a required assumption.

Filter and aggregate in code before returning data. Update only changed records; avoid rereading the entire course or rewriting all learner history. Cache by content/policy revision and invalidate on relevant changes. Use clear text for explanations and compact structured payloads for operations; measure formats with actual content before adopting TOON or another encoding.

Measure total cost per correct completed task, including prompts, tool schemas/results, follow-up calls, vision/OCR, retries, and output. Distinguish provider-reported usage from tokenizer estimates and actual billed cost. Unknown billing data stays unknown. Token counts from different tokenizers are not interchangeable monetary costs.

Semantic search, reranking, or provider-specific prompt caching enters the plan only after a measured retrieval or cost problem justifies it.

## 8. Tutoring and evaluation

Persist the ordered sequence of submitted work and assistance, at meaningful steps rather than only at exercise completion. Record what the learner demonstrably did, not what the tutor infers they probably meant.

For each skill/subpart, distinguish conceptual, method-selection, counting, algebra, and arithmetic errors when supported. A correct method and wrong final arithmetic can yield different evidence. A correct final answer without a derivation may not establish the intended skill.

Success after a hint or exposed solution is assisted evidence. Resuming an attempt is not a new independent attempt. Track question-family and solution exposure; repeated variants cannot indefinitely increase independent-evidence counts. Paused or untouched parts remain unassessed.

Use a versioned deterministic policy to summarize active evidence, keeping observed performance, coverage, assistance, diversity, and recency separate. Report counts/descriptions before calibrated mastery estimates exist. Do not apply arbitrary per-exercise increments or automatic knowledge decay solely from elapsed time.

Diagnostics use an explicit topic/skill coverage blueprint. If exam weights are unavailable, show the chosen coverage assumptions instead of inventing lecturer priorities. Validate generated questions and reference solutions before their use for assessment. An unresolved question/rubric cannot reduce learner state. A second response from the same model does not by itself constitute independent validation.

A diagnostic score is the observed rubric score on its items. Overall reports retain untested topics and prior exposure. Targeted practice does not replace balanced diagnostic sampling. Suggestions remain optional and cite the evidence or coverage gap they address.

## 9. Persistence, backup, and migration

Store source paths relative to the managed workspace and verify hashes when restoring or investigating corruption. Source bytes are immutable after registration; extraction corrections create processed versions.

Use SQLite's backup API or another documented consistent snapshot method. Read the source/asset list from the snapshot and copy exactly its referenced immutable files. Include schema/contract versions and hashes in the export manifest. Test database integrity, foreign-key consistency, and source-reference resolution after restoring into a new path.

Do not commit a live learner database or uploaded course materials to the code repository as the synchronization mechanism. Snapshot transfer supports moving workspaces; simultaneous remote use requires a single service owning the database and is deferred. A temporary cloud working directory is not durable persistence unless an explicit save/restore integration supplies it.

## 10. Milestones and completion gates

All runtime milestones below are initially pending. This document package is the planning deliverable, not a completed milestone implementation.

| Milestone | Work | Exit gate |
|---|---|---|
| M0 — Shared contract and discovery | Package core skeleton, capability checks, native loaders, structured operation envelope, and host/version records | All three hosts can discover shared instructions and invoke a minimal core capability operation; unavailable hosts are recorded as untested |
| M1 — Reliable storage and originals | Migrations, source versions, attachments, idempotent writes, attempt events, snapshot backup/restore | Original-byte restoration, duplicate/conflict tests, course-boundary tests, and interrupted-commit recovery pass |
| M2 — One course ingestion and retrieval | Representative source types, locators, full extraction, semantic units, topic map, FTS5, and dependency expansion | Checked retrieval fixtures retain every required assumption and resolve original locations; ambiguous inputs are flagged |
| M3 — Tutor evidence and corrections | Assisted/independent events, per-skill evidence, partial progress, pauses, corrected grading, and topic projections | Evidence is explainable and reproducible; assistance, repetition, tutor-error, and resume fixtures pass |
| M4 — Diagnostic and practice selection | Coverage blueprints, checked questions/rubrics, resumable assessments, and transparent reports | Missing coverage/exposure/uncertainty remain visible; no unvalidated reference changes learner state |
| M5 — Three-host conformance and measured efficiency | Real-host smoke tests, cross-host resume, held-out educational evaluations, and usage reporting | All required hosts pass the declared feature matrix, or the release explicitly remains partial; costs and accuracy are reported together |
| M6 — Correctness and reliability repair pass | Scoring/retraction race prevention, item-to-attempt linkage/exclusivity (Migration 005), strict check schema validation, timeline assistance preservation, atomic item startup, exception-safe lock release, and CI Python matrix (3.10–3.14) | Multi-connection concurrency tests, foreign attempt rejection, strict verification tests, timeline assistance tests, zero lock/FD leak on failure, and clean restore recovery all pass |
| M7 — Final correctness and reliability verification pass | Active evaluated evidence requirement for confirmed scores (including zero), question/solution/rubric validation revision & content identity check, idempotent attempt link reaffirmation, and schema-v4 legacy migration quarantine with backup table & audit trail | 10 dedicated verification tests pass (`tests/test_final_verification.py`), full 77-test regression suite passes, capabilities inspector and synthetic demo pass cleanly |

M0 includes minimal discovery early, so environment incompatibility is not discovered only after the tutor is built. M5 establishes complete integration, not a guarantee that different models make identical judgments.

For every milestone, record implemented changes, automated checks, reviewed educational fixtures, actual host versions, remaining limits, and measured versus estimated usage. Update status only after the relevant evidence exists.

## 11. Failure scenarios and acceptance fixtures

These are tests to implement or review, not tests already passed.

| ID | Failure fixture | Required behavior |
|---|---|---|
| F01 | OCR substitutes `<` for `≤` or drops a subscript | Uncertain extraction is flagged; the original region remains available; no unchecked grading based on the changed condition |
| F02 | Summary omits an independence condition | Retrieval returns the condition/dependency needed to decide applicability |
| F03 | Hebrew/English aliases use different wording | Retrieve the intended topic or expose insufficient retrieval and a valid expansion path |
| F04 | Source answer or assumption changes | Default retrieval uses active content; dependent evaluations are identified for review; old provenance remains accessible |
| F05 | Identical bytes uploaded under a different name | Preserve upload aliases without duplicate processing or knowledge units |
| F06 | Same filename with different bytes | Create distinct immutable versions and resolve both historical locators |
| F07 | Correct answer follows a shown solution | Classify the observed success as assisted/exposed, not independent |
| F08 | Learner pauses after one correct subpart | Preserve its evidence; untouched subparts remain unassessed |
| F09 | Correct method, arithmetic mistake | Keep method evidence distinct from arithmetic outcome |
| F10 | Repeated question/near-identical variants | Preserve exposure/family identity; do not fabricate diverse independent evidence |
| F11 | Tutor incorrectly marks a valid solution wrong | Correction retracts invalid evidence and recomputes affected state without erasing history |
| F12 | Generated question has contradictory conditions | Withhold assessment changes until the question/reference is repaired |
| F13 | Exercise combines two skills with different outcomes | Update only skills/subparts actually demonstrated |
| F14 | Submitted image has an unreadable symbol | Do not invent the symbol; clarify or leave affected evidence pending |
| F15 | Tool retry after a successful commit | Return the prior receipt; count the operation once |
| F16 | Same request ID with different content | Return an explicit conflict rather than overwriting or ignoring new content |
| F17 | Crash before/after commit | Recover to a consistent committed state or explicit pending review; no half-applied projection |
| F18 | Two sessions change the same attempt revision | Reject stale updates; preserve both genuine observations without silent overwrite |
| F19 | Exercise ID belongs to another course | Reject the cross-course write |
| F20 | Conversation reset or host switch | Resume the committed attempt and preferences without loading the full transcript |
| F21 | Only weak topics are repeatedly practiced | General reports expose the untested coverage; use a separate coverage blueprint |
| F22 | Exam has no official solution | Mark reference uncertainty; validate before it changes learner assessment |
| F23 | Syllabus topic has no uploaded content | Show missing material instead of claiming complete course coverage |
| F24 | Original source is missing or hash mismatches | Identify the affected references; do not claim source verification succeeded |
| F25 | Backup contains data but omits source files | Restore validation fails until all referenced originals/assets are present |
| F26 | Required unit exceeds retrieval budget target | Preserve the complete assumption/formula or require explicit expansion; never silently truncate |
| F27 | Host reads an override instead of project loader | Report instruction discovery accurately; verify shared rules before declaring integration support |
| F28 | Host can return text but cannot expose source images | Advertise the limitation and keep image-dependent verification pending |
| F29 | A cloud workspace is recreated without data | Require explicit restore; do not invent prior progress from the new empty workspace |
| F30 | Core save command is unavailable | State that progress is not persisted; do not return a synthetic commit receipt |
| F31 | Scoring races with evidence retraction | Protect checks and writes in immediate transaction; reject score if retracted, or revert score to pending review on subsequent retraction |
| F32 | External/unlinked attempt supplied to scoring | Reject unlinked attempt; enforce item-to-attempt linkage, exercise version match, learner ownership, and attempt uniqueness |
| F33 | Ambiguous strings or numbers passed as verification checks | Strictly reject 'false', 'failed', 'pending', numbers, and containers; require boolean True or passing structured check state |
| F34 | Assistance requested after independent submission | Maintain independent classification for earlier evaluated submission; record subsequent assistance as exposure without rewriting score |
| F35 | Failed item startup on unowned assessment | Keep ownership assignment, validation, and linking atomic; leave assessment unowned when startup raises ValidationError |
| F36 | Initialization failure in workspace session | Exception-safe cleanup releases locks, closes connections, and leaves zero descriptor leaks, enabling immediate restore |
| F37 | Zero score without active evaluated evidence | Scoring strictly requires active evaluated evidence for any confirmed score, including zero; unevaluated work stays pending |
| F38 | Validation approves concurrently edited question | Validation attestation identifies exact question/solution/rubric revision and content identity; rejects stale attestations |
| F39 | Reaffirming unchanged attempt link erases score | Reaffirming unchanged link is an idempotent no-op preserving points, evidence, history, and completion status |
| F40 | Migration on schema-v4 workspace with duplicate attempt links | Pre-migration detection backs up to `backup_v4_assessment_items`, audits duplicates into `legacy_duplicate_attempt_links`, quarantines to `pending_review`, and allows clean Migration 005 |
| F41 | Observation evidence level submitted for confirmed assessment score | Reject confirmed score; enforce strict evidence schema; require evaluated evidence; never report unassessed work as assisted |
| F42 | Submission evaluated after exercise replacement or content change | Persist revision/hash on attempts & evidence (Migration 006); reject evaluating old submission or scoring using outdated evidence |
| F43 | Question validation called without caller-side identity | Reject validation without caller identity; mandate positive integer `expected_revision` or non-empty `expected_content_hash` |
| F44 | Question validation provenance records stale pre-update values | Provenance records final attested revision and content hash in provenance, atomically committed with snapshot history |
| F45 | Contradictory structured verification checks submitted | Strict schema: reject conflicting status/state, disallowed keys, duplicate check names, and failing/pending statuses |
| F46 | Caller-supplied learner ID in linking mismatches attempt owner | Verify caller learner ID matches attempt owner; reject attempt ownership overrides |
| F47 | Repeated legacy repair reaffirms unchanged attempt link | Reaffirmation is an idempotent no-op preserving points, evidence, history, and completed assessment state |
| F48 | CLI operation omits API parameters or receives malformed payload | Forward `submission_event_id`; reject non-object JSON with code 1; detect conflicting CLI options vs payload parameters |
| F49 | Restore archive contains Zip Slip, symlink, absolute path, or traversal | Sandboxed path resolution strictly rejects traversal, symlinks, absolute paths in archive and manifest |

Use small deterministic fixtures for storage guarantees and reviewed real examples for educational correctness. Validate the reasoning and required assumptions, not only the final numeric answer.

## 12. Evaluation protocol

Build a representative sample including a text PDF, scan, slide deck, formula/table, diagram, submitted solution image, and an exam when available. Confirm reference answers and source locations. Keep some questions held out from retrieval/prompt tuning.

Under the same model and checking protocol, compare complete relevant source content, structured retrieval, and summary-only retrieval. Summary-only is a failure probe, not the intended product design. Keep failures and retries in the result set.

Report task correctness, assumption preservation, source-location accuracy, retrieval sufficiency, repeated calls, uncertainty handling, restore behavior, total usage, and latency. Report critical failures separately from averages. Choose the configuration with lower measured cost among those meeting the agreed correctness gate; do not optimize a short payload that increases wrong answers or retries.

An evaluation gate may be strict for known critical fixtures without pretending that zero fixture failures proves general reliability. Further statistical claims require larger representative data.

## 13. Remaining decisions

- Extraction tools and runtime/dependency minimums, based on real material and host capabilities.
- Topic/skill granularity that explains learner errors without an unnecessary taxonomy.
- Sufficiency criteria for qualitative topic labels; initially report the underlying evidence rather than inventing calibrated confidence.
- Whether lexical retrieval plus aliases is sufficient for Hebrew/math queries.
- Transport needs for each installed host, especially visual-source handling and restricted/cloud environments.

Resolve these through the milestones and recorded tests. Do not expand the architecture simply because an optional component exists.

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
