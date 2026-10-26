# Core technical guarantees

Extracted from the product requirements on 2026-10-19. These implementation
contracts retain the detailed schemas, migration names and API behavior.
[development/goal.md](../goal.md) owns the product guarantees; [the historical roadmap](roadmap/INDEX.md) and
[CLI workflow](../../docs/lumen-workflow.md) describe implementation and use. Schema v13
is current; numbered migrations below describe their historical repairs.

## Validation, persistence and recovery contracts

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
16. **Provenance Chain Eligibility, Score Revalidation, and Projection Rebuilding**: Evidence eligibility requires that the entire provenance chain (evidence record, attempt, committed submission, learner ownership, and current exercise version) is valid and resolved. Obsolete attempts cannot legitimize current-version evidence, scoring, mastery, coverage, or recommendations. Migration 008 backs up tables (`backup_v7_*`), revalidates historical scores against complete policy (quarantining invalid items to `pending_review` with audit history and reopening assessments), quarantines incompatible active evidence, and rebuilds all `topic_state` projections within the migration transaction. Outdated attempts cannot be resumed (`resume_attempt` rejects stale attempts, and `course_brief` omits stale resume actions). Exponent overflow and non-finite numbers in JSON are rejected before execution, and response serialization is tested before transaction commit.


## Course discovery and source-bound practice

`list-courses` / `LumenCore.list_courses()` returns `workspace_path` and the
registered `courses` in the explicitly selected workspace. It does not discover
or merge other databases. The tutor resolves the chosen course before querying
its `course-brief` and source inventory.

`propose-practice` accepts `source_only` (strict boolean, default `false` for
backward compatibility). General source-based practice workflows pass `true`.
This requires an accepted source occurrence with an applicable visual-review
status and same-course source version, in addition to the existing current
validation/exposure gates. Candidates expose `source_reference` with immutable
source version/hash, original filename, question key and spans; exercises without
an occurrence report null. Source-only shortages are explicit and never filled
with unbound generated questions. The operation remains read-only.


## Saved assessment paper and PDF export

New `create-assessment` receipts include a `delivery` object identifying PDF as
the default test format, `status:not_exported` and the next operation
`export-assessment`. Saving a selection must not be confused with file delivery.

`assessment-paper` / `LumenCore.assessment_paper(assessment_id, course_id=None)`
returns only the saved title, selected question order, current checked exercise
identity, student text/subpart keys and exact source references. Teacher references,
rubrics, private option mappings, scores and learner submissions are excluded.
Cross-course requests, unvalidated exercises and withdrawn source reviews fail.
The operation does not create learner events or assessment reservations.

`export-assessment` / `LumenCore.export_assessment(...)` renders the same snapshot
to offline HTML/MathML and prints a PDF with an installed Chrome/Chromium/Edge.
`output_directory` is optional; the default is
`<course_directory>/tests/<assessment_id>`. No network math assets are needed.
Renderer failure, missing output or an unreadable/empty PDF cannot produce a
successful delivery response. The output reports paths/hashes, page count and
`rendered_pending_visual_review`; the host must inspect rendered PDF pages and
deliver a file link before claiming the test is complete. Export does not mutate
learner evidence. An existing export with a different paper fingerprint requires
a new version directory rather than silently overwriting a changed paper.


Course-local export defaults are resolved from recorded import provenance, checked
against the course manifest. Workspace-only courses use a safe course ID under
`<workspace>/courses`. `list-courses.directory` and
`course-brief.course_directory` expose the location. The brief's learner-scoped
`open_assessments` exposes existing saved test IDs and PDF paths without private
solutions, allowing recovery of a missing PDF when fresh candidates are reserved.
Browser discovery honors `LUMEN_BROWSER_EXECUTABLE`, normal browser paths and
known Playwright caches (including `PLAYWRIGHT_BROWSERS_PATH`), without downloading
software or searching the filesystem. No security flags are weakened.


## Completed source-processing reuse

Ingestion reuses a completed result only for the same course, logical source,
full SHA-256 of the immutable staged bytes and eligible processing fingerprint.
Both `LumenCore.ingest_source` and `IngestionPipeline.ingest_file` use this key.
The fingerprint covers the extractor implementation/version, Python runtime,
relevant dependency versions, effective file suffix, unit-builder and catalog
versions, and a detached snapshot of effective ingestion configuration.
Unknown implementations or dependency versions disable reuse; they never justify
serving an older known result. Required extractor dependencies retain their normal
failure behavior.

Configuration includes role, catalog flag, all structured-unit fields (including
explicit IDs and list order), normalized topic slugs and their resolved topic IDs,
including unresolved slugs. Object key order and topic order/duplicates do not
change processing identity. A topic that becomes resolvable changes the key.
An existing logical source cannot change role through ingestion. An omitted role
inherits its existing role; a new source defaults to `reference`. An explicit
different role is rejected. Explicit unit
IDs already owned by an earlier or foreign unit fail rather than overwrite or
relink history; omit IDs or supply fresh IDs when new processing is required.
Maintainers must bump the applicable tokens in `ingestion/processing.py` whenever
extractor, unit-builder or automatic-catalog output behavior changes.

Staging and extraction run outside database write transactions; ingestion rejects
entry under an active caller transaction. Publishing verifies staged bytes even
on reuse. A short immediate transaction rechecks ownership, role, topic mapping
and reuse identity, then commits sections, units, processing metadata, catalog
output and any operation receipt together. Concurrent misses may extract twice,
but their commit recheck retains one completed version and derived set. A vanished
speculative hit or changed topic mapping fails for preparation to be retried
outside the transaction. Extraction or commit exceptions leave no partial reusable
database result or successful receipt. Immutable orphan files may remain after a
rolled-back publication; staging is cleaned on success, replay and failure.

Migration 13 adds `source_processing` metadata without rewriting historical
versions or guessing their processor identities. Legacy versions reprocess on
the next ingestion. Changed bytes, processor or configuration create immutable
versions with fresh derived IDs and independent extraction, visual and mathematical
review gates. Same-byte catalog aliases require equal known eligible processing
fingerprints on both versions. Completion metadata can describe extracted,
uncertain, empty or unsupported output: reuse preserves those limitations and
never constitutes review acceptance or mathematical validation.

Old originals, exact source spans, reviews, aliases, attempts, evidence and grades
remain intact. An old result cannot satisfy a changed processing key, but this
contract does not revoke historical review eligibility or impose a global latest
source version policy. An unchanged request ID/input replays its original committed
receipt even after a processor upgrade, without extraction; divergent input under
the same request ID still fails. A fresh request uses current processing identity.

Synthetic safety tests cover two-connection prepared misses with matching and
distinct request IDs, extraction and post-catalog interruption, staged-byte
mutation/corruption, upgraded receipt replay, and retained text/OOXML review and
learner history after source or processor changes. These tests do not establish
live-host or external-bank processing validation.
