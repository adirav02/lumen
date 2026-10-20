TL;DR: Observed usage and outcomes for measured development tasks.
Status: active; date: 2026-10-20.

# Measured task usage

| Task id | Mode | Input | Fresh input | Output | Model calls | Wall seconds | Outcome |
|---|---|---:|---:|---:|---:|---:|---|
| 20261020-record-results-solo | solo | 2,081,534 | 98,686 | 12,099 | 36 | 302.211941 | PASS; 5/5 criteria; corrected after one FAIL review |
| 20261020-record-results-delegated | delegated | 2,304,994 | 140,514 | 12,246 | 43 | 303.416867 | 3/5 criteria; original reviewer PASS, comparison found P2 |
| 20261019-assemble-exam | delegated | 3,284,856 | 241,784 | 22,042 | 62 | ~503 | PASS after one FAIL review |

Record-results source: [paired comparison](record-results-comparison.md).
Assemble-exam source: collector-run totals supplied by the user (2026-10-20);
task identity/mode: `work/20261019-assemble-exam/status.json`.
Input includes cached tokens; fresh input excludes cached tokens.
Observed usage does not establish billing or hidden-retry completeness.
The paired comparison is one pair; wall times were about equal.
Append one row after each measured task, preserving unknowns and approximations.
