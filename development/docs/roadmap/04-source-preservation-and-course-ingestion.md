TL;DR: Verbatim legacy roadmap: 4. Source preservation and course ingestion.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 4. Source preservation and course ingestion

### Original files

- Store the exact uploaded bytes before registering a committed reference to them.
- Retain original name, MIME/format, size, SHA-256, logical source ID, source version, upload time, and a relative managed path.
- Use content identity to avoid reprocessing identical bytes uploaded under another name. Keep aliases/upload history distinct from content versions.
- Different content under the same filename creates a new version; do not overwrite the old file.
- Copy through a staging path, verify content, and publish to the managed store before the database refers to the final file. Recover orphaned staged files without deleting referenced originals.
- Store images and derived crops with links to their source version, page index, and region. Source-page index and printed page label are separate fields.

Source-derived units can have multiple provenance entries. Generated explanations, instructor corrections, and generated questions carry explicit origin labels. Faithful extraction does not establish that a statement or reference solution is mathematically correct; track extraction fidelity separately from reference validation.

### Ingestion flow

1. Create/select the course; accept syllabus, lectures, slides, exercises, and optional exams/solutions.
2. Register originals and detect extraction capabilities. Process usable inputs while keeping unsupported inputs available and visibly pending.
3. Extract full page/slide content with locators. Preserve formulas, tables, and diagrams; use a vision/OCR path for uncertain regions when available.
4. Build a course map from supplied material. Treat missing syllabus topics and uncertain mappings as explicit gaps, not inferred coverage.
5. Create semantic units: definition, theorem, formula, method, example, table, or figure. Each mathematical unit retains assumptions, symbol definitions, exceptions, and required dependencies.
6. Validate fidelity against the source where necessary; publish valid units and pending-review items with distinct statuses.
7. Update active-version FTS5 indexes and produce a concise coverage/quality report.

Checkpoint per source version and extraction stage. Cache results by content hash and processor version. New content or a changed processor can be evaluated without discarding checked prior versions. Do not process all files with a model by default if local extraction is sufficient; do not claim local extraction handles every scan.

Source changes identify affected knowledge units, reference solutions, and evidence. Cosmetic changes do not automatically invalidate learner evidence. Changes to assumptions or answers mark dependent evaluations for review, preserving the original assessment history.

