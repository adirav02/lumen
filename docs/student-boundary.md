TL;DR: Serve only the student projection; originals and raw retrieval are tutor-only.
Status: active; date: 2026-10-20.

# Student content boundary

`student-preview`, `student-search`, `assessment-paper` and `export-assessment`
project through `course_tutor.student.student_question`. It allows reviewed stems,
shared setup/data already incorporated into those stems, subpart wording, points
and minimal source citations. It never follows source paths, solution links,
private references, rubrics, review artifacts or arbitrary metadata. PDF and HTML
use this projection too. Search matches approved question text, never raw sections.

Use `--audience student` on a student CLI integration: all other operations are
rejected before opening the workspace. `capabilities` is also permitted. Tutor
commands include `search`, `read-units`, `read-source-region`,
`get-extracted-sections`, `list-questions`, `search-questions`, annotation,
validation and all mutations. These may expose mixed-source instructor answers.
Never publish their responses or serve the course root to students.

`student_preview` and `student_search` are the safe core API entry points. They
require validated versions and applicable extraction/visual reviews. Saved assembly
papers use their immutable reviewed snapshots; current draft papers check current
review status. A tutor must check transcription boundaries before accepting them:
an answer mistakenly approved inside a stem cannot be removed by a field allowlist.
This is an application content boundary; it does not restrict a workspace owner's
filesystem access. A web service must expose only the student entry points and
student artifact directory, with its own authentication/authorization.
