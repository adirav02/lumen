TL;DR: Verbatim legacy roadmap: 5. Data model.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 5. Data model

Implement versioned migrations and enable foreign keys on every connection. Enforce course boundaries with composite constraints or equivalent validated relationships. Keep commonly filtered fields as columns; use JSON for bounded flexible detail, not for one whole-course blob.

| Entity or table group | Required information |
|---|---|
| `courses` | Name, scope, language/notation settings, active state, and course revision |
| `sources`, `source_versions` | Logical source, immutable content identity/path, role, active version, and extraction status |
| `topics`, `topic_links` | Course-scoped hierarchy, aliases, and prerequisites |
| `knowledge_units`, `unit_provenance`, `unit_topics` | Full content, summary, kind, assumptions, symbols, dependencies, origin, versions, locators, and fidelity status |
| `exercises` and versioned definitions | Question/subparts, exercise family, topic/skill mapping, reference solution, rubric version, and validation state |
| `attempts`, `attempt_events` | Exercise version, mode, status, ordered observed submissions, assistance, references, and current revision |
| `evidence` | Skill/subpart, observed fragment/event, correctness, prior assistance, evaluator/reference provenance, and correction/retraction history |
| `assessments`, `assessment_items` | Coverage blueprint, selected question versions, attempts, rubric points, exposure, and progress |
| `topic_state` | Rebuildable projection from active evidence with policy version and last included event |
| `learner_settings` | Teaching preference, chosen language, and explicit goals; not evidence of ability |
| `operation_receipts` | Stable request ID, canonical request hash, and committed response |

Use stable IDs; enforce uniqueness for a logical observation and assessed skill, not merely for a freshly generated request ID. Corrections reference prior evidence and remain auditable. Full transcript storage is not required; preserve the actual observed work needed to explain judgments, including attachments and meaningful assistance events.

FTS5 is derived from active searchable content. Update it with content publication or use a controlled rebuild with a revision check. An index rebuild cannot alter learner evidence.

