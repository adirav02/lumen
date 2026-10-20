TL;DR: Compare fixed development jobs with the same host/model and a quality gate.
Status: manual protocol; date: 2026-10-19.

# Development workflow benchmark

Choose a few fixed development tasks on the same base commit. Run the original
and scaffold workflows with the same host, exact model, settings and task inputs.
Record context/cache conditions, retries, dev_reviewer effort and any missing counters.
Keep runs separate; session totals only represent tasks when sessions are dedicated.
Do not compare token accounting across hosts/models as if the units were identical.
Record the baseline before role execution. All profile turn caps, including dev_explorer's
15, are soft instructions; record actual counts and any overshoot.

| Task/base commit | Workflow | Host/model/settings | Input/cache/output tokens | Turns | Tool calls | Quality PASS/FAIL | Evidence path |
|---|---|---|---|---|---|---|---|
| example/COMMIT | before | HOST/MODEL | unknown | unknown | unknown | pending | work/ID/review.md |
| example/COMMIT | after | same | unknown | unknown | unknown | pending | work/ID/review.md |

Quality requires the same acceptance criteria and targeted tests, correct scope,
and a dev_reviewer PASS. Keep failed jobs in results. Compare usage only among runs
meeting the quality gate; report unknown billing as unknown. No automation yet.
