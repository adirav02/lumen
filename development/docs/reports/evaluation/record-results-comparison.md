TL;DR: Solo used fewer tokens/calls; its corrected branch meets all five criteria.
Status: evaluated 2026-10-20; branches compared without merging.

# Record-results comparison

Main/base: `6e363b8`; solo: `81bd26c`; delegated: `64f2236`.
Collector: existing `python3 scripts/collect_native_usage.py --repo "$PWD" --task work/20261020-record-results-{solo|delegated} --json`, run separately for each task.
Windows below are the task status.json started_utc/ended_utc, inclusive.
Counts are observed native records, deduplicated by the collector; root excludes children.
Cached is included in input; fresh = input − cached; reasoning is included in output.
These are observed usage totals, without billing or hidden-retry completeness claims.

## Solo

Window: `2026-10-20T04:45:22+00:00`–`2026-10-20T04:50:24.211941+00:00`.
Wall time: **302.211941 s** (5m 2.212s).
Root: `01a1579f-0ab5-7df2-abf3-d749aa96f2ab`.

| Role | Input | Cached | Fresh | Output | Reasoning | Model calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| manager | 1,686,907 | 1,634,432 | 52,475 | 9,632 | 1,201 | 26 | 27 |
| dev_reviewer | 394,627 | 348,416 | 46,211 | 2,467 | 475 | 10 | 9 |
| **Total** | **2,081,534** | **1,982,848** | **98,686** | **12,099** | **1,676** | **36** | **36** |

## Delegated

Window: `2026-10-20T04:51:15+00:00`–`2026-10-20T04:56:18.416867+00:00`.
Wall time: **303.416867 s** (5m 3.417s).
Root: `01a157a5-d274-73d1-86b0-7cbeb3c929ea`.

| Role | Input | Cached | Fresh | Output | Reasoning | Model calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| manager | 1,673,209 | 1,623,552 | 49,657 | 7,514 | 483 | 27 | 28 |
| dev_planner | 391,868 | 340,992 | 50,876 | 3,240 | 506 | 9 | 8 |
| dev_reviewer | 239,917 | 199,936 | 39,981 | 1,492 | 172 | 7 | 6 |
| **Total** | **2,304,994** | **2,164,480** | **140,514** | **12,246** | **1,161** | **43** | **42** |

Delegated minus solo: +223,460 input (+10.74%), +41,828 fresh (+42.38%),
+147 output, −515 reasoning, +7 model calls, +6 tool calls, +1.204926s wall.

## Branch scope and validation

Exact `git diff --stat main..exp/record-results-solo`:
```text
 src/course_tutor/assessment/assembly.py |  30 +++--
 tests/test_exam_assembly.py             | 231 ++++++++++++++++++++++++++++++++
 2 files changed, 252 insertions(+), 9 deletions(-)
```
Exact `git diff --stat main..exp/record-results-delegated`:
```text
 src/course_tutor/assessment/assembly.py |  27 ++++-
 tests/test_exam_assembly.py             | 174 ++++++++++++++++++++++++++++++++
 2 files changed, 196 insertions(+), 5 deletions(-)
```

| Check | Solo | Delegated |
|---|---|---|
| Added test functions / parametrized cases | 8 / 20 | 4 / 15 |
| Final branch full suite, rerun for this comparison | PASS 657 | PASS 652 |
| Additional same-submission eligibility probe | PASS 3 | FAIL 3 |
| Original reviewer findings | 1 × P2; initial FAIL | 0; PASS |
| Finding resolution | Corrected; focused PASS 160; no re-review | None reported by original reviewer |

Test additions are relative to main (637 cases); both branches only add test cases.
Suites used the environment Python with `PYTHONPATH=src`, through `scripts/run_tests.py`
in detached worktrees at the stated branch tips. Probe used `PYTHONPATH=src:tests`.
Original evidence: `work/20261020-record-results-{solo,delegated}/{review.md,changes.md,review-packet.md}`.
Original suites: solo PASS 653 before its correction; delegated PASS 652.
The comparison's full-suite rerun verifies solo's final corrective commit.

## Acceptance against docs/evaluation/record-results-brief.md

“Yes” means verified against final code and automated checks; suite PASS alone is insufficient.

| Criterion | Solo | Delegated | Evidence / qualification |
|---|---|---|---|
| 1. Public results adapt weights; retries/variants count once; distinct family adds a unit | Yes | Yes | New public-flow family tests; unchanged formula. |
| 2. Later eligible outcome replaces unit; correction/retraction recomputes | Yes | Yes | Chronology/correction/retraction regressions. |
| 3. Ineligible/foreign evidence excluded; unknown neutral | Yes | No | Delegated ineligible same-submission competitor hides valid evidence. |
| 4. Exact representative IDs, deterministic ties/seed, hard counts/family exclusion | Yes | No | Delegated loses representative IDs and same-submission topic dimension. |
| 5. Read-only preparation; immutable saved weights/re-export; scoring/idempotency | Yes | Yes | Snapshot/read-only regressions and full suites. |

Comparison finding: **1 × P2** in delegated, separate from its original review's zero findings.
`assembly.py:48–59` ranks with `ROW_NUMBER` before eligibility checks at `:65`;
the partition omits topic. A higher-ID unassessed/stale competitor on the same
submission hides eligible evidence; another-topic competitor hides its topic's unit.
Probe: `work/20261020-record-results-comparison/test_eligibility_probe.py` (3 cases),
using the historical active-evaluation scenario already supported by both branches' tie tests.
Solo retains all candidates until eligibility and includes topic in representative identity.
Neither branch was merged or modified. No measurement tooling was built or edited.
