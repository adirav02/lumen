# Broader educational evaluation

Prepared/reviewed on 2026-10-19. All 16 cases are generated fixtures, newly added
to this repository. They broaden the earlier probability/course workflow with
algebra, calculus, graphs, formulas, diagrams, ambiguity and Hebrew option order.

| Artifact | Meaning |
|---|---|
| `cases.json` | Questions, submitted work, actual assistance order, image references; no reference answers |
| `graph.png`, `graph-unknown.png` | Directed graph and deliberately missing edge label; both visually inspected in this Codex session |
| `checked-references.json` | Self-contained derivations, locators, expected review actions and evidence policy |
| `review-2026-10-19.json` | Captured review decisions and feedback from the authoring Codex session |
| [Recorded result](../../docs/evaluation/education-2026-10-19.json) | All cases retained, compared with references and exercised through shared core policy |
| `build_diagrams.py` | Reproducible generated diagram builder using Pillow |

References and captured reviews were prepared in the same session with reference
access. This is **not blind or held out**, not human review, and not a fresh-host
model run. The runner invokes no model and cannot decide whether arbitrary prose
or a new image was graded correctly. A passing comparison establishes agreement
with these reviewed fixtures and core persistence/classification behavior.

## Reviewed coverage

The review accepts an exact Bayes fraction and an alternative parity proof;
separates correct setup from arithmetic mistakes; retains domain restrictions
after cancellation and squaring; handles covariance and the negative domain of
`ln|x|`; uses the actual displayed Hebrew option; and evaluates only the submitted
Bernoulli expectation part. Feedback does not reveal the untouched variance part.

The visible graph's path and weights were inspected against the PNG, not inferred
only from filenames. The missing middle weight can change the shortest route,
so the ambiguous-image case requests clarification. A submission with no proof
also requests work rather than inventing mastery. An inconsistent variance key
is rejected pending reference repair. Earlier independent work remains independent
after a later solution; a prior denominator hint makes later work assisted.

This review found no mismatch in those captured decisions. The incorrect source
key is a deliberate failure probe, not an application failure hidden from totals.
Arithmetic reference checks use exact fractions; graph checks enumerate paths and
all simple four-vertex graphs. Derivations also state the general arguments;
finite enumeration alone is not a proof of the general theorem. Educational
feedback was read in this session for correctness, focus and untouched-part
leakage; that qualitative review is not automatically checked by the runner.

## Reproduce

```bash
.venv/bin/python scripts/evaluate_education.py \
  --reviews examples/educational_evaluation/review-2026-10-19.json \
  --output scratch/education/replayed-result.json
.venv/bin/pytest -q tests/test_educational_evaluation.py
```

The runner requires every case exactly once, retains mismatches and reports
critical false confirmations separately, then exits nonzero
on a failed comparison. Tests deliberately inject a wrong judgment to check that
it stays in the result set. Disposable workspaces exercise only the reviewed
grading decisions; ambiguity/reference conflicts do not create confirmed evidence.
No real learner history is changed.

## Next: actual unseen-answer review

Freeze a new set of representative real/permissioned submissions with source
versions, assumptions and independently checked references. Include scanned
formulas, handwritten diagrams and ambiguous regions. Keep those references out
of the tutor's prompt/context until its first response is saved. Do not call the
current published fixtures unseen in subsequent runs.

Capture each host/version/model, exact prompt/retrieved sources, first response,
image inspection and any clarification before looking at the key. A separate
reviewer checks reasoning, assumptions, exact-version attribution, error type,
feedback usefulness and solution leakage. Record all failures, retries, critical
false confirmations and pending clarifications, and use the usage ledger for
every model call. Capture actual model decisions in the same JSON structure as
the review file; the comparison runner accepts that file, but prose quality and
image interpretation still require an independent review. Changes to fixtures or
rubrics require a newly versioned artifact, not retroactive rewriting of results.

The M5 educational gate remains open until that real-host unseen evaluation is
reviewed. Sixteen authored cases do not establish general teaching accuracy.
