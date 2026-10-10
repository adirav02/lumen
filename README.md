# Lumen — Portable Course Tutor & Learning Assistant

Lumen is an evidence-based, portable course tutor and learning assistant for **OpenAI Codex**, **Anthropic Claude Code**, and **Google Antigravity**. It preserves original course materials, retrieves required knowledge with exact mathematical provenance, guides learners through targeted practice, and maintains a deterministic, audit-preserved record of demonstrated mastery.

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

- **Python**: `>= 3.10` (Tested and verified locally on **Python 3.14.8**; GitHub Actions CI matrix configured for **Python 3.10, 3.11, 3.12, 3.13, 3.14**).
- **SQLite**: `>= 3.35` with FTS5 enabled.
- **Dependencies**: `pypdf`, `python-pptx`, `pytest` (development).

---

## Installation & Setup

1. **Clone and enter the repository**:
   ```bash
   git clone <repository_url>
   cd lumen
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Lumen in editable mode**:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Verify installation and environment capabilities**:
   ```bash
   lumen capabilities
   ```

---

## Quickstart Demo

Run the standalone synthetic probability course demonstration:
```bash
python demo.py
```
This runs an automated end-to-end showcase:
- Capability checks
- Course creation and topic alias configuration (English & Hebrew)
- Course material ingestion and semantic unit extraction
- Multilingual search and dependency expansion
- Interactive attempt with graduated hints and assisted performance recording
- Mistake correction and deterministic state recomputation
- Blueprint-driven diagnostic evaluation
- Full snapshot backup to ZIP and restore verification into a clean workspace.

---

## Testing

Run the full automated test suite covering all failure scenarios (F01–F36) from `plan.md` and boundary concurrency tests (67 tests passing):
```bash
pytest -v
```

---

## Host Integration

Lumen integrates seamlessly into the three required AI agent platforms:

### 1. OpenAI Codex
- **Native Instruction Loader**: Root `AGENTS.md` directs Codex to read `docs/agents.md`.
- **Lumen Skill**: Located at `.agents/skills/lumen/SKILL.md` with valid YAML frontmatter.
- **Project Configuration**: `.codex/config.toml` and `.codex/README.md`.

### 2. Anthropic Claude Code
- **Native Instruction Loader**: Root `CLAUDE.md` imports `@docs/agents.md`.
- **Skill Pointer**: `.claude/skills/lumen/SKILL.md` routes commands to the canonical skill and CLI.

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
