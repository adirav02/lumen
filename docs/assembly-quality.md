TL;DR: Preserve exam instructions and source bytes; reject unsafe question combinations.
Status: active; date: 2026-10-26.

# Assembly and export quality

Use existing `annotate-question` with `expected_revision`, a stable `request_id`,
and either metadata field below. Links are directional and course-scoped:

```json
{
  "depends_on": [{"exercise_version_id": "prerequisite-version", "part": "a"}],
  "gives_away": [{"exercise_version_id": "spoiled-version", "part": "b"}]
}
```

`part` identifies the target part; optional `from_part` identifies the source
part. Omit part keys for a whole question. The core validates targets and part
keys, adds source/target identity hashes, and records the metadata revision and
history with its mutation receipt. Supply an empty list to remove a relation.
These are explicit reviewed judgments; lexical similarity does not discover them.
After changing either stem or subparts, reannotate affected relations. Stale
relations block selection until reviewed; unrelated reference/rubric changes do
not invalidate a text relationship.

Assembly rejects missing prerequisites, cycles, stale constraints and pairs that
disclose answers. Prerequisites precede dependents in the saved order; this can
move a question ahead of another section. Section membership and counts stay hard.
Manual `create-assessment` rejects a forward dependency instead of reordering the
caller's selection. Private snapshots retain the checked relations. Existing saved
papers remain reproducible; new annotations do not rewrite old snapshots.

HN101's unchanged FE01, FE04 and FE05 originals have hash-bound reviewed rules:
FE01 Q2 depends on Q1(a); Q8 discloses Q3(a) and the Q7 change. FE04 Q2 depends
on Q1(b); Q8 supplies Q1(b)'s intake. FE05 Q2 depends on Q1(a); Q8 needs Q1's
case/body mass and supplies Q2(a)'s maintenance intake. Cataloging records these
annotations without granting extraction, visual or mathematical acceptance.
Readiness also enforces the known rules on banks cataloged before this repair.
To persist those annotations in an existing workspace, run:

```sh
lumen apply-known-question-constraints -w WORKSPACE -c COURSE -r STABLE_REQUEST_ID
```

No course source file is changed. Different source hashes require new review.

# Paper settings

Blueprints accept `instructions`, a list of nonempty student-facing strings,
and positive finite `duration_minutes`. Carry forward the reviewed source's
answer policy, permitted materials, rounding and extra-paper directions explicitly.
All five unchanged HN101 final papers share checked general rules; when instructions
are omitted those rules are captured in the saved effective blueprint. An explicit
list, including an empty list, overrides that default. Original source point
allocations are not inherited into a differently assembled paper.

Both assembly and manual saved assessments print instructions, duration, total
item points, name/date lines and CSS page/total-page counters. Leading source
question numbers and standalone source question-ID/points labels are removed only
while rendering the student paper. Stored stems and citation question keys remain
unchanged. Export reuses saved settings and selections.

# Readiness

`warnings` identifies every slot with fewer than three eligible question versions:
“seed has little or no effect”. Answer-disclosure warnings identify prohibited
pairs even when a safe alternative exam exists. `question_constraints` gives
private directional review details.

`analysis.distinct_exams` counts complete version-to-slot selections. Order inside
a slot and option permutations do not make a new exam. Alternatives may reuse
families; this differs from `analysis.capacity`, which measures disjoint tests
without family reuse. Both honor eligibility, family and pair constraints.
Distinct-exam enumeration is bounded; `count:null` and lower/upper bounds report
budget exhaustion honestly. Dependency-aware disjoint capacity may also remain
bounded. Exact counts are not a promise that different seeds produce every choice.

# Original bytes and extraction

Ingestion's immutable store copies raw bytes and saves their SHA256 as
`source_versions.file_hash`; it does not rewrite CSV line endings. Text extraction
intentionally decodes, converts line endings to LF, splits heading sections and
trims boundaries for retrieval. Each new text section records `original_sha256`,
`extracted_text_sha256` (UTF-8 of that exact stored section), and a normalization
description in its metadata. The processor identity is bumped, so fresh requests
reprocess older results; old versions and idempotent receipt replays stay intact.

The checked-in HN101 CSV files already have LF line endings in Git. Earlier upload
bytes cannot be reconstructed from them. Regression tests ingest CRLF copies of all
15 CSVs and verify byte identity, original and extracted hashes, plus retries.
Git attributes disable future text EOL conversion for these example originals.

# Cancelled and replaced exports

`release-reservation` (including `reason:cancelled`) and `expire-reservations`
write a `superseded.json` sidecar beside owned default/job artifacts after committing
terminal disposition. PDF, HTML, manifests and job snapshots are preserved; the
sidecar explicitly marks the complete set superseded. Foreign or ambiguous files
are never adopted or deleted. Retry the same request after a filesystem failure:
the saved receipt replays and reconciles missing sidecars. Active publication and
rename-before-commit recovery protections still apply.

For a replaced export or an export in a custom directory, use the public operation:

```sh
lumen supersede-export -w WORKSPACE -c COURSE -r STABLE_REQUEST_ID \
  -j '{"assessment_id":"OLD","output_directory":"/absolute/export/path","replacement_assessment_id":"NEW"}'
```

The replacement ID is optional and must belong to the same course. Ownership is
validated before saving a receipt; retry completes an interrupted sidecar write.
This operation marks exports; release the old reservation separately when desired.
`course-brief` flags terminal reservations as superseded;
`export-assessment` reports `export_status:superseded` on retired artifacts,
including re-exports of a cancelled assessment. Custom directories are not scanned;
pass their exact path to supersede them. File publication still requires independent
visual review before delivery.

# Local references and catalog refresh (2026-10-28)

Assembly resolves reference candidates through current reviewed `depends_on`
links, exact exercise versions, target parts and source occurrence versions.
For references across source papers, supply `reference_text` quoting the exact
reference (for example `Question 1(a)`) on the reviewed dependency. Identical
numbers in another source never establish a relationship. Missing, ambiguous or
stale relationships block publication. Structured subpart wording is preserved in
manual papers, and exact review quotes can occur in the stem or a subpart. Keep necessary setup in the target item;
review shared-context groups and all subparts for answer disclosure. Lexical
matching only flags candidates; it cannot certify semantic completeness.
Private assembly snapshots retain original wording and detached presentation text;
re-export uses the saved presentation, unaffected by later bank annotations.

Catalog processor version 4 removes whitespace-only boundary spillover while
conservatively retaining visual/uncertain sections even without text. To reprocess
an older catalog, ingest the unchanged original with a **fresh request ID** and
review the resulting source/exercise versions. Existing accepted catalogs and
saved papers remain unchanged; old request IDs replay their original receipts.
Do not rewrite historical source spans in place. Reviewed non-contiguous spans
remain supported through explicit source spans.
