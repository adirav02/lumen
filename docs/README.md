# Documentation map

Start with the root [README](../README.md) for installation and usage,
[goal](../goal.md) for requirements, and [plan](../plan.md) for implementation.

| Area | Documents |
|---|---|
| Agent behavior | [Canonical instructions](agents.md), [agent profiles and skill layout](agent-profiles.md) |
| Tutor operation | [CLI workflow](lumen-workflow.md), [tutoring](workflows/tutoring.md), [answer review](workflows/answer-review.md), [practice building](workflows/practice-building.md) |
| Course imports and history | [Course layout](course-layout.md), [question tracking](question-tracking.md), [example map](../examples/README.md) |
| Release and current evidence | [Current readiness tracker](release-readiness.md), [usage/cost adapters and log](usage-measurement.md), [native adapter evidence](evaluation/host-usage-2026-10-19.json), [educational evaluation](../examples/educational_evaluation/README.md), [October audit](audit-2026-10-18.md), [CI review](ci-review.md), [historical verification checklist](verification-checklist.md) |
| Technical guarantees | [Core contract: schemas, migrations and API details](core-contract.md) |
| Real integration evidence | [Antigravity](antigravity-integration-report.md), [real-course Codex workflow](real-course-integration-report.md), [extraction simulation](course-extraction-simulation-report.md) |
| Continuation and history | [Claude/friend handoff and cross-host protocol](claude-handoff.md), [Antigravity handoff](antigravity-handoff.md), [historical Codex handoff](codex-handoff.md), [implementation history](implementation-status.md), [historical skill patch](lumen-skill-audit.patch) |

Historical reports retain the evidence and limitations of their own runs. They
are not additional active instructions or substitutes for current release gates.
Generated databases, backups and local run logs belong in ignored workspace/scratch
storage. Do not delete learner state as a repository housekeeping step.
