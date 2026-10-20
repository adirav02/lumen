TL;DR: Verbatim legacy roadmap: 18. Organized course extraction and real-material simulation.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 18. Organized course extraction and real-material simulation

Migration 10 separates visual source review, question metadata and solution links
from extraction acceptance and mathematical validation. Identical file uploads
alias the existing course catalog. Source review gates practice, diagnostics and
evidence eligibility; withdrawal preserves old scores/history while rebuilding
derived topic state. Upgrades retain pre-v10 score/projection backups.

Native DOCX extraction preserves paragraph/table/part locators, OMML XML and
linear search text, with equation/image/answer-highlight uncertainty. Legacy DOC
and OCR remain unsupported. Curated imports can defer automatic splitting using
`catalog_questions:false`. Scoped question search reuses FTS.

Use [course layout](docs/course-layout.md), [project profiles](docs/agent-profiles.md)
and the `extract-course-questions` skill. The
[real-course demo](examples/real_course_test/README.md) imports seven originals
into two separate courses: 45 appearances with stable source-bound labels. Only
four algorithms questions are reviewed for practice; the remaining bank stays
pending. Three reviewed questions form a selectable offline KaTeX/RTL practice
and visually inspected two-page PDF, with private saved keys and version manifest.

Acceptance: 197 automated tests, including the isolated real-course simulation,
visual-review withdrawal/upgrade score preservation, DOCX fidelity and duplicate
aliases; synthetic probability demo; actual local browser/math/font checks and
visual inspection of the PDF. Mock attempts exercise errors, hints, retries,
grading corrections, partial diagnostics, repetition policy and backup/restore.
Independent educational verification and bounded profile/skill forward tests
are recorded separately from live-host integration. Existing host release gates
remain open; this run does not establish fresh host execution of the new features.


