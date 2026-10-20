# Lumen CLI tutoring workflow

Audited on 2026-10-18. These examples supplement the canonical Lumen skill and its [tutoring](workflows/tutoring.md), [answer review](workflows/answer-review.md), and [practice building](workflows/practice-building.md) modes. Replace bracketed IDs with returned `data` fields; use the same workspace and learner ID throughout. Run `.venv/bin/lumen` from the project root, or the installed `lumen` command.

Start with `list-courses -w <workspace>` and `course-brief` for a matching registered course. Use `capabilities` to check environment support. If no matching course exists, ask for the supplied-material location; never substitute a scratch/example database. For a new course, create a course and register syllabus topics with `create-topic`. Ingest originals with `ingest-source`, inspect `get-extracted-sections`, and review `course-brief` for missing material. PDF text, PPTX text/tables, and supplied text have local extractors. Images and visual regions require host inspection; OCR is not implemented. Unsupported originals remain available with explicit limitations. Automatic units are pending review.

For exams, use `role:"exam"` and follow [question tracking](question-tracking.md)
for automatic cataloging, extraction/coverage review, source occurrences,
paginated learner history, duplicate review and ordinary-practice grades. Existing
diagnostic grading stays on the linked item workflow below.

Save preferences through the public core:

```bash
lumen update-learner-settings -w '<workspace>' -c '<course_id>' -r '<stable-settings-request>' -j '{"learner_id":"learner_1","chosen_language":"he","teaching_preference":"Hints only when requested"}'
```

Create generated questions with `create-exercise`, recording `exercise_family`, `question_text`, `subparts`, `topic_mappings`, `reference_solution`, and `rubric`. Label generated content. A rubric may declare `max_points`; diagnostics preserve that maximum. New questions remain pending until the reviewer checks their exact content:

```bash
lumen validate-exercise-version -w '<workspace>' -r '<stable-validation-request>' -j '{"version_id":"<exercise_version_id>","expected_revision":1,"checks":{"mathematical_consistency":true,"source_correspondence":true,"rubric_review":true}}'
```

Checks attest actual review. Never copy passing checks onto an unchecked or contradictory question. Use the current expected revision or content hash; exercise edits invalidate older submissions and scores.

For practice selection, `propose-practice` returns checked, distinct-family candidates without recording an attempt, presentation, score or reservation. It excludes recorded prior attempts and assessment selections for this learner/unowned drafts by default; `shortfall` describes an insufficient bank. Family equivalence, date/source constraints and external practice history still require review:

```bash
lumen propose-practice -w '<workspace>' -c '<course_id>' -j '{"learner_id":"learner_1","count":3,"source_only":true,"topic_ids":["<topic_id>"],"exclude_exercise_version_ids":["<already-selected-version>"]}'
```

For ordinary tutoring or checking a worksheet outside a diagnostic, start a practice attempt and use its returned `data.id`. This does not require creating an assessment:

```bash
lumen start-attempt -w '<workspace>' -c '<course_id>' -r '<stable-practice-request>' -j '{"exercise_version_id":"<exercise_version_id>","learner_id":"learner_1","mode":"practice"}'
```

For a diagnostic, select the actual checked version IDs and use its linked item attempt instead. An empty selection creates an empty coverage plan, not a generated examination:

```bash
lumen create-assessment -w '<workspace>' -c '<course_id>' -r '<stable-assessment-request>' -j '{"title":"Diagnostic","learner_id":"learner_1","blueprint":{"topic_ids":["<topic_id>"]},"selected_exercise_version_ids":["<exercise_version_id>"]}'
lumen start-assessment-item-attempt -w '<workspace>' -r '<stable-attempt-request>' -j '{"assessment_id":"<assessment_id>","item_order":1,"learner_id":"learner_1"}'
```

Record work on the returned linked attempt. Record hints and solution exposures in actual chronological order, with a subpart key when appropriate. Use the returned revision for each next event:

```bash
lumen record-attempt-event -w '<workspace>' -r '<stable-submission-request>' -j '{"attempt_id":"<attempt_id>","expected_revision":1,"event_type":"work_submission","subpart_key":"a","content":"<actual learner submission>"}'
lumen commit-evidence -w '<workspace>' -r '<stable-evaluation-request>' -j '{"attempt_id":"<attempt_id>","submission_event_id":"<submission_event_id>","evaluations":[{"subpart_key":"a","topic_id":"<topic_id>","skill_id":"<skill_id>","correct":true}],"complete_attempt":false}'
```

Do not evaluate ambiguous symbols or unseen subparts. Observation levels (`unreadable`, `uncertain`, `pending`, `unassessed`) do not support confirmed scores. Correct method with an arithmetic error can be recorded with `correct:false`, `partial:true`, and `error_category:"arithmetic"`.

Score through `record-assessment-item-score` only after linked, applicable evaluated evidence exists. All required subparts must be evaluated for a full score. Explicit `allow_partial:true` permits a partial score while leaving the diagnostic open. Use `pause-attempt`/`resume-attempt` to preserve unfinished work; `course-brief` finds the same attempt in a new session. Hints or solutions from earlier same-family attempts remain exposure. Repeated learner/family/skill/subpart observations remain stored but do not inflate fresh independent evidence.

Use `correct-evidence` for tutor mistakes. It retains history, recomputes topic state, and invalidates dependent scores for review. Re-score only after checking the corrected evidence. Source version changes retain historical citations; an explicit exercise edit invalidates its old evidence.

Use stable request IDs for authoring, preferences, attempts, events, evidence, validation, and scoring. Identical retries return the original receipt; divergent retries conflict. Backup and restore have filesystem semantics: restore refuses a populated destination by default. Keep backups outside live database/original/staging paths.

Reproduce the audited workflow with:

```bash
.venv/bin/pytest -s -q tests/test_audit_course_e2e.py
```

It uses independently generated materials in `examples/audit_course/`, including Hebrew text, a two-page PDF, a slide deck, missing coverage, five reviewed questions and one rejected candidate. This is a synthetic educational review and CLI test; it does not establish live Claude Code or Antigravity integration or measured provider costs.


## Test delivery is a PDF

After `create-assessment` succeeds, use its ID to export the saved paper:

```bash
lumen assessment-paper -w '<workspace>' -c '<course_id>' -j '{"assessment_id":"<assessment_id>"}'
lumen export-assessment -w '<workspace>' -c '<course_id>' -j '{"assessment_id":"<assessment_id>"}'
```

Use the returned `pdf_path`, inspect rendered PDF page images with the host PDF
skill, then deliver its link. A saved assessment or chat question list is not a
finished test. `assessment-paper` supplies safe question fields without SQL or
private keys. Export does not mark presentation, assistance, submission or grading.
A missing PDF for an existing assessment calls for export, not a new assessment.


## Assemble from a saved blueprint

Save this object as `blueprint.json` (replace the topic ID with a registered ID):

```json
{
  "duration_minutes": 90,
  "relaxations": [],
  "shuffle_options": false,
  "slots": [
    {"id": "core", "section": "Core", "topic_ids": ["<topic_id>"],
     "question_type": "multiple_choice", "count": 2, "max_points": 5}
  ]
}
```

```bash
lumen assemble-exam -w '<workspace>' -c '<course_id>' -r 'exam-20261019-01' -j '{"blueprint_file":"blueprint.json","learner_id":"learner_1","title":"Practice test","seed":42}'
```

The file must contain a finite JSON object. Each distinct slot requires a positive
integer `count`; `max_points` defaults to 1. Optional `section` and exact
`question_type` constrain allocation. `topic_ids` means ANY listed topic; use
separate slots for exact counts per topic. Optional `source_version_ids`, inclusive
integer `year_min`/`year_max`, and exact `difficulty` require reviewed occurrence
metadata/source identity; missing or untrusted values exclude candidates. Unknown
fields and unsupported derived structures reject. Limits are 100 slots and 100
questions. Section first-appearance order and within-section slot order are saved.
Weakness and novelty weighting acts only within hard constraints; the seed makes
selection reproducible for the same eligible bank and learner history.

Omit `relaxations` or supply `[]` for strict selection. To authorize fallback, use
an ordered list of unique constraint names, for example
`"relaxations": ["difficulty", "year_min"]`. Supported names are
`source_version_ids`, `year_min`, `year_max`, and `difficulty`. Each step drops that
constraint from every slot; readiness tries strict first, then cumulative prefixes,
stopping at the first proven complete allocation. Topic/type/section/count, review,
provenance, exposure, reservation and similarity gates remain hard. Invalid original
constraints reject even when listed for relaxation. Repeats are unsupported.
Original/effective blueprints and attempted/applied policy are saved privately;
retries retain the saved effective constraints and re-export uses saved snapshots.
Omit `shuffle_options` or use false; true and other values reject. Original option
wording/order and checked private answer mappings are saved unchanged.

Success returns only `assessment_id`, `pdf_path`, and a one-line question-count /
pending-visual-review summary in the standard JSON envelope. A shortage or
unproven bounded search returns structured sanitized `details.gaps` and exit 1,
without new assessment, reservation or output artifacts. Gaps give slot/section,
topic/type, needed/eligible/shortfall and exclusion counts. Search exhaustion is
not proof that the bank is infeasible.

Keep the request ID stable when retrying the same loaded blueprint, title, course,
learner and seed. A published replay returns the original receipt; changed content
conflicts even if the file path is unchanged. An active owner returns an incomplete
conflict. After readiness passes, the next invocation recovers verified completed
publication or retires dead owned staging; it preserves live owners and unknown
paths. Atomic publication requires Linux `renameat2(RENAME_NOREPLACE)`, a working
PDF browser renderer, and sibling staging on the destination filesystem;
unsupported publication platforms reject safely.

`assessment-paper` and `export-assessment` for this assessment use saved snapshots,
without reselection or current learner weights, even after source/question edits.
Export preserves verified existing PDF bytes and rejects corrupt existing output;
a missing export can be rendered again from snapshots. A fresh rendering need not
be byte-identical. Rendering remains `rendered_pending_visual_review`: inspect
rendered page images and deliver a clickable PDF link separately. Assembly/export
does not record delivery, attempts, grades or learner progress. Automated readable
PDF checks do not establish human visual review or live-host integration.

## Release or expire unused reservations

```bash
lumen release-reservation -w '<workspace>' -c '<course_id>' -r 'release-01' -j '{"learner_id":"learner_1","assessment_id":"<assessment_id>","reason":"released"}'
lumen release-reservation -w '<workspace>' -c '<course_id>' -r 'cancel-01' -j '{"learner_id":"learner_1","assessment_id":"<assessment_id>","reason":"cancelled"}'
lumen expire-reservations -w '<workspace>' -c '<course_id>' -r 'expiry-01' -j '{"learner_id":"learner_1"}'
```

Course, learner assertion and stable request ID are required. Explicit
`"learner_id":null` targets only unowned legacy drafts; it is not a wildcard.
Release defaults to `released`; `cancelled` has the same terminal effect.
Reuse a request ID only for identical operation and input; replay returns the
original receipt, including the original expiry results. Use a new ID for a later
expiry sweep. Success is persisted only when its commit receipt is returned.

Expiry runs on demand, using server UTC and a fixed seven days from original
assessment/job creation; retries do not reset age. No scheduler or read-time age
filter releases records. Unused open/paused drafts must have no linked attempts,
awarded score, score history or assessed score state. Expiry returns `released`,
`skipped` with structured reasons, and `ttl_days`. Recent, used, completed, live
(`active`), invalid-timestamp and `recovery_required` records are skipped.
Explicit unsafe releases fail. Recover a renamed-but-uncommitted publication by
retrying its original assembly request before releasing its unused saved draft.

Cancellation/release of a pending job is terminal: its old assembly ID cannot
resume or publish. These operations delete no artifacts, snapshots, assessment,
audit or exposure history. Published snapshot re-export remains available without
reactivating a reservation; independent attempted families remain excluded.
Readiness reports `without_safe_releases` separately from its broader
all-reservations counterfactual; only the safe relief identifies unused saved
drafts, conservatively retaining pending jobs and overlapping unsafe reservations.
