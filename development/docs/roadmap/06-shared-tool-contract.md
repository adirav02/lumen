TL;DR: Verbatim legacy roadmap: 6. Shared tool contract.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 6. Shared tool contract

This table is the target contract; inspect `src/course_tutor/api.py`, the CLI dispatcher, and `docs/lumen-workflow.md` for executable operations and actual envelopes. It does not prove every proposed operation exists.

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

