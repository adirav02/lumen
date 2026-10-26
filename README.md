# Lumen — Portable Course Tutor & Learning Assistant

Lumen is an evidence-based, portable course tutor and learning assistant for **OpenAI Codex**, **Anthropic Claude Code**, and **Google Antigravity**. It preserves original course materials, retrieves required knowledge with exact mathematical provenance, guides learners through targeted practice, and maintains a deterministic, audit-preserved record of demonstrated mastery.

Release validation remains open. See the [completed/remaining evidence tracker](development/docs/release-readiness.md)
and [Claude Code test handoff](development/docs/reports/claude-handoff.md) for a friend with access.
Tagged CI builds prepare draft releases while these gates remain open.

---

## Key Features

- **One Shared Core**: Standard Python and SQLite architecture. All hosts share the identical core, database schema, immutable storage, and assessment policy without diverging provider-specific state.
- **Zero Paid LLM Dependencies for Storage & Retrieval**: Ingestion, FTS5 lexical indexing, dependency expansion, state projections, and backups operate completely locally without external API keys or background services.
- **Byte-for-Byte Preservation**: Original PDFs, slide decks, and notes are stored immutably with SHA-256 content hashes and locators (page, slide, region).
- **Mathematical Assumption Preservation**: Definitions and theorems preserve required assumptions (e.g., $P(B) > 0$, independence), symbol definitions, exceptions, and prerequisite dependencies.
- **Trustworthy Evidence & Assistance Tracking**:
  - Independent work vs. assisted work: answers submitted after hints or exposed solutions are classified as *assisted performance*, never independent mastery.
  - Partial progress: method correctness is preserved even when arithmetic is erroneous.
  - Pausing/fatigue: untouched subparts remain unassessed; pausing is never counted as failure.
  - Audit trail & corrections: mistakes made by the tutor or rubric are retracted or superseded, and topic states are recomputed deterministically without erasing history.
- **Resumable Diagnostics**: Topic blueprint evaluations report observed rubric score, coverage percentage, and assistance level without fabricating pass probabilities.
- **Consistent Backup & Restore**: Online SQLite snapshots combined with verified source assets and manifest integrity checks.

---

## System Requirements & Python Support

- **Python**: `>= 3.10` (Tested and verified locally on **Python 3.14.8**; GitHub Actions CI matrix configured for **Python 3.10, 3.11, 3.12, 3.13, 3.14, 3.15**).
- **SQLite**: `>= 3.35` with FTS5 enabled.
- **Dependencies**: `pypdf`, `python-pptx`, `pytest` (development).

---

Developer setup, tasks and verification: [development/README.md](development/README.md).

## Installation & Setup

1. **Clone and enter the repository**:
   ```bash
   git clone <repository_url>
   cd lumen
   ```

2. **Bootstrap from the local pip cache, offline by default**:
   ```bash
   python3 development/scripts/bootstrap.py
   ```
   This creates `.venv`, installs development dependencies and Lumen, and runs
   dependency diagnostics. Use `--online` to allow downloads when the cache is
   incomplete. See [offline setup](development/docs/dependency-bootstrap.md) for wheelhouse
   provisioning and cache selection.

3. **Verify environment capabilities**:
   ```bash
   .venv/bin/lumen capabilities
   ```

Development uses one agent for the whole task. Delegation requires an explicit
user request. Start usage collection before setup, without a venv, with
`python3 development/scripts/watch_usage.py --label my-task`; stop it with Ctrl-C at task end.
Verification clones belong under `.tmp/` and must be deleted at the end.

---

## Quickstart Demo

Run the standalone synthetic probability course demonstration:
```bash
.venv/bin/python demo.py
```
This self-contained demo creates synthetic text in a temporary directory, exercises
the current core API, and removes its original and restored workspaces on exit.
Its inputs are separate from maintained automated fixtures in `tests/fixtures/`.
It runs an automated end-to-end showcase:
- Capability checks
- Course creation and topic alias configuration (English & Hebrew)
- Synthetic text ingestion and semantic unit extraction
- Multilingual search and dependency expansion
- Interactive attempt with graduated hints and assisted performance recording
- Mistake correction and deterministic state recomputation
- Blueprint-driven diagnostic evaluation
- Full snapshot backup to ZIP and restore verification into a clean workspace.

---

## Tutoring and practice

Test and exam requests deliver a **PDF file by default**. Saving an assessment or
posting questions in chat is incomplete. After selection, the agent uses
`assessment-paper` and `export-assessment`, visually checks the rendered PDF, and
returns its file link. Explicit chat-only/other-format requests override this.
The exporter needs an installed Chrome, Chromium or Edge browser; `lumen
capabilities` reports its availability. Math is rendered offline with MathML.

Lumen's course skill has three shared modes: [tutoring](docs/workflows/tutoring.md),
[answer review](docs/workflows/answer-review.md), and [practice building](docs/workflows/practice-building.md).
The general workflows provide focused hints, checking the actual
displayed answer version, preserving valid intermediate work, and avoiding repeated
solution families. The same workflows and SQLite history are used across hosts.

Discover the registered course, then propose three checked source-bound questions
without recording them as presented or solved:

```bash
lumen list-courses -w '<workspace>'
lumen propose-practice -w '<workspace>' -c '<course_id>' -j '{"learner_id":"learner_1","count":3,"source_only":true}'
```

The proposal reports missing candidates instead of silently filling the set with
repeats. See [the CLI workflow](docs/lumen-workflow.md) for selection and persistence.

For exam imports, use the [course extraction skill](.agents/skills/extract-course-questions/SKILL.md)
and [course folder layout](docs/course-layout.md). The
[beta course collection](examples/beta_courses/README.md) is reserved for upcoming
public fixtures. Real course materials are not distributed with this repository;
keep them in the gitignored `local-courses/` folder. Historical private-run reports
are implementation evidence only and do not include their source data.

## Testing

Configure Claude Code and Antigravity CLI callbacks with `lumen configure-usage -w .lumen`.
Use `lumen watch-usage -w .lumen` for Codex/Claude transcript polling and a combined
view of callback updates; inspect saved data with `lumen usage-summary -w .lumen`.
The [usage/cost guide](docs/usage-measurement.md) explains measured scopes, native
headless capture, project filtering, estimates and unavailable billing. Antigravity
CLI capture has live evidence; Claude runtime verification is still open.
The [broader educational evaluation](examples/educational_evaluation/README.md)
provides 16 local reviewed cases and a protocol for future unseen host testing.

Run the full automated suite, including provenance, extraction review, assembly and PDF privacy,
attempt/evidence lifecycle, migrations, recovery, CLI and configuration regressions:
```bash
.venv/bin/python development/scripts/run_tests.py
```

---

The independent audit fixture and full workflow can be run with:
```bash
.venv/bin/python development/scripts/run_tests.py tests/test_audit_course_e2e.py
```
See [the audit report](development/docs/reports/audit-2026-10-18.md) and [the corrected tutoring workflow](docs/lumen-workflow.md).

## Host Integration

Lumen supplies shared loaders and CLI integration for the three required AI agent platforms. Automated tests inspect files and simulate host markers. Separate live evidence verifies [Antigravity integration and fresh-session resume](development/docs/reports/antigravity-integration-report.md) and [Codex visual review of real course materials](development/docs/reports/real-course-integration-report.md). Live Claude Code integration and cross-host handover remain open; see [release status](development/docs/release-readiness.md).

### 1. OpenAI Codex
- **Native Instruction Loader**: Root `AGENTS.md` directs Codex to read `docs/agents.md`.
- **Lumen Skill**: Located at `.agents/skills/lumen/SKILL.md` with valid YAML frontmatter.
- **Project Configuration**: `.codex/config.toml` and `.codex/README.md`.

### 2. Anthropic Claude Code
- **Native Instruction Loader**: Root `CLAUDE.md` imports `@docs/agents.md`.
- **Skills**: `.claude/skills/` exposes both shared skills through small pointers to `.agents/skills/`.
- **Agent profiles**: `.claude/agents/` contains native lookup, practice, and reasoning profiles. See [agent and skill layout](docs/agent-profiles.md).

### 3. Google Antigravity
- **Native Instruction Loader**: Root `AGENTS.md` directs Antigravity to `docs/agents.md`.
- **Skill Discovery**: Native automatic discovery of `.agents/skills/lumen/SKILL.md`.

---

## Command-Line Interface (`lumen`)

The CLI emits compact, structured JSON to stdout and diagnostic logs to stderr.

```bash
# Check capabilities
lumen capabilities

# Create course
lumen create-course -j '{"name": "Probability 101", "scope": "Undergraduate"}'

# Ingest source
lumen ingest-source -c "<course_id>" -j '{"file_path": "path/to/notes.txt", "role": "lecture"}'

# Course brief
lumen course-brief -c "<course_id>"

# Search knowledge units
lumen search -c "<course_id>" -q "Bayes"

# Read units with dependencies
lumen read-units -c "<course_id>" -j '{"unit_ids": ["<unit_id>"], "expand_dependencies": true}'

# Learner attempts
lumen start-attempt -c "<course_id>" -j '{"exercise_version_id": "<ex_ver_id>"}'
lumen record-attempt-event -j '{"attempt_id": "<att_id>", "expected_revision": 1, "event_type": "work_submission", "content": "P=0.5"}'
lumen commit-evidence -j '{"attempt_id": "<att_id>", "evaluations": [{"topic_id": "<topic_id>", "skill_id": "calc", "correct": true}]}'

# Backup and Restore
lumen backup -j '{"output_path": "backups/lumen_backup.zip"}'
lumen restore -j '{"backup_path": "backups/lumen_backup.zip", "target_workspace": "restored_ws"}'
```

## Exam question tracking

Upload with `role:"exam"` to create a reviewable question catalog with exact source
versions and page/section spans. Lumen distinguishes shown, answered, graded and
correctly answered work per learner/course, retains all attempts and grading
corrections, and supports ordinary-practice scores/feedback. Indexed duplicate and
similarity candidates prevent accidental repeats; `propose-practice` with
`focus:"mistakes",allow_repeats:true` revisits recorded difficulties intentionally.

See [question tracking and CLI examples](docs/question-tracking.md). Scanned or
uncertain extraction remains pending until reviewed; automatic splitting cannot
establish that every question was captured.

## CI and releases

GitHub Actions runs Python 3.10–3.15 tests, capabilities, the synthetic demo, and
a distribution build. Package checks install the wheel built through the source
distribution into a fresh virtual environment outside the checkout and verify both
CLI entrypoints, source ingestion, retrieval/provenance and backup/restore.
Tagged releases reuse these checks and attach those exact validated distributions
to a draft release. The tag must equal `v<version>` from package metadata
(for example, `v0.1.0`); manual release retries must select a tag.
See [local distribution verification](development/docs/conventions.md#distribution-verification)
and [CI review and remaining checks](development/docs/reports/ci-review.md).

For public distribution builds, run `python development/scripts/build_public.py`, followed by
`python development/scripts/check_release_version.py`. The build wrapper removes local owner
identities and timestamps from source archive metadata before publication.


For seeded exam assembly from a saved blueprint, run:

```bash
lumen assemble-exam -w '<workspace>' -c '<course_id>' -r 'exam-20261019-01' -j '{"blueprint_file":"blueprint.json","learner_id":"learner_1","title":"Practice test","seed":42}'
```

See the [saved blueprint workflow](docs/lumen-workflow.md#assemble-from-a-saved-blueprint)
for concrete JSON, strict constraints, stable retries, Linux atomic publication,
and snapshot re-export. Success returns the assessment ID, PDF path and pending
visual review summary. Inspect rendered pages before delivering the PDF link.
