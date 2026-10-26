# Documentation map

Start with the root [README](../README.md) for installation and usage,
[goal](../development/goal.md) for requirements, and [plan](../development/README.md) for implementation.

| Area | Documents |
|---|---|
| Agent behavior | [Canonical instructions](agents.md), [agent profiles and skill layout](agent-profiles.md) |
| Tutor operation | [CLI workflow](lumen-workflow.md), [tutoring](workflows/tutoring.md), [answer review](workflows/answer-review.md), [practice building](workflows/practice-building.md) |
| Course imports and history | [Course layout](course-layout.md), [question tracking](question-tracking.md), [example map](../examples/README.md) |
| Release and current evidence | [Current readiness tracker](../development/docs/release-readiness.md), [usage/cost adapters and log](usage-measurement.md), [native adapter evidence](../development/docs/reports/evaluation/host-usage-2026-10-19.json), [educational evaluation](../examples/educational_evaluation/README.md), [October audit](../development/docs/reports/audit-2026-10-18.md), [CI review](../development/docs/reports/ci-review.md), [historical verification checklist](../development/docs/reports/verification-checklist.md) |
| Technical guarantees | [Core contract: schemas, migrations and API details](../development/docs/core-contract.md) |
| Real integration evidence | [Antigravity](../development/docs/reports/antigravity-integration-report.md), [real-course Codex workflow](../development/docs/reports/real-course-integration-report.md), [extraction simulation](../development/docs/reports/course-extraction-simulation-report.md) |
| Continuation and history | [Claude/friend handoff and cross-host protocol](../development/docs/reports/claude-handoff.md), [Antigravity handoff](../development/docs/reports/antigravity-handoff.md), [historical Codex handoff](../development/docs/reports/codex-handoff.md), [implementation history](../development/docs/implementation-status.md), [historical skill patch](../development/docs/reports/lumen-skill-audit.patch) |

Historical reports retain the evidence and limitations of their own runs. They
are not additional active instructions or substitutes for current release gates.
Generated databases, backups and local run logs belong in ignored workspace/scratch
storage. Do not delete learner state as a repository housekeeping step.
