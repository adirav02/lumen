TL;DR: Verbatim legacy roadmap: 24. Course discovery and general workflow cleanup.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 24. Course discovery and general workflow cleanup

`list-courses` exposes the selected workspace's registered courses through the
public core/CLI. Source-based practice uses explicit `source_only:true`, excluding
validated generated questions without accepted source occurrences. Candidates
return immutable source version/hash, filename and question spans for citation.
Missing courses/materials and source-only shortfalls must be reported; the tutor
must not substitute scratch/example databases or silently generated questions.

All project profiles are course-neutral (`course_lookup`, `course_practice`,
`course_reasoning`, with hyphenated Claude names). Removed obsolete imported
subject-specific skill/profile copies and the redundant Hebrew routing note.
Canonical skills remain in `.agents/skills`; Claude discovery pointers remain
because the hosts require separate discovery locations. Course originals and
learner databases are preserved. The first live check found no registered courses in `.lumen`. After the user
explicitly selected the example course collection, its hash-verified originals
and source catalogs were imported through public operations into `.lumen`, with
no mock learner state. Algorithms has 37 occurrences, including 3 retained checked
questions with matched prior review/render/reference evidence; probability has
8 pending questions. Replay did not duplicate course/question records.


