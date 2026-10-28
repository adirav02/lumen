TL;DR: Deliver explicitly reviewed source PNG diagrams offline from immutable assessment snapshots.
Status: active; date: 2026-10-28.

# Reviewed question diagrams

Ingest a question-only PNG through `ingest-source` in the same course. Preserve
its original bytes. Inspect the actual entire image, labels, units and relation
to the question; an image-only extraction remains uncertain until that review.
Do not attach a source page containing adjacent solutions or instructor notes.
This feature accepts whole static PNGs, not arbitrary files, URLs, SVG, JPEG,
PDF pages or unreviewed crops. A crop needs a separate reviewed source identity;
automatic cropping/OCR and semantic figure matching are not implemented.

Use the existing versioned rubric and `validate-exercise-version` operation:

```json
{
  "version_id": "question-version-id",
  "expected_revision": 1,
  "reference_solution": "Your independently verified private solution",
  "rubric": {
    "max_points": 10,
    "student_assets": [{
      "source_version_id": "ingested-png-source-version-id",
      "alt": "Reviewed accessible description of the supplied inputs",
      "caption": "Figure V1",
      "review_notes": "Private record of actual whole-image inspection"
    }]
  },
  "checks": {"mathematical_review": true, "visual_assets_reviewed": true}
}
```

The strings above illustrate fields; they are not evidence of a completed review.
Source-question extraction and applicable visual review gates still apply.
Validation requires the explicit passing `visual_assets_reviewed` check, binds
source version, SHA256, MIME, filename, version and `whole_image` region, and
records them in exercise content identity/history. Asset changes through the
normal rubric update withdraw validation and require fresh exact-version review.
The visual-context digest also binds reviewed dependency/disclosure relationships:
changing a diagram or its public text makes those links stale until reannotated.
Unrelated point/private-note changes do not change that visual digest. Legacy image
attestations without a digest require renewed relationship review, preserving history.
Read the returned revision rather than assuming whether it incremented.

# Selection, student boundary and re-export

Assembly verifies immutable source bytes, PNG signature/chunks and dimensions,
then freezes exact image bytes and provenance in its private saved snapshot.
Missing/corrupt/changed assets block new assembly and live previews. At most four
PNGs per question, each at most 2 MiB and 10 million pixels, are supported.
No filesystem path or external URL can be supplied as an asset input. Source
identity must belong to the same course. Private review notes and rubrics never
enter student HTML/JSON; only the explicit image projection and provenance do.

Student HTML embeds hash-checked PNG data directly and permits only data images
in its content security policy. PDF rendering needs no image network access.
Aspect ratio is retained; diagram questions use the instructed extra paper rather
than a fixed blank answer block that could create an otherwise empty page.
Inspect every printed page; successful PNG extraction/validation is not visual QA.

Published assembly re-export uses frozen image bytes and survives later bank
changes or missing original copies. Original-source preservation remains required;
snapshot independence is not permission to delete originals. Legacy/manual papers
and previews recheck live sources; use `assemble-exam` for immutable presentations.
Existing publication ownership, cancellation and receipt replay remain unchanged.
Keep earlier exports when changing presentation or renderer versions: HTML/PDF
bytes may differ across renderer versions even when question snapshots are equal.
