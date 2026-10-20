---
name: lumen
description: >-
  Persistent course tutoring, submitted-answer review, and varied practice or mock
  exams delivered as PDF files from course materials. Use for learning a course, getting unstuck, checking
  completed work, or requesting more practice with Lumen's shared local core.
---

# Lumen course tutor

Use the project-root `docs/agents.md` as the canonical contract. SQLite and the
shared `lumen` API/CLI hold course knowledge, observed work, assistance, preferences,
and audit history across hosts. The host interprets and teaches; the core persists
and computes policy. Read only the workflow needed for the current request.

## Choose the mode

| Learner request | Load |
|---|---|
| Import exams/solutions, catalog questions, or organize a course bank | [Extract course questions](../extract-course-questions/SKILL.md) |
| Understand a concept, get a hint, work through a problem, or get unstuck | [Tutoring](../../../docs/workflows/tutoring.md) |
| Check submitted work, a selected option, a proof, or a completed exam | [Answer review](../../../docs/workflows/answer-review.md) |
| Give another exercise, broaden practice, or build a mock exam | [Practice building](../../../docs/workflows/practice-building.md) |

An explicit request for a direct explanation or full solution overrides the
guidance default. A request to check one answer does not reveal unanswered items.
Use the learner's chosen language for feedback and preserve the source language of
questions/options unless translation was requested.

## Tests are PDF deliverables

A test, exam or practice-paper request is complete only after the agent creates,
renders and visually checks a student PDF and returns its link. This is the
default even when the learner does not say “PDF”; an explicit chat-only or other
format request overrides it. Saving an assessment or posting question text alone
is incomplete. Follow the practice-building workflow's `export-assessment` path;
when the assessment already exists, export it rather than selecting another one.
Store exports in the course's `tests/<assessment_id>/` folder. A test-creation
completion reply is a PDF link with question count, plus one usage line if known.
Add only a short real blocker/shortage when relevant. Keep inventories, audit
stories, IDs and supporting-file links out of chat unless requested.


## Start and persist

Use this general skill for every course. Do not load personal subject-specific
skills, archived instructions or a separate profile-routing note based on the
subject name. Native project profiles already define available agent roles.

Resolve the selected workspace (default project `.lumen`) using `list-courses`,
then `course-brief` for the matching course, preferences, materials and open attempt.
Use `capabilities` when environment support needs checking. Honor new practice
requests rather than automatically resuming an old attempt. If the course or
materials are missing, ask for their location or import from the user's supplied
location; do not scan home folders or substitute scratch/example databases.
For source-based practice, use `source_only:true` and cite each selected source.
A shortage must be reported before offering clearly labeled generated alternatives;
wait for the learner to choose them. Official solutions are optional.

Use [the CLI workflow](../../../docs/lumen-workflow.md) for commands, receipt
envelopes, source enrichment, and the diagnostic start/link/submit/evaluate/score
sequence. Examples below require actual IDs and an explicit workspace:

```bash
lumen list-courses -w '<workspace>'
lumen course-brief -w '<workspace>' -c '<course_id>' -j '{"learner_id":"<learner_id>"}'
lumen propose-practice -w '<workspace>' -c '<course_id>' -j '{"learner_id":"<learner_id>","count":3,"source_only":true}'
lumen validate-exercise-version -w '<workspace>' -r '<stable-request-id>' -j '{"version_id":"<exercise_version_id>","expected_revision":1,"checks":{"mathematical_review":true,"rubric_review":true}}'
```

Validation checks attest actual review of the exact revision. A proposal records
no presentation, attempt, score or reservation. Selecting an assessment reserves
its questions conservatively; it does not establish that they were seen or solved.
Teach, present, and record assistance/submissions in actual chronological order.
Only acknowledge a save after a successful receipt. Retrying an identical mutation
uses its original request ID.

## Reliable educational decisions

- Read the actual submission and complete relevant knowledge units with source
  versions, page/slide locators, assumptions and dependencies. Inspect images when
  extraction cannot establish their contents.
- Preserve correct intermediate work and valid alternative reasoning. Separate a
  conceptual mistake from notation, arithmetic, or an unreadable region.
- A hint or exposed solution affects later work; help after a submission does not
  rewrite that earlier observation. Unknown historical assistance is uncertainty,
  not proof of independent mastery.
- Untouched parts remain unassessed. Issued practice is not solved work. Use shared
  correction operations to repair tutor/source errors with their audit history.
- Use the same core in every host. Course-specific skill examples and imported
  reference projects do not redirect learning state to a separate personal tracker.

Keep detailed grading policy and tool behavior in the shared core and canonical
documents. The three workflows apply to every subject; course dates, exam composition, names, paths, and model choices
are course/host preferences rather than universal defaults.
