---
name: extract-course-questions
description: Extract questions from course exams, solved exams and worked-problem collections, including when no unsolved edition exists; organize sources, review extraction and maintain Lumen tracking through the shared core.
---

# Extract course questions

Follow the project-root `docs/agents.md`, [course layout](../../../docs/course-layout.md)
and [question-tracking contract](../../../docs/question-tracking.md). Use Lumen's
public core/CLI and SQLite; do not create a second authoritative JSON tracker.

Classify each original by its contents, course and role before filing it. A file
named “exam” may contain solutions; a paper may highlight correct choices. Keep
originals unchanged, hash uploads, retain duplicate-upload aliases and exact
source versions. Unknown dates/sittings/points stay null with provenance notes.

Distinguish course reference solutions from the learner's own submitted work.
A learner uploading a solved exam does not mean they authored, read or attempted
its solutions. Keep course-provided solutions as private reference material;
importing or inspecting them creates no learner submission, grade, mastery or
solution-exposure event. Record exposure only when a solution is actually shown
to that learner, and grade only their separately identified submitted answer.
If authorship or purpose is ambiguous, clarify before assessing it as learner work.

Solved exams and worked-problem collections are question sources even when no
separate unsolved paper exists. Extract every recoverable problem statement,
answer choice and subpart from the solved document itself; catalog those questions
and link separately stored private solutions to locations in that same source
version. Keep the original in `sources/solutions/` with its actual role, such as
`solutions_with_statements`. That role does not trigger automatic exam splitting:
explicitly call `catalog-exam-questions` with the reviewed boundaries/candidates.
Do not skip these files or require an unsolved copy before extracting them.
If a document contains only answer letters or derivations without a recoverable
statement, retain the available evidence and flag it for review; do not invent
the missing problem. When an unsolved copy also exists, link matching occurrences
and review duplicates rather than counting the solved copy as fresh practice.

Extract raw text and source locations before splitting. Keep subparts together;
distinguish main question numbers from option numbers and pseudocode. Use stable
course/exam/part/question labels in `annotate-question` metadata. Store question
stems separately from private solutions and link their exact source versions.
Raw search text is not reviewed content. Word OOXML math retains original XML;
its linear representation requires rendered verification. Legacy DOC, OCR, scans,
RTL corruption and diagram gaps remain explicit limitations unless a functioning
conversion/OCR path was actually exercised.

Accept extraction only after comparing the boundaries/transcription with the
original. Record visual review separately with `review-question-visual`; only
attest rendered formulas/options/diagrams actually inspected. Mathematical review
uses `validate-exercise-version` with checked reference/rubric and exact revision;
an official solution is evidence to check, not proof of correctness. Do not mark
the whole bank verified because a few practice questions were checked.

For student output, rebuild selectable text, neutral answer formatting, real
LaTeX rendering and RTL/LTR isolation. Bundle renderer/CSS/fonts for offline use;
verify the rendered result and print output. Keys and feedback belong outside
student HTML/JavaScript. Preserve stable option IDs and each issued version's
saved mapping. Source crops supplement transcription; link each crop to its
source/version/location. Never claim OCR, rendering or visual review from a text
extraction alone.

Importing, selecting, showing, submitting and grading are distinct. Use the
existing attempt/event/evidence/score/correction APIs; acknowledge saves only
from successful receipts. Consult history and reviewable duplicate/similarity
relations before practice. For mock runs, use explicitly named synthetic learners
in an isolated workspace and mark every exported result as simulated. Exported
catalog/tracking JSON is a readable snapshot of SQLite, never a competing writer.

For a reproducible synthetic example, run `python demo.py`. Real originals
belong in the gitignored `local-courses/` folder; public beta courses are pending
in `examples/beta_courses/`. Keep execution logs, rejected operations and
verification limits in the run report.
