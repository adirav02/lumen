TL;DR: Deduplicate family evidence in adaptive selection; result recording already exists.
Status: proposed implementation brief; date: 2026-10-20.

# Record results: smallest remaining slice
## Goal
Use recorded per-question results to adapt selection within hard blueprint constraints,
without treating repeated questions or known variants as fresh independent evidence.
Basis: goal.md, Meaning of assessment, Question tracking, and Efficient test generation.
Code inspected at 922508d; this brief proposes work, not a completed feature.

## Already implemented
- `api.py:726` exposes idempotent `commit_evidence`; `learning/service.py:206`
  validates submitted work, records skill/subpart outcomes and assistance, and
  atomically recomputes affected topic states. `correct_evidence` preserves audit history.
- `assessment/diagnostic.py:338` records linked item scores with current-version,
  evaluated-evidence and required-subpart gates; practice grades and feedback use
  `questions/history.py:49` (`grade_attempt`). CLI operations expose these paths.
- `storage/repositories.py:1670` rebuilds topic state; independent successes count
  distinct learner/family/skill/subpart units, retaining every observation.
  This projection is course/topic scoped; adaptive selection separately scopes learners.
- `assessment/assembly.py:36` already derives private weakness/novelty weights from
  eligible learner evidence, neutralizes unknown topics, and retains evidence IDs.
  Seeded selection preserves hard constraints and saves selection inputs in snapshots.
- `tests/test_exam_assembly.py:264` covers learner isolation, neutral observations,
  obsolete identity exclusion and preference toward weak topics.

## Exact scope
Close the family-diversity gap in `_weights`: its current per-attempt query allows
retries and same-family variants to change evidence count and mean as fresh samples.
After existing eligibility and latest-submission checks, contribute at most one
representative per (topic, exercise family, skill, subpart), scoped to course/learner.
Choose the latest eligible submission by persisted submission creation time, with
submission ID then evidence ID as deterministic ties; never compare event indexes
across attempts. Corrections retain submission chronology. Keep the existing outcome
scores and weight formula; count representative units for novelty and mean score.
Retain contributing evidence IDs and document/version the changed selection policy.
Preserve all historical observations, grades, topic projections and saved assemblies.

## Acceptance criteria (automated)
1. Public submission/evidence calls followed by preparation change the intended topic's
   weight; repeated identical outcomes on the same question or same-family variant
   leave that weight unchanged. A distinct family contributes another unit.
2. A later eligible changed outcome replaces that unit's contribution; correction or
   retraction recomputes weights from remaining eligible representatives on next prepare.
3. Other learners/courses, pending observations, superseded/retracted evidence, stale
   identities and failed source-review gates contribute nothing; unknown stays neutral.
4. Evidence IDs identify exactly the contributing representatives; deterministic ties
   and a fixed seed yield stable selection. Hard counts and family exclusion still hold.
5. Preparation writes no learner state; saved assemblies retain their original weights
   and re-export snapshots after later results. Existing scoring/idempotency checks pass.

## Out of scope
New result-recording API/CLI, schema migration, topic-state redesign, calibrated mastery,
pass predictions, automatic weight tuning, semantic family discovery, UI or host rollout.

## Likely files and validation
`src/course_tutor/assessment/assembly.py`, `tests/test_exam_assembly.py`; inspect existing
`learning/service.py`, `learning/policy.py`, `questions/history.py`, storage repositories
and snapshot tests as contracts. Run targeted tests through `scripts/run_tests.py`;
run the full suite once after implementation. This task commits only the brief/index.
