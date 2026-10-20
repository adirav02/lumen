# Course folders and data ownership

Each course has one stable folder under a course collection. Private materials
live in the gitignored `local-courses/<course-id>/` folder. This repository ships
synthetic fixtures only; public beta courses are added next under
`examples/beta_courses/`. A private course folder can have this layout:

```text
<course-id>/
  README.md                 Start here: scope, material map, commands and limits
  course.json               Course ID, source inventory and explicit metadata
  sources/
    exams/                  Original question papers, unchanged
    solutions/              Original keys and worked solutions, unchanged
    lectures/               Original teaching material
    submissions/            Original learner uploads
  catalog/
    source-review.json      Source classification and uncertainty
    question-boundaries.json Main-question/solution locations and stable labels
    questions.jsonl         Readable export of the core catalog; no answer keys
    relations.jsonl         Exact/similar candidates and their review status
    review-queue.json       Remaining extraction/visual/math review
  private/
    solutions.jsonl         Source-linked extracted solutions, unverified by default
    presentation-keys.json  Issued option mappings and checked teacher references
    evidence/               Source-render crops and source/version/hash manifest
    review/                 Independent mathematical verification evidence
  practice/
    student/                Selectable, offline rendered questions; no keys
    assessment.json         Version identity and selected question IDs
  tracking/
    mock-results.json       Explicitly simulated learner/history snapshot
  reports/
    simulation.json         Run ID, checks, rejected operations and limitations
```

Directories are created when they have content. A course README links to every
useful generated artifact; avoid unexplained scratch files or duplicated sources
at the collection root. Preserve original filenames. Classify the course and
question/solution role from internal content, leaving unconfirmed metadata null.
Source hashes and stable course/exam/part/question labels survive folder moves.

SQLite in the selected workspace is authoritative for sources, catalog reviews,
attempts, assistance, scores, corrections and receipts. The JSON files above are
inputs with source provenance or read-only exports; editing an export never
changes learner history. Every export identifies its workspace/run and whether
it contains mock data. Rebuild through public core operations, never by merging
independent tracking JSON back into SQLite.

Private originals, catalogs, practice exports and runtime databases must remain
in ignored local storage. The public repository includes no real-course sources,
review snapshots or simulation database. Only `practice/student/` is served as
student content; the authoring course folder and `private/` are not a student web
root.

The extraction skill routes imports/review/tracking through the same architecture.
PDF/DOCX/image capabilities are explicit. OCR and legacy DOC conversion are not
core capabilities; keep those documents pending or use a verified host adapter.

Raw core extraction snapshots live in `catalog/raw/` or `private/raw/` according
to source role. Historical text-only preflight snapshots live in matching
`preflight/` folders so boundary decisions remain reproducible. Source crops stay
private when the original contains an answer, annotation or highlighting. Artifact
presentation status is stored in the version's manifest, separately from question
extraction, visual source review and mathematical validation in SQLite.


## Use an existing collection for real practice

A supplied collection may contain real originals and catalog exports alongside
mock history. Import the originals and source-bound catalog into the active
workspace rather than using its simulation database:

```bash
.venv/bin/python scripts/import_course_collection.py local-courses --workspace .lumen --retain-reviewed
.venv/bin/lumen list-courses -w .lumen
```

The importer verifies all source hashes before writing and uses stable request
IDs for replay. It reads no tracking exports or simulation databases and creates
no learner settings, attempts, exposure, evidence, grades or assessments.
`--retain-reviewed` retains prior reviews only when an exact teacher question,
source hash, recorded reviews and hash-verified source-render evidence match.
Other questions remain pending. Import counts and checked practice capacity
depend on the locally supplied collection; no private bank is bundled here.


## Test export folders

Learner test exports live in `<course-directory>/tests/<assessment-id>/test.pdf`,
with supporting HTML, rendered review pages and the presentation manifest beside
that PDF. Originals and private teacher keys remain in their existing folders.
The exporter resolves the course directory from its registered catalog import
origin and verifies the matching `course.json`. It does not scan other folders.
A course without an import origin gets `<workspace>/courses/<course-id>` as its
course directory. Ambiguous or unavailable recorded roots require an explicit
`output_directory`, rather than silently writing into an unrelated course.

`list-courses` includes `directory`. `course-brief` includes `course_directory` when saved assessments need it,
and up to ten learner-scoped `open_assessments` with their PDF paths/existence,
so a reserved test can be exported without querying SQLite or reading source code.
Private course sources and generated tests under `local-courses/` are ignored by Git.
