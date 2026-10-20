# Build varied practice

Use for one exercise, more practice, a diagnostic or a mock exam. Follow
`docs/agents.md` and the learner's actual constraints. Course year ranges, exam
composition, topic labels and language defaults come from the course/user; the
original algorithms project's specific defaults are not Lumen-wide rules.

## Required test deliverable

A request to create a test, exam, mock exam or practice paper requires an actual
student-facing **PDF file by default**, including short tests. The learner does
not need to add “PDF” to the prompt or approve a second export step. Only an
explicit chat-only or other-format request overrides this. A saved assessment,
a question list in chat or a proposed selection is not a completed test.

Use the public CLI below; do not reverse-engineer SQLite tables or read core
implementation files during routine assembly. The selected candidate data and
`assessment-paper` provide the student-safe fields needed for rendering.
If source questions or a renderer are unavailable, report the specific blocker
and leave the test visibly incomplete instead of silently delivering text.

## Propose before recording

Use `list-courses -w '<workspace>'` to identify the course in the active workspace,
then read its `course-brief` and source inventory. If no matching course or supplied
sources are registered, report the missing material and use the user's supplied
location for import, or ask for it. Do not query scratch/example databases or load
personal subject-specific skills as a fallback.

Requests to practice the course material use source-bound questions by default.
Set `source_only:true`; this excludes generated exercises without a cataloged source
occurrence. Each issued question must cite its actual source filename, version and
page/section/question location. Do not claim coverage of material you did not retrieve.

Read the course brief and recorded practice history. Ask the core for checked
candidates, optionally filtering topics and excluding the current batch:

```bash
lumen propose-practice -w '<workspace>' -c '<course_id>' -j '{"learner_id":"<learner_id>","count":3,"source_only":true,"topic_ids":["<topic_id>"],"exclude_exercise_version_ids":["<already-selected-version>"]}'
```

The result includes each candidate's revision/hash, family, prior attempt count,
assessment-selection count, and a shortfall. It exposes question text and source
references, not the private reference solution or rubric. This is read-only:
proposing does not mark a question presented, solved, or reserved.

For uploaded exams, start from the source-bound [question catalog](../question-tracking.md).
Candidates with unaccepted extraction stay out of practice. Selection now also
filters exact textual duplicates and unrejected similarity candidates, including
within a batch; these heuristics supplement family labels. Use
`focus:"mistakes",allow_repeats:true` for intentional revisits of the latest
recorded incorrect/partial family-skill work. Filled proposals report available
families as a lower bound rather than counting the entire remaining bank.

By default the command excludes families with prior attempts for this learner or
assessment reservations for this learner/unowned drafts, and returns at most one
candidate per family. A reservation means the question was selected, not that the
learner actually read or solved it. History outside the active Lumen course is
unknown. Recheck selection before issuing a set; proposals are not atomic delivery
reservations against concurrent work.

## Broaden the reasoning, not just the numbers

A family should describe a specific problem/solution pattern, not a whole subject
such as “calculus” or “graphs.” Review the setting, inputs, requested result, method
structure and central idea. Different dates, numbers, variable names or answer
orders do not establish a new learning opportunity. Family labels help the core
filter history; they do not replace a conceptual comparison among the proposed
questions and the current batch.

Honor explicit topic/date/source/difficulty constraints using verified metadata;
do not infer missing years or silently broaden the request. If there are too few
fresh questions, say how many are missing and offer a concrete alternative. Use
`allow_repeats:true` only when revisiting exposed/reserved families is requested
or agreed; the output retains its exposure labels. A weak area may justify an
intentional revisit, but should not hide untested coverage.

If no suitable bank question exists, report the shortfall and offer clearly labeled
generated alternatives. For a source-based request, wait for the learner to choose
that alternative before issuing it. Check the actual solution, assumptions and rubric
before validation. Never silently replace supplied-source practice with generated
questions or claim a generated adaptation came from an official paper.

## Prepare a learner-facing version

Verify transcriptions against the original page/image, including inequalities,
tables, indices and diagram labels; OCR alone is insufficient. Preserve original
question/option language unless translation was requested. Keep explanations in
the chosen learning language. Record meaningful editorial corrections transparently.

Use clean text/math and legible diagrams. Give every option the same visual
treatment. Keep answer keys, correctness flags and explanations out of student HTML,
JavaScript, embedded data and PDFs. A key hidden in a browser payload is still a
disclosed key. For complex formulas, render them rather than printing raw math
source. Support RTL prose with LTR formulas when needed. Verify the actual artifact
and offline behavior before delivery; use the relevant artifact skill when available.

Preserve uploaded option order by default. For an explicitly requested shuffled
version, assign stable option IDs and establish a checked mapping. Existing core
storage can hold it in the versioned teacher-only `rubric`, for example:

```json
{"max_points":4,"choice_presentation":{"version":"practice-v2","label_to_option_id":{"א":"o3","ב":"o1","ג":"o2"},"correct_option_id":"o1"}}
```

This is a metadata convention, not an automatic shuffle or grading API. Verify
that every option appears once, the key still points to the right text, and labels
match the actual artifact. Cross-references such as “both A and C” require a
verified rewrite or preserving the original order. Keep the map fixed within a
version. If the mapping is uncertain, do not issue a shuffled paper or grade by
guessing letters.

Create each separately issued variant using `create-exercise` with the same
`exercise_family` and a distinct exercise-version identity; preserve source
question identity in `external_ref`. Store the rendered question/options and
teacher mapping together, validate that exact revision, and associate it with its
assessment. Do not edit an already issued version just to produce a second paper:
that would invalidate its old attempts. A real source/rubric correction should use
the existing revision/correction workflow and retain the audit trail.

## Export the saved test and verify it

After selecting checked versions, create the assessment once with a stable request
ID and use its returned `assessment_id`. Then run:

```bash
lumen assessment-paper -w '<workspace>' -c '<course_id>' -j '{"assessment_id":"<assessment_id>"}'
lumen export-assessment -w '<workspace>' -c '<course_id>' -j '{"assessment_id":"<assessment_id>"}'
```

`assessment-paper` returns the saved question order, wording and source citations
without keys or reference solutions. `export-assessment` renders that paper to
offline HTML/MathML and a PDF through an installed Chrome/Chromium/Edge browser.
The returned `pdf_path` is the deliverable; do not guess its path. The default is
`<course_directory>/tests/<assessment_id>/test.pdf`. `list-courses` and
`course-brief` return the resolved course directory; imported collections use
their course folder, while new workspace-only courses use
`<workspace>/courses/<course_id>`. A different destination
may be supplied with `output_directory`. No source files or learner records are
modified by export. An existing saved assessment should be exported directly;
do not re-propose or reserve another test merely because its PDF was missing.

Use the PDF skill available in the host to render every PDF page to an image and
inspect it before delivery. Check original-language text, RTL prose/LTR formulas,
all options and subparts, source citations, page breaks, font rendering, clipping
and the absence of keys/answer cues. MathML is rendered math, not raw LaTeX text.
Keep supporting HTML offline with no CDN dependencies. If a formula, table or
required diagram is not reproduced faithfully, repair the presentation and
repeat rendering; do not change the mathematical question or answer order silently.
The exporter reports `rendered_pending_visual_review`, never a fabricated visual
approval. Record actual artifact review in the accompanying presentation manifest
only after inspection. Corrections retain the same assessment/version and stable
option mapping; a new test receives its own identity.

## Keep delivery replies minimal

For test creation, the final reply defaults to **two short lines**:

```text
[Test PDF](<returned pdf_path>) — 3 questions.
Session tokens: <input> in / <output> out / <cache> cache-read (cache inclusion unknown).
```

Only include usage when the associated session is known. Add at most one short
sentence for an actual blocker or shortage affecting the requested test. Preserve
source citations inside the PDF and audit checks in the manifest; do not repeat
bank inventories, source tables, assessment IDs, verification checklists, HTML or
manifest links, or workflow stories in chat unless requested. Do not expand the
reply just to demonstrate that the work was done. Correctness and actual PDF
inspection remain required; keep the completion message short.

Use `course-brief.open_assessments` to find an existing saved test and its PDF path.
An empty fresh proposal may mean checked questions are already reserved, not that
the bank is broken. Reuse a saved assessment only to complete or resume that
specific test. For genuinely new practice, report the fresh-question shortage;
never relabel an old test as new. Export the existing requested test instead of guessing SQL
schemas, inspecting source code or reserving another assessment. Browser discovery
checks known installed paths and Playwright caches automatically; do not run a
filesystem-wide browser search.

Usage is session-wide unless task-only attribution is established. Raw
input/output/cache-read counters remain separate when cache inclusion is unknown;
do not sum them or call them billed cost. See
[usage reporting](../usage-measurement.md#task-facing-usage-notes).

## Issue, assist and evaluate separately

Once the selection and presentation are checked, use `create-assessment` with the
actual selected version IDs and learner ownership. Confirm its receipt before
claiming it was saved. It is a reservation/coverage plan, not automatic question
generation or proof of delivery. Start a linked diagnostic attempt when working
on an item; for ordinary practice use the practice attempt workflow. Record a
`question_presented` event when actually presented, and record hints, submissions,
and evaluated work separately in actual order. Do not create fake submissions or
assistance merely to reserve a question.

On checking a submission, use [answer review](answer-review.md) and the exact issued
version's mapping. Track partial progress and prior exposure without inflating
mastery. A reprint or cosmetic rendering change is not fresh independent evidence.


## Saved blueprint assembly

Use the [saved blueprint command and JSON](../lumen-workflow.md#assemble-from-a-saved-blueprint)
when hard section/topic/type counts are known. `assemble-exam` checks readiness,
saves immutable selections and publishes a PDF in one command. Strict-only policy
rejects nonempty ordered relaxations, including authorized unsupported policies;
option shuffling is unsupported and original option order is retained. Shortages
return structured gaps without creating an assessment or artifacts. Stable request
IDs replay the same receipt and reject changed input. Linux atomic no-replace
publication and a PDF browser renderer are required; dead-owner recovery never
steals a live job. Re-export reads saved snapshots without selecting again.

The returned summary remains pending visual review. Perform the page-image review
and clickable PDF delivery described above; publication does not establish visual
approval, delivery or learner progress.

## Retire unused reservations

Use [release-reservation and expire-reservations](../lumen-workflow.md#release-or-expire-unused-reservations)
with explicit course/learner assertions and stable mutation request IDs when an
unused draft is abandoned. `reason:"cancelled"` is accepted for explicit release.
Expiry is an on-demand sweep after seven days from original creation in server
UTC, with no background or implicit read-time release. Only unused open/paused
drafts qualify; linked attempts, score state/history, live publication locks and
recovery-required completed renames protect work. Expiry reports skipped reasons;
recover publication with its original assembly request when required.

Released pending jobs cannot resume under the same assembly ID. Retiring a
reservation preserves assessment/audit history, exposure and saved-snapshot
re-export. Prior attempts still exclude their families. Readiness's
`without_safe_releases` reports safe draft relief separately from removing all
reservations; inspect that result before deciding to release or grow the bank.
