# Course Tutor — Goal

Status: approved product direction; implementation has not started.  
Updated: 2026-10-09.  
Audience: product owner, implementers, and agents working on this project.

## Purpose

Build a portable course workspace that turns an existing AI agent into a persistent tutor. A learner supplies course materials, works through exercises, and can request a comprehensive diagnostic. The system retains course knowledge and evidence of the learner's performance across sessions and supported agent environments.

The objective is better understanding and independent problem solving. The assessment must reflect the evidence honestly; it is not a number that must rise after every conversation.

## Required environments

Support OpenAI Codex, Anthropic Claude Code, and Google Antigravity through one shared instruction contract and one storage/tool implementation. Additional environments can implement the same contract. "Universal" means a portable core with explicit environment adapters, not a promise that every chat application can access local files or execute tools.

Instruction discovery, tool execution, source-image access, and durable storage must be checked separately in each environment. Host permissions and instruction precedence remain in force. Provider-specific session memory must not become the authoritative course or learner database.

## Learner experience

1. Create a course and request the syllabus and available learning materials. Past exams and official solutions are optional. Materials can be added later.
2. Preserve the uploaded originals, process their contents, and build a course map. Show missing material and extraction uncertainty before claiming coverage.
3. Offer a diagnostic when requested. Evaluate topics and skills using a coverage plan and checked questions, with no requirement to finish in one session.
4. Inspect the learner's attempted solution and teach according to their preference. Default to focused guidance; reveal a full solution when requested.
5. Persist observed work and assistance during the exercise. On completion or a pause, retain the evidence without grading unseen parts as failures.
6. Show topic-level performance, material coverage, and assistance separately. Offer a next exercise that addresses a documented difficulty, checks an untested area, or revisits a skill.
7. Resume the same attempt and assessment after a new session or a supported environment switch.

## Non-negotiable decisions

- SQLite is authoritative for processed course knowledge, attempts, evidence, assessments, and preferences. Original uploaded files remain immutable files with versioned metadata and content hashes.
- Every source-derived knowledge unit links to the exact source version and page, slide, or other location. Generated explanations and questions are labeled as generated.
- Retain full extracted content and source files. A summary is a navigation aid, not the sole basis for a mathematical answer.
- Preserve formula assumptions, symbol definitions, exceptions, and necessary diagrams. Retrieval may expand when correctness requires it.
- Evaluate observed skills and subparts. Distinguish independent work, work after hints, and work after an exposed solution.
- Evidence can be corrected or retracted. Source, rubric, or tutor errors must be able to repair affected topic states without erasing the audit trail.
- Writes are validated, course-scoped, idempotent, and transactional. The agent does not own the SQL schema or write the database directly during tutoring.
- A positive save acknowledgment means the database commit succeeded. Unavailable persistence is stated plainly.
- Use ordinary code for search, filtering, counts, and state updates. Use the model for interpretation, teaching, and judgments that require reasoning.
- Measure total tokens and cost per correct task, including retries and image use. Do not claim a savings percentage without measurements.

## Meaning of assessment

The system reports observed performance and the strength, diversity, and recency of evidence. Unknown topics remain unknown. A score on a diagnostic is a score on that diagnostic; it is not automatically a calibrated probability of passing an exam.

Do not add arbitrary mastery points for each correct answer. Repeated attempts at the same question or near-identical variants do not count as fresh independent evidence. A break caused by fatigue is not evidence of a conceptual weakness.

## Initial scope

One learner per workspace, multiple courses, one local SQLite database, immutable source/attachment files, local tool execution, and thin adapters for the three required environments. Use a Python core with SQLite support; document and feature-check the runtime. Extraction dependencies are selected from representative files rather than assumed to handle every format.

PDFs, slides, images, and supplied text are target inputs. Their actual extraction capability must be reported. Unsupported or ambiguous pages remain available as originals and are marked for review.

## Deferred scope

Live multi-device synchronization, a custom chat client, a hosted multi-user service, automatic fine-tuning, agent fleets, and statistically calibrated pass predictions are outside the initial release. Semantic search, reranking, and provider-specific caching require measured benefit before adoption.

## Explicit product guarantees

1. **Attempt, Evidence Binding, and Subpart Completeness**: Confirmed assessment scores require an explicitly linked, owned attempt and applicable active evaluated evidence. Scoring cannot adopt unlinked or external attempts. Every confirmed score, including zero, strictly requires applicable completed active evaluated evidence grounded in submitted work; observation levels (`unassessed`, `pending`, `uncertain`, `unreadable`) cannot support confirmed scores or assessed topic coverage. Unevaluated work remains pending. Positive scores require positive evaluated evidence; zero scores require evaluated incorrect work. Full item scoring (`score_status="scored"`) requires all declared required subparts evaluated; partial scores without complete subparts require explicit `allow_partial=True`, receive `score_status="partially_scored"`, and keep the assessment open (`status="open"`). Reporting never classifies unassessed work as assisted.
2. **Transaction and Publication Atomicity**: Validation and publication cannot race into inconsistent learner state. State mutations and operation receipts commit together within atomic immediate transactions.
3. **Rollback on Failure**: Failed mutations leave authoritative state completely unchanged. Pre-mutation states, learner ownership, and revisions are preserved when validation fails.
4. **Timeline-Aware Assistance Preservation**: Earlier independent work remains independent despite later assistance. Post-submission hints or solutions are recorded as exposure history but never rewrite prior independent mastery.
5. **Strict Verification Check Schemas and Finite Numbers**: Verification checks have an explicit, unambiguous schema with allowed keys (`status`, `state`, `reason`, `notes`, `metadata`, `score`), disallow conflicting `status`/`state`, reject duplicate check names (case-insensitive), and reject failing/pending statuses (`failed`, `falsified`, `rejected`, `pending`, `unknown`). Check `score` must be a finite numeric value >= 0 (rejecting booleans, NaN, Inf); `reason` and `notes` must be strings; nested metadata numbers must be strictly finite. CLI input rejects non-standard JSON constants (`NaN`, `Infinity`) with exit code 1; CLI output produces strictly valid JSON (`allow_nan=False`).
6. **Exception-Safe Resource Lifecycle**: Initialization failures release every acquired resource (database connections, workspace file locks, file descriptors) immediately to enable clean recovery and restore.
7. **Deterministic Correction Propagation**: Retracting or superseding evidence propagates immediately to item scores, topic coverage, and topic state projections, reverting affected items to pending review and retaining an immutable audit trail.
8. **Traceable Educational Revisions and Applicable Evidence**: Educational revision and content hash identity are persisted on attempts and evidence (via Migrations 006 & 007). Evaluating old submissions against replaced or modified exercise content is rejected; scoring assessment items using evidence from outdated exercise revisions is rejected. Outdated attempts cannot be resumed after exercise revision updates. Corrections on obsolete or unresolved evidence create replacements with `status="pending_review"` and historical rationale, preventing obsolete records from reviving into active current performance. Projections and reports exclude obsolete/unresolved evidence.
9. **Mandatory Caller-Side Validation Identity**: Question validation (`validate_exercise_version`) strictly mandates caller-side identity (`expected_revision` as a positive integer or non-empty `expected_content_hash`). Provenance records the final attested candidate revision and content hash in provenance, atomically committed with snapshots.
10. **Ownership Verification in Linking**: Caller-supplied `learner_id` in attempt linking is an assertion to verify against `attempt.learner_id`, not an override. Agreement is verified across caller, attempt, item, and assessment.
11. **Idempotency and Link Reaffirmation**: Stable request IDs guarantee idempotent replays for identical intents and explicit conflict errors for divergent intents. Optimistic revision guards reject stale concurrent writes. Reaffirming an unchanged attempt link on an assessment item is an idempotent no-op preserving points, evidence, history, and completion status.
12. **CLI Signature and Payload Conformance**: CLI operations conform to core API signatures, forwarding parameters such as `submission_event_id` in `commit_evidence`. The CLI rejects non-object JSON payloads with exit code 1 and detects conflicting CLI flags versus payload parameters.
13. **Secure Path Sandboxing on Restore**: Restore operations treat archives, manifests, and database paths as untrusted input. Path resolution strictly sandboxes extraction, rejecting Zip Slip, symlinks, absolute paths, and path traversal sequences (`..`).
14. **Evidence-Based Runtime Reporting**: Supported runtimes, operating systems, and host integrations are reported honestly according to verified evidence. Platforms lacking flock exclusion explicitly report locking as unsupported.
15. **Safe Legacy Schema Migration, Identity Quarantine, and Link Repair**: Upgrades detect legacy constraint ambiguities and unresolved identities prior to applying unique indexes or scoring, creating pre-migration backups (`backup_v4_*`, `backup_v6_*`), auditing ambiguous records into quarantine tables with pending-review status, and reopening affected assessments. Stale legacy repairs on already-resolved records or uncoordinated overwrites of active scored links without explicit `expected_link_states` are rejected with `ConflictError`.

## Release evidence

A release is ready only when:

- Originals can be restored byte-for-byte, and source references resolve after a workspace move.
- Representative course questions retain all required assumptions and provenance during retrieval.
- Assistance, partial progress, repeated submissions, tutor corrections, and interrupted writes pass their specified checks.
- Diagnostics expose missing coverage and unresolved grading uncertainty.
- Codex, Claude Code, and Antigravity each pass a recorded integration smoke test against the same core contract. Documentation checks alone do not establish runtime compatibility.
- Reported costs distinguish observed usage, estimated token counts, and unavailable billing data. Accuracy failures remain in the evaluation results.

## Document ownership

This file defines the product outcome and fixed requirements. `plan.md` defines the implementation sequence and acceptance tests. `docs/agents.md` defines agent behavior. Root loader files only route hosts to those shared instructions. If scope changes, update these documents together and record the change; provider wrappers must not quietly redefine the product.
