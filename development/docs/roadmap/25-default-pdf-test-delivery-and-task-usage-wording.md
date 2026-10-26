TL;DR: Verbatim legacy roadmap: 25. Default PDF test delivery and task usage wording.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 25. Default PDF test delivery and task usage wording

Test/exam/practice-paper requests require an actual rendered, visually checked PDF
and a delivery link unless the learner explicitly selects a different format.
This requirement is in goal.md, canonical agent instructions, the general Lumen
skill, and the practice-building workflow. The supplied exam-builder skill was
consulted for its rendered/offline artifact and review requirements, without
reintroducing its personal paths, subject-specific defaults or routing note.

`assessment-paper` exposes a safe saved paper snapshot, eliminating schema
exploration during assembly. `export-assessment` uses that snapshot to render
escaped student text and offline MathML, then prints through native headless
Chrome/Chromium/Edge. Teacher keys/reference solutions/private subpart metadata
are excluded. The create-assessment receipt explicitly reports that PDF delivery
is pending and names export-assessment as the next operation. Missing/failed renderers and unreadable PDFs fail export; successful
printing still requires host visual review. Saved order and version identity are
preserved and export creates no learner evidence or reservations.

Automated checks cover safe fields, course/current-validation gates, question
order, math rendering, CLI retrieval and failed-print handling. No native PDF was
created in this implementation turn at the user's explicit request; native PDF
printing and visual review remain to be exercised by AGY on its next export.

The latest actual AGY assembly session's ledger counters match its transcript:
99,213 raw input, 9,875 output, 753,273 cache-read tokens. That session saved the
three-question assessment but did not deliver a PDF. Task-facing usage notes must
name the delivered result separately from usage and avoid claiming randomization,
a PDF or per-task billing that was not established. Cache inclusion remains
unknown; raw counters are not summed. Tracker health belongs in diagnostics.


