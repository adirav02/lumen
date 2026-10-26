TL;DR: Verbatim legacy roadmap: 11. Failure scenarios and acceptance fixtures.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
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
| F50 | Legacy workspace contains NULL identity attempts/evidence | Migration 007 resolves unedited questions, creates `backup_v6_*`, quarantines modified question items to `pending_review`, and reopens assessments |
| F51 | Correction attempted on obsolete or unresolved evidence | Replacement is stamped `pending_review` with historical rationale; topic state recomputation and brief exclude obsolete evidence |
| F52 | Observation evidence submitted for topic coverage | Observation evidence excluded from assessed coverage; topic state and course brief retain `assessed: false` / unassessed status |
| F53 | Incomplete subpart evaluation submitted for full scoring | Reject scoring without complete subparts; with `allow_partial=True`, assign `partially_scored` and leave assessment status `open` |
| F54 | Stale legacy repair or uncoordinated link overwrites | Reject already-resolved quarantine repairs with `ConflictError`; reject overwriting active scored links without explicit `expected_link_states` |
| F55 | Non-finite numbers or JSON constants in checks or CLI | Reject NaN, Inf, booleans in check score; reject non-finite nested metadata; CLI rejects `NaN`/`Infinity` constants with exit code 1 |
| F56 | Outdated or ineligible provenance chain submitted for scoring, classification, coverage, or recommendations | Verify entire chain (evidence, attempt, submission event, learner ownership, current exercise version); exclude ineligible evidence from classification, coverage, and course brief |
| F57 | Historical workspace has invalid scores from earlier schema versions | Migration 008 creates `backup_v7_*` tables, revalidates historical scores against complete current policy, quarantines invalid scores to `pending_review` with audit history, and reopens affected assessments |
| F58 | Historical workspace has outdated topic projections after upgrade | Migration 008 rebuilds all `topic_state` projections inside the migration transaction using the shared eligibility policy so coverage and briefs agree immediately |
| F59 | Non-boolean `allow_partial`, full credit awarded with missing subparts, or zero score with positive evidence | Strict boolean `allow_partial` enforced; disallow full credit when required subparts are missing; require evaluated incorrect work for confirmed zero scores |
| F60 | Resuming attempt on outdated exercise revision | `resume_attempt` enforces educational identity resolution and rejects outdated attempts; `course_brief` omits stale attempts from resume recommendations |
| F61 | Non-finite numbers or exponent overflow in payloads | `validate_all_finite_numbers` rejects NaN, Inf, exponent overflow before mutations; responses tested with `allow_nan=False` before committing receipts |
| F62 | Multi-host workspace handover and cross-host resume across Antigravity, Codex, and Claude Code | Simulated host-marker conformance test (`tests/test_three_host_conformance.py`; no host executables launched) executes sequential handover: Host A (Antigravity) initializes, ingests with assumptions and pauses attempt; Host B (Codex) resumes, records hint, commits assisted evidence, verifies write idempotency, and scores item; Host C (Claude Code) inspects source region, corrects tutor mistake with preserved audit trail, and verifies byte-for-byte backup/restore |

Use small deterministic fixtures for storage guarantees and reviewed real examples for educational correctness. Validate the reasoning and required assumptions, not only the final numeric answer.

