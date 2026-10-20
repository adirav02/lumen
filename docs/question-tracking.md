# Exam questions and learner history

Lumen keeps a course-level question catalog and learner-scoped attempts in the
same SQLite workspace. Cataloging is not presentation, submission or grading.
The implementation extends the existing exercises, source versions, events,
evidence and assessment policy; it does not introduce a second learning tracker.

## What existed and what was added

| Capability | Before this change | Current implementation |
|---|---|---|
| Original exams and revisions | Immutable source files, hashes and extracted sections | Preserved; each question occurrence links to exact source/version/hash and source spans |
| Question extraction/catalog | Manually authored exercises and free-text external references | Automatic conservative exam splitting, reviewable occurrences and explicit whole-exam coverage review |
| Learner history | Learner/course attempts, generic events, evidence and corrections | Paginated question/attempt history with separate shown/answered/graded/correct fields |
| Scores and feedback | Diagnostic scores/history and evidence rationales | Existing diagnostic history plus append-only ordinary-practice scores/feedback/correction reasons |
| Repetition | Recorded exercise families | Families, exact text fingerprints and reviewable similar-question candidates |
| Mistake practice | Topic recommendations | Explicit latest-evaluation mistake-focused question selection |

## Upload and catalog

```bash
lumen ingest-source -w '<workspace>' -c '<course_id>' -r '<upload-request>' -j '{"file_path":"<exam.pdf>","logical_name":"Final 2025, version B","role":"exam"}'
lumen list-questions -w '<workspace>' -c '<course_id>' -j '{"source_version_id":"<source-version-id>","limit":50}'
lumen exam-catalog-status -w '<workspace>' -c '<course_id>' -j '{"source_version_id":"<source-version-id>"}'
```

Roles `exam` and `past_exam` trigger cataloging during ingestion by default. Set
`catalog_questions:false` when importing raw files for a curated boundary pass;
then call `catalog-exam-questions` with the main questions and exact spans. This
avoids creating automatic candidates alongside a manually segmented bank. Existing exam
sources are cataloged from their stored sections during migration 9. For an
already uploaded source with another role, use `catalog-exam-questions` with its
source version. Repeating automatic cataloging reuses that source's catalog.

Solved exams and worked-problem collections can supply the question bank without
an unsolved edition. Preserve their actual role (for example,
`solutions_with_statements`) and explicitly catalog recoverable statements,
choices and subparts from those sources. Store solution passages privately, linked
to the same source version with their own locations. Answer-key-only material
without a recoverable problem remains unresolved for review. A matching unsolved
paper, if supplied, adds provenance rather than evidence of a new unseen problem.
Migration 10 aliases byte-identical uploads in the same course to their existing
catalog, even under another logical filename. Both upload versions remain
traceable; identical copies do not add questions. Uploading changed bytes creates a distinct source version and occurrences; even
an identical question retains its separate exam provenance.

The splitter recognizes line-start `Question`, `Problem`, `שאלה` labels and falls
back to numbered lines. It retains cross-page continuations and offsets into
immutable source sections. Automatic boundaries, repeated labels, numbered-line
ambiguity and source quality flags require review. Every automatic occurrence is
pending, including clean text. Scans, missing headers and unrecognized layouts can
produce zero candidates; this never means the exam has no questions or full
coverage. OCR is still unavailable. Image inspection/transcription is host work.

For missing or visual questions, submit checked transcriptions in bounded batches:

```bash
lumen catalog-exam-questions -w '<workspace>' -c '<course_id>' -r '<catalog-request>' -j '{"source_version_id":"<source-version-id>","questions":[{"question_key":"3","question_text":"<transcription>","source_spans":[{"section_index":2}],"subparts":[{"key":"a"},{"key":"b"}],"topic_mappings":["<topic-id>"]}]}'
```

Spans may include `start_offset`/`end_offset`; their section must belong to that
exact source version and offsets must be valid. Visual transcriptions can differ
from a missing/garbled text layer, so they remain pending until reviewed. The raw
extracted snapshot stays intact. A changed key/text cannot silently overwrite an
existing occurrence. Use `update-exercise-version` for a correction; changes to
question text reopen source review and retain the original extraction.
For incorrect boundaries/locators, add a candidate with a new unique key and correct
spans, then reject the erroneous candidate; its original provenance stays intact.
The revision operation also accepts `subparts`, `topic_mappings` and `skill_mappings` so a
reviewer can enrich an automatic candidate before validation. These changes
invalidate prior educational evidence through the existing revision policy.

Review each candidate, including rejection of non-question material:

```bash
lumen review-question-occurrence -w '<workspace>' -c '<course_id>' -r '<review-request>' -j '{"occurrence_id":"<occurrence-id>","expected_revision":1,"status":"accepted","notes":"Compared transcription, diagram and both subparts with original page."}'
```

Extraction acceptance, source visual review and mathematical validation are
separate. Practice selection and diagnostics require an accepted occurrence,
verified visual status (or `not_required` for plain text), **and** a validated
exercise version. Supply a
checked reference/rubric and validate the current revision using the established
`validate-exercise-version` operation. Reproduce declared subparts faithfully; do
not infer whole-question correctness from checking just one part.

```bash
lumen annotate-question -w '<workspace>' -c '<course_id>' -r '<metadata-request>' -j '{"occurrence_id":"<occurrence-id>","expected_revision":2,"metadata":{"stable_id":"course/exam/open/1","year":null,"semester":null,"sitting":null,"original_question_number":1,"points":25},"solution_links":[{"source_version_id":"<solution-source-version-id>","status":"unverified"}]}'
lumen review-question-visual -w '<workspace>' -c '<course_id>' -r '<visual-request>' -j '{"occurrence_id":"<occurrence-id>","expected_revision":3,"status":"verified","notes":"Compared rendered source, all options and formulas.","checks":{"source_render_checked":true,"formulas_options_diagrams_checked":true}}'
lumen search-questions -w '<workspace>' -c '<course_id>' -j '{"query":"תכנון דינמי","limit":20}'
```

Use actual current occurrence revisions. Metadata edits preserve previous values
and source-solution links in review history; links must stay inside the course.
Unknown metadata stays null. Search uses the question-text FTS index, returns
scoped excerpts/review states and omits private reference solutions/rubrics.
Visual checks attest work actually performed, not an automatic guarantee.
Version indexes bound dependent evidence/item lookups; the upgrade rebuilds each
affected course/topic projection once rather than once per imported question.
Withdrawing source review withdraws dependent diagnostic scores with audit history
and recomputes topic projections; practice grades become effectively pending.
Migration 10 backs up pre-upgrade scores/projections and applies the new gate.
Historical evidence remains intact. Reapproving review requires explicit regrading
for a withdrawn numeric diagnostic score.

DOCX extraction retains OOXML equations and a linear search representation,
paragraph/table/part locations, and image/highlight warnings. Word paragraphs are
not invented PDF pages. Original XML is not a verified LaTeX transcription.
Source verification and presentation verification remain separate: a rendered
student artifact has its own version manifest, hashes and print checks. Private materials belong in the gitignored `local-courses/` folder.
[Public beta courses](../examples/beta_courses/README.md) are pending; no private
source bank or renderer is distributed with this repository.

Only after reviewing all original pages and resolving all candidates, use
`review-exam-catalog` with the current catalog revision, `expected_question_count`,
`notes` and `checks:{"all_pages_reviewed":true,"question_count_verified":true}`.
The accepted count must match. `coverage_verified` then becomes true. An agent
must actually perform those checks; the API cannot prove a human read every page.
The course brief exposes pending exam-catalog counts.

## Separate the history states

Course reference solutions and learner submissions have separate roles. Uploading
a solved test for the question bank does not establish authorship, presentation,
solution exposure, an answer or a grade. Learner history starts from their actual
presentation/assistance/submission events; only identified learner work supports
an evaluation. A reference solution remains private until actually delivered.

| Field | Meaning |
|---|---|
| `shown` | An explicit `question_presented` event exists; creating an attempt or selecting a paper is insufficient |
| `answered` | An actual nonempty `work_submission` exists; hints or discussion are insufficient |
| `graded` | Work received a completed evaluation at some point, including preserved historical evaluations |
| `currently_graded` | Applicable evaluation exists for the latest submitted work of at least one part/skill |
| `answered_correctly` | All declared required parts have applicable successful evaluations; partial progress is insufficient |
| `needs_review` | Grading/evidence is invalidated or the latest answer needs renewed checking |

`hint_count`, `solution_exposure_count`, submissions, feedback events, evidence
rationales, correction reasons and score revisions remain independently visible.
Assisted correct work can be answered correctly without establishing independent
mastery. Later assistance does not rewrite earlier independent submissions.
An unknown prior presentation is not backfilled as shown. A newer ungraded answer
never inherits an older answer's correctness.

```bash
lumen question-history -w '<workspace>' -c '<course_id>' -j '{"learner_id":"alice","exercise_version_id":"<version-id>","limit":20}'
lumen attempt-history -w '<workspace>' -c '<course_id>' -j '{"learner_id":"alice","attempt_id":"<attempt-id>","limit":50}'
```

Catalog/question-attempt pages use `next_after_id`. Event, evidence and grade
streams have separate continuation fields (`next_event_after`,
`next_evidence_after`, `next_grade_after`, `next_assessment_score_after`). Pass
returned cursors as `event_after`, `evidence_after`, or `grade_after`, respectively;
practice and diagnostic scores are separate streams. Records include original
chronology; UUID page order is stable rather than chronological. Another learner's
attempt cannot be retrieved by these APIs. Learner IDs scope local data; they do
not constitute authentication for a hosted multi-user service.

For ordinary practice, commit evaluated evidence first, then record a score:

```bash
lumen grade-attempt -w '<workspace>' -c '<course_id>' -r '<grade-request>' -j '{"learner_id":"alice","attempt_id":"<attempt-id>","expected_grade_revision":0,"points_awarded":2,"max_points":4,"feedback":"Correct method; arithmetic error in the final count.","evidence_ids":["<partial-progress-evidence-id>"]}'
```

A defensible rubric is required; no score is invented from a discussion. Positive
points need positive evaluated work, zero needs evaluated incorrect work, and
full credit needs complete correct evidence. Partial subpart grading requires
`allow_partial:true`. A supplied maximum must match the checked rubric maximum
when declared. All evidence must belong to this attempt/learner and match the
current exercise identity and latest submitted part. Include every current evaluated
skill for the parts being scored; omitting an incorrect skill cannot create full credit. Diagnostics continue to use
`record-assessment-item-score`; their score/history is included in attempt history.
Use `feedback_given` events or evidence rationales for diagnostic feedback.

To correct grading, use `correct-evidence` where the evaluation was wrong, then
call `grade-attempt` with the current grade revision and a nonempty
`correction_reason`. Score-only/feedback corrections can reference unchanged valid
evidence. Each grade revision is appended. Old scores and feedback remain;
`is_latest`, `effective_status`, and `evidence_still_applicable` distinguish current,
superseded and invalidated grades. Source/rubric edits and evidence retractions
make dependent latest grades pending review without erasing the previous values.

## Duplicates, similarity and mistake-focused practice

Exact fingerprints preserve mathematical case, operators, punctuation and numbers,
normalizing Unicode NFC and line endings while preserving indentation and layout. Numeric-template hashes and bounded FTS
candidate searches detect likely variants; token overlap proposes additional
similarity candidates. Exact textual matches are linked; similarity stays pending
mathematical review. Questions and attempts are never merged or deleted.

Use `list-question-relations`, optionally filtering `exercise_version_id`, and
`review-question-relation` with its ID/current revision, `confirmed` or `rejected`
status, and reason. Relations retain review history and the compared text hashes;
obsolete matches stop affecting current practice after text changes. The detector
does not establish semantic equivalence and cannot discover every paraphrase.

Default proposals exclude learner attempts, learner/unowned assessment
reservations, exact duplicates, and unrejected similarity candidates, including
within the proposed set. Numeric-template hash groups still prevent repetition
when a large variant group exceeds the bounded relation-candidate list. Explicit
rejections let reviewed distinct variants be selected. Shortfalls are reported
instead of silently repeating. Intentional mistake practice explicitly permits
revisits:

```bash
lumen propose-practice -w '<workspace>' -c '<course_id>' -j '{"learner_id":"alice","count":3,"focus":"mistakes","allow_repeats":true}'
```

Mistake focus selects families whose latest applicable evaluation for a skill/part
is incorrect or partial; later successful work and retracted evaluations remove
that resolved difficulty. Topic filters remain available. Families must describe
actual solution patterns. External practice and unidentified equivalences remain
unknown. Proposals never record a presentation, attempt, reservation or grade.

## Storage and scale

Migration 9 is additive. Existing originals, attempt events, evidence and diagnostic
score histories are preserved; original files stay immutable. New mutations use
the existing atomic transactions, stable request IDs and revision checks. Backups
include the new tables with the existing consistent SQLite snapshot.

Catalog/history reads are paginated (maximum 100 records per stream); catalog
manual writes accept at most 500 questions per batch; automatic exam splitting
catalogs the complete candidate set rather than truncating it at that batch limit. Fingerprint lookups use course/hash
indexes, FTS matching is candidate-bounded (100 hash peers plus 40 text hits), and
selection filters in SQL without loading every reference solution/rubric. A
proposal stops after filling the requested count; `available_families` is a lower
bound when `available_families_is_lower_bound` is true. Exact bank-wide semantic
novelty counts are not claimed. Schema indexes cover course/learner/question
history, evidence lookup and relation endpoints. This remains local SQLite, not a
hosted distributed service.
