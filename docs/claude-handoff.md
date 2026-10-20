# Claude Code test handoff

Status: prepared on 2026-10-19; **not run in Claude Code**. A friend with Claude
Code can use this protocol and return the filled [report](templates/host-smoke-report.md).
No private course data or API keys are needed. Use Linux/macOS/WSL with Python
3.10+ and working `flock`; check capabilities rather than assuming OS support.

## Setup

Clone/download the complete repository including `.claude/`, `.agents/`, and
`CLAUDE.md`. Open its root. Install Claude Code using its current official setup
instructions if needed, sign in normally, then run:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/lumen capabilities
.venv/bin/pytest -q
.venv/bin/lumen configure-usage -w .lumen -j '{"hosts":["claude"]}'
git rev-parse HEAD
claude --version
claude
```

Save version/capability/test output and the exact Git revision under
`scratch/claude-smoke/<run-id>/`. Use a new workspace there; do not reuse a real
learner database. Keep original failed runs when retrying. Running pytest does
not establish that Claude itself can invoke the CLI or see an image.

## Native discovery first

Before telling Claude to open the canonical instruction file, inspect `/context`
and `/memory` and save which project files were loaded. Expect the root
`CLAUDE.md` and its `@docs/agents.md` import, subject to installed-version settings.
If you manually load them to proceed, record discovery as failed/blocked rather
than silently converting that into a pass.

Invoke `/lumen` and `/extract-course-questions` on a bounded request to explain
their workflow routing without importing data. Verify they resolve the thin
`.claude/skills/` pointers to `.agents/skills/`. Inspect the available agents and
explicitly ask for one read-only `course-lookup` task: locate the generated
audit Bayes question's exact file/ID without solving it or writing learner state.
Save the actual child invocation, selected model, tools and result. Check that
`course-practice` and `course-reasoning` are also exposed; do not run
expensive reasoning merely to test their names. Reading the profile files alone
is static evidence, not native discovery.

The current docs describe `/agents` differently across versions: older versions
show an inspector, newer versions may show a reminder. Record the observed UI
and actual invocation. Commands are version-sensitive; unsupported commands
remain limitations. References checked 2026-10-19:
[memory/imports](https://code.claude.com/docs/en/memory),
[skills](https://code.claude.com/docs/en/skills), and
[subagents](https://code.claude.com/docs/en/sub-agents).

## First-session prompt

Paste this after discovery; replace `<run-id>` with your chosen identifier:

> Use the Lumen skill and public CLI in this repository. This is a live host smoke
> test using generated data, not real learner evidence. Use workspace
> `scratch/claude-smoke/<run-id>/workspace`, course `host-smoke`, learner `tester`.
> Save executed commands, JSON receipts and a checkpoint manifest in the run
> directory. Do not modify the implementation or manually edit SQL.
>
> Create the course, a Bayes topic, and a preference for hints only when requested.
> Ingest `examples/synthetic_probability/materials/lecture_bayes.txt`. Retrieve
> a complete unit, inspect its cited source region, and state its exact version,
> locator, assumptions and hash verification. Pending extraction is not a checked
> reference. Also ingest `examples/educational_evaluation/graph.png` as a source,
> resolve its immutable original with read-source-region, and OPEN THAT IMAGE
> using your image-capable host tool. Describe the arrows and edge labels you
> actually see. Do not substitute text from checked-references.json for seeing it.
>
> Create a GENERATED two-part Bayes question: P(D)=0.02, P(+|D)=0.9,
> P(+|not D)=0.1. (a) Find P(+). (b) Find P(D|+). Check the derivation and
> rubric, then validate the exact exercise revision. Start one practice attempt.
> Treat this as the simulated learner's actual (a) submission:
> '0.9*0.02+0.1*0.98=0.116'. Record and evaluate only (a). Replay the identical
> evidence commit with its original request ID; show the same receipt and no
> duplicate evidence. Then try a changed evaluation with that ID and retain the
> expected conflict. Record a denominator hint for (b), but no (b) submission yet.
> Pause. Show that (a) is independent, (b) is unassessed, and the hint is retained.
> Save the workspace/course/learner, version/topic/attempt IDs, current revision,
> submission/evidence/request IDs, original image path and citation in the
> checkpoint manifest. Record any available usage using docs/usage-measurement.md;
> native callback/transcript capture is configured during setup. Inspect
> `.lumen/usage.jsonl` to verify actual invocation, preserve scoped counters and
> estimates, and return any failures. Unavailable per-call data or billed cost
> stays unavailable. Stop at this pause.

Pass requires actual host tool calls and successful receipts, not a plausible
narrative. Inspect `attempt-history` and `course-brief` outputs. The first prompt
has not authorized inventing additional work or assistance.

## Fresh-session prompt

Exit Claude entirely. Start a **new conversation**, without `--resume` or copied
chat history, in the same project root. Supply only this prompt and the run path:

> Resume the Lumen attempt in `scratch/claude-smoke/<run-id>/workspace` for course
> `host-smoke`, learner `tester`. Read the durable checkpoint and public core
> history, not provider memory. Report the saved work, hint, pending part, IDs
> and revision before writing. Resume the same attempt using that revision.
> Now the simulated learner submits (b): '0.018/0.116=9/58'. Record and evaluate
> it; verify assisted success because the hint preceded it. Verify the earlier
> independent (a) evidence is preserved. Open the saved original graph image
> again. Pause and save the updated checkpoint. Keep transcripts and receipts.

If a tutor mistake occurs, retain it, use `correct-evidence`, and verify dependent
grades return to pending review. To exercise correction deliberately after saving
the real result, create a separate generated test attempt, record an intentionally
wrong judgment with a clear test rationale, correct it, and retain both versions.
Create a core backup outside the workspace, restore into a new empty directory,
and verify history, preferences, citations and original hashes from the restored
workspace. Copy measurement logs separately, as described in the measurement guide.

## Cross-host handover

Run the first-session prompt in **one actual host** (Codex or Antigravity), then
the fresh-session prompt in **actual Claude Code**, or reverse those roles. Start
another run ID; do not relabel an earlier Claude-only run. Keep host/version and
session evidence at both ends. On one machine, close the writer before handing
over the same workspace. On different machines, use core backup/restore into an
empty destination, transfer the checkpoint and measurement ledger separately,
and retain the exact code revision and source hashes. Do not sync a live SQLite DB.

Verify the same attempt and exercise identity, (a) submission/evidence, prior
(b) hint, preferences, revisions and citations before accepting new work. Confirm
the new (b) submission becomes assisted and earlier (a) stays independent. Return
to the first real host and inspect the updated history without duplicating it.
Setting `CLAUDE_CODE` or another environment marker does not run that host.

## What to send back

Return the filled report, discovery evidence, command/receipt transcript,
checkpoint, anonymized usage log/summary and any failures/retries. A generated
workspace backup can be returned for reproduction. Do not send credentials or
private host settings. Mark each check passed/failed/blocked/not run with an
artifact path; a checklist without artifacts cannot close the release gate.
