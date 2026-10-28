TL;DR: Batch catalog candidates and metadata in one atomic core mutation; use returned revisions.
Status: active; date: 2026-10-20.

# Atomic onboarding

`batch-questions` / `core.batch_questions(course_id, items, request_id)` accepts
1–500 items with a stable request ID. Each item is either:

- `catalog_candidate`: `source_version_id`, optional `exam_label`, one `question`
  using the existing catalog schema, and optional `metadata`.
- `annotate`: `occurrence_id`, `expected_revision`, `metadata`, optional
  `solution_links`, using the existing metadata guards.

Every item runs the original per-item source/course/revision/schema checks.
The outer immediate transaction includes all writes and the single receipt.
`details.rejected_items` identifies every rejected item by zero-based index;
any rejection rolls back the whole payload, including otherwise valid items.
No failed receipt survives; correct the payload and retry. After success, replay
an identical request to retrieve the original result; divergent replay conflicts.
Batching does not confer extraction, visual or mathematical approval.
No model calls, extraction or rendering occur inside this transaction.

`update-exercise-version` accepts `context_blocks` with `question_text`. It builds
complete canonical text and includes an exact context block only once, even when
retrying text that already contains that block. Supply the original reviewed stem
where possible. `current_revision` and `changed` describe the actual saved result;
a no-op has `changed:false` and does not increment revision. Use that returned
revision rather than assuming an increment. Question-text changes invalidate
transcription acceptance. Renew `review-question-occurrence` at its current
occurrence revision before mathematical validation; the error explains this step.
Occurrence revisions and exercise revisions are separate counters.

The four-question synthetic regression measures committed public mutation receipts:
old path 10, batch path 3, including the same course/source setup. The candidate
and metadata phase alone takes 8 versus 1. These are mutation counts, not token,
latency or cost measurements; internal per-item SQL validation is retained.

## Act on readiness blockers

`blueprint-readiness` includes `slots[].review_actions` with version/occurrence
identities, current revisions, overlapping blockers, prerequisite IDs and concrete
public operation names. Inspect the source before extraction/visual acceptance;
recompute answers before mathematical validation. Supply actual review inputs,
then re-read revisions after every mutation. Suggestions are never approvals.
Stale links require reviewed reannotation; include genuine prerequisites in a
matching blueprint slot rather than deleting their relationships to force a fit.
The report reads identities/statuses, not stems or solutions. Unannotated semantic
or lexical references can still block the authoritative assembly check.

`selection_variation.status` distinguishes multiple available selections, a forced
selection, infeasibility and budget-limited uncertainty. It excludes order/option
permutations and does not promise that every seed changes selection. Exact/bounded
counts remain in `analysis.distinct_exams`. Per-slot second-paper family deficits
are marginal hints only; joint capacity and pair/dependency constraints remain hard.
