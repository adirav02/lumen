"""Simulated host-marker conformance and static loader checks.

These tests do not launch Codex, Claude Code, or Antigravity. Native discovery,
host permissions, and source-image display require separate real-host evidence.

Verifies:
1. Native instruction discovery and loader configuration for Google Antigravity,
   OpenAI Codex, and Anthropic Claude Code.
2. Runtime capability inspection and host environment detection across all three hosts.
3. Sequential cross-host workspace handover and resume smoke test:
   - Host A (Antigravity): Workspace init, course creation, source ingestion with
     provenance and assumptions, diagnostic creation, item attempt start, initial submission, pause.
   - Host B (Codex): Workspace open, course brief resume detection, attempt resumption,
     hint request/response, submission, evidence commit with strict assistance ordering,
     idempotent retry verification, and assessment item scoring.
   - Host C (Claude Code): Workspace open, course brief verification, source region visual
     inspection, mistake correction with audit preservation, snapshot backup, and
     byte-for-byte restore verification into a clean workspace.
4. CLI multi-host invocation conformance across environments.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.capabilities import check_capabilities


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ==============================================================================
# 1. Host Instruction Discovery & Loader Integrity
# ==============================================================================

def test_host_discovery_and_loader_integrity():
    """Verify that all three required host environments discover shared instructions."""
    project_root = Path(__file__).resolve().parent.parent

    # 1. Canonical Shared Instructions
    canonical_agents = project_root / "docs" / "agents.md"
    assert canonical_agents.is_file(), "docs/agents.md must exist as canonical instructions"
    agents_text = canonical_agents.read_text(encoding="utf-8")
    assert "Shared Agent Instructions" in agents_text
    assert "## Tutoring mode" in agents_text
    assert "## Implementation mode" in agents_text

    # 2. Google Antigravity Discovery
    root_agents = project_root / "AGENTS.md"
    assert root_agents.is_file(), "Root AGENTS.md must exist for Antigravity"
    root_agents_text = root_agents.read_text(encoding="utf-8")
    assert "docs/agents.md" in root_agents_text, "Root AGENTS.md must point to docs/agents.md"

    antigravity_skill = project_root / ".agents" / "skills" / "lumen" / "SKILL.md"
    assert antigravity_skill.is_file(), "Antigravity skill must exist at .agents/skills/lumen/SKILL.md"
    skill_text = antigravity_skill.read_text(encoding="utf-8")
    assert "name: lumen" in skill_text
    assert "expected_revision" in skill_text

    # 3. OpenAI Codex Discovery
    codex_config = project_root / ".codex" / "config.toml"
    assert codex_config.is_file(), ".codex/config.toml must exist for Codex"
    codex_readme = project_root / ".codex" / "README.md"
    assert codex_readme.is_file(), ".codex/README.md must exist for Codex"
    assert "AGENTS.md" in codex_readme.read_text(encoding="utf-8")

    # 4. Anthropic Claude Code Discovery
    claude_md = project_root / "CLAUDE.md"
    assert claude_md.is_file(), "Root CLAUDE.md must exist for Claude Code"
    claude_text = claude_md.read_text(encoding="utf-8")
    assert "@AGENTS.md" in claude_text, "CLAUDE.md must import the shared root loader"

    claude_skill = project_root / ".claude" / "skills" / "lumen" / "SKILL.md"
    assert claude_skill.is_file(), "Claude Code skill pointer must exist at .claude/skills/lumen/SKILL.md"
    assert "docs/agents.md" in claude_skill.read_text(encoding="utf-8")
    import re
    for target in re.findall(r"\]\(([^)]+)\)", claude_skill.read_text(encoding="utf-8")):
        assert (claude_skill.parent / target).resolve().is_file(), target


# ==============================================================================
# 2. Host Capability Detection Across Environments
# ==============================================================================

def test_host_environment_detection_capabilities(monkeypatch):
    """Verify capabilities reporter correctly detects host from environment markers."""
    # Antigravity marker
    monkeypatch.setenv("ANTIGRAVITY", "1")
    monkeypatch.delenv("CLAUDE_CODE", raising=False)
    monkeypatch.delenv("CODEX", raising=False)
    monkeypatch.delenv("OPENAI", raising=False)
    monkeypatch.delenv("ANTHROPIC", raising=False)
    caps_ag = check_capabilities()
    assert caps_ag["detected_host"] == "antigravity"
    assert caps_ag["contract_version"] == "1.0.0"
    assert caps_ag["runtime"]["fts5_supported"] is True
    assert caps_ag["runtime"]["locking_supported"] is True
    assert caps_ag["extraction_capabilities"]["visual_source_inspection"] == "host_dependent"

    # Codex marker
    monkeypatch.delenv("ANTIGRAVITY", raising=False)
    monkeypatch.delenv("GEMINI", raising=False)
    monkeypatch.setenv("CODEX", "1")
    caps_codex = check_capabilities()
    assert caps_codex["detected_host"] == "codex"

    # Claude Code marker
    monkeypatch.delenv("CODEX", raising=False)
    monkeypatch.setenv("CLAUDE_CODE", "1")
    caps_claude = check_capabilities()
    assert caps_claude["detected_host"] == "claude_code"

    # Generic CLI
    monkeypatch.delenv("CLAUDE_CODE", raising=False)
    caps_generic = check_capabilities()
    assert caps_generic["detected_host"] == "generic_cli"


# ==============================================================================
# 3. Sequential Cross-Host Handover & Resume Smoke Test
# ==============================================================================

def test_three_host_cross_resume_conformance_smoke_test(temp_workspace, monkeypatch):
    """Full cross-host conformance smoke test across Antigravity, Codex, and Claude Code.

    - Host A (Antigravity): Starts workspace, creates course, ingests material with assumptions,
      creates diagnostic, starts item attempt, records submission, pauses attempt.
    - Host B (Codex): Opens same workspace, checks course brief, resumes attempt, gives hint,
      records submission, commits assisted evidence, verifies write idempotency, scores item.
    - Host C (Claude Code): Opens same workspace, checks brief/progress, inspects source region,
      corrects tutor mistake on practice attempt, verifies topic rebuild, creates snapshot
      backup, and verifies byte-for-byte restore into a clean workspace.
    """
    course_id = "prob-three-host"
    learner_id = "student_smoke"

    # --------------------------------------------------------------------------
    # Phase 1: Host A (Google Antigravity)
    # --------------------------------------------------------------------------
    monkeypatch.setenv("ANTIGRAVITY", "1")
    monkeypatch.delenv("CODEX", raising=False)
    monkeypatch.delenv("CLAUDE_CODE", raising=False)

    core_a = LumenCore(temp_workspace)
    try:
        # Check capabilities under Antigravity
        caps_a = core_a.capabilities()
        assert caps_a["detected_host"] == "antigravity"

        # 1. Create Course
        c_res = core_a.create_course(
            "Continuous & Discrete Probability",
            course_id=course_id,
            scope="Undergraduate STEM",
            default_language="en",
        )["data"]
        assert c_res["id"] == course_id

        # 2. Ingest source with assumptions and locators
        source_content = (
            "### Theorem: Bayes' Rule\n"
            "Content: P(A|B) = P(B|A) * P(A) / P(B)\n"
            "Assumptions: P(B) > 0; Events form valid probability space\n"
            "Symbols: P(A|B) = posterior; P(A) = prior; P(B|A) = likelihood; P(B) = evidence\n"
            "Exceptions: Undefined when P(B) = 0\n"
        )
        source_path = temp_workspace / "bayes_lecture.txt"
        source_path.write_text(source_content, encoding="utf-8")

        ingest_res = core_a.ingest_source(course_id, str(source_path), logical_name="bayes_lecture", role="lecture")["data"]
        source_ver_id = ingest_res["source_version_id"]
        unit_id = ingest_res["units"][0]["id"]

        # Verify unit reading preserves assumptions
        read_res = core_a.read_units(course_id, [unit_id])
        assert read_res["units"][0]["assumptions"] == ["P(B) > 0", "Events form valid probability space"]

        # 3. Create Topic and Exercise
        topic = core_a.create_topic(course_id, name="Bayes Theorem", slug="bayes-rule")
        ex = core_a.create_exercise(
            course_id,
            "bayes_calc_family",
            "Calculate posterior probability given prior=0.2, likelihood=0.8, evidence=0.4",
            reference_solution="P(A|B) = 0.4",
            rubric={"max_points": 10.0},
        )
        ex_ver_id = ex["exercise_version_id"]

        # Validate exercise with mandatory caller expected revision
        val_res = core_a.validate_exercise_version(ex_ver_id, checks=["check_passed"], expected_revision=1)
        assert val_res["validation_state"] == "validated"

        # 4. Create Diagnostic Assessment
        diag = core_a.create_assessment(
            course_id,
            "Midterm Diagnostic",
            blueprint={"topic_ids": [topic["id"]]},
            selected_exercise_version_ids=[ex_ver_id],
        )["data"]
        diag_id = diag["assessment_id"]

        # 5. Start Assessment Item Attempt
        item_att = core_a.start_assessment_item_attempt(diag_id, item_order=1, learner_id=learner_id)
        att_id = item_att["attempt"]["id"]
        assert item_att["attempt"]["mode"] == "diagnostic"
        assert item_att["attempt"]["learner_id"] == learner_id

        # 6. Record Initial Student Work Submission
        core_a.record_attempt_event(
            att_id,
            expected_revision=1,
            event_type="work_submission",
            content="P(A|B) = (0.8 * 0.2) / 0.4 = 0.4",
        )

        # 7. Pause Attempt (Learner pauses session)
        pause_res = core_a.pause_attempt(att_id, expected_revision=2)["data"]
        assert pause_res["status"] == "paused"
        assert pause_res["current_revision"] == 3
    finally:
        core_a.close()

    # --------------------------------------------------------------------------
    # Phase 2: Host B (OpenAI Codex)
    # --------------------------------------------------------------------------
    monkeypatch.delenv("ANTIGRAVITY", raising=False)
    monkeypatch.setenv("CODEX", "1")

    core_b = LumenCore(temp_workspace)
    try:
        caps_b = core_b.capabilities()
        assert caps_b["detected_host"] == "codex"

        # 1. Open Session: Query Course Brief without reading full transcript
        brief_b = core_b.course_brief(course_id, learner_id=learner_id)
        open_att = brief_b["open_attempt"]
        assert open_att is not None
        assert open_att["attempt_id"] == att_id
        assert open_att["status"] == "paused"
        assert open_att["revision"] == 3

        # 2. Resume Attempt
        resume_res = core_b.resume_attempt(att_id, expected_revision=3)["data"]
        assert resume_res["status"] == "open"
        assert resume_res["current_revision"] == 4

        # 3. Learner Requests and Receives Hint
        core_b.record_attempt_event(att_id, expected_revision=4, event_type="hint_request")
        core_b.record_attempt_event(
            att_id,
            expected_revision=5,
            event_type="hint_given",
            content="Check denominator: P(B) is 0.4, numerator is 0.16.",
        )

        # 4. Learner Submits Final Answer
        sub_event = core_b.record_attempt_event(
            att_id,
            expected_revision=6,
            event_type="work_submission",
            content="0.16 / 0.4 = 0.4",
        )["data"]
        sub_id = sub_event["event"]["id"]

        # 5. Commit Evaluated Evidence (Tied to submission event)
        commit_req_id = "req-smoke-commit-evidence-001"
        eval_payload = [{
            "subpart_key": "default",
            "topic_id": topic["id"],
            "skill_id": "bayes_posterior",
            "correct": True,
            "submission_event_id": sub_id,
        }]
        commit_res = core_b.commit_evidence(
            att_id,
            evaluations=eval_payload,
            complete_attempt=True,
            request_id=commit_req_id,
        )["data"]

        ev = commit_res["evidence_created"][0]
        # F07 invariant: Success after hint is assisted_success, NEVER independent_mastery
        assert ev["demonstrated_level"] == "assisted_success"

        # 6. Idempotency Check: Replaying exact request ID returns cached receipt
        retry_res = core_b.commit_evidence(
            att_id,
            evaluations=eval_payload,
            complete_attempt=True,
            request_id=commit_req_id,
        )
        assert retry_res.get("idempotent_replay") is True
        assert retry_res["data"]["evidence_created"][0]["id"] == ev["id"]

        # 7. Record Assessment Item Score
        score_res = core_b.record_assessment_item_score(
            diag_id,
            item_order=1,
            points_awarded=10.0,
            attempt_id=att_id,
        )
        assert score_res["points_awarded"] == 10.0
        assert score_res["score_status"] == "scored"

        # Verify diagnostic progress
        prog_b = core_b.assessment_progress(diag_id)
        assert prog_b["completed_items"] == 1
        assert prog_b["total_awarded_points"] == 10.0
        assert prog_b["assistance"]["assisted_items_count"] == 1
        assert prog_b["assistance"]["independent_items_count"] == 0
    finally:
        core_b.close()

    # --------------------------------------------------------------------------
    # Phase 3: Host C (Anthropic Claude Code)
    # --------------------------------------------------------------------------
    monkeypatch.delenv("CODEX", raising=False)
    monkeypatch.setenv("CLAUDE_CODE", "1")

    core_c = LumenCore(temp_workspace)
    try:
        caps_c = core_c.capabilities()
        assert caps_c["detected_host"] == "claude_code"

        # 1. Verify Persisted Progress in Course Brief
        brief_c = core_c.course_brief(course_id, learner_id=learner_id)
        assert brief_c["coverage"]["assessed_topics_count"] == 1
        topic_entry = brief_c["coverage"]["assessed_topics"][0]
        assert topic_entry["name"] == "Bayes Theorem"
        assert topic_entry["assisted"] == 1
        assert topic_entry["independent"] == 0

        # 2. Inspect Source Region with Physical Hash Verification
        region = core_c.read_source_region(source_ver_id, page_index=1)
        assert region["file_exists"] is True
        assert region["hash_verified"] is True
        assert region["original_filename"] == "bayes_lecture.txt"
        assert Path(region["absolute_path"]).exists()

        # 3. Practice Exercise & Tutor Mistake Correction
        ex_prac = core_c.create_exercise(course_id, "prac_fam", "Compute 2+2", validation_state="validated")
        att_prac = core_c.start_attempt(course_id, ex_prac["exercise_version_id"], learner_id=learner_id)["data"]
        core_c.record_attempt_event(att_prac["id"], expected_revision=1, event_type="work_submission", content="4")

        # Tutor incorrectly grades as wrong (Defect / F11)
        wrong_commit = core_c.commit_evidence(
            att_prac["id"],
            evaluations=[{
                "subpart_key": "default",
                "topic_id": topic["id"],
                "skill_id": "prac_skill",
                "correct": False,
            }],
        )["data"]
        wrong_ev_id = wrong_commit["evidence_created"][0]["id"]
        assert wrong_commit["evidence_created"][0]["demonstrated_level"] == "incorrect"

        # Tutor corrects the mistake via correct_evidence
        corr_res = core_c.correct_evidence(
            evidence_id=wrong_ev_id,
            correction_reason="Tutor mistake: 4 was correct.",
            replacement={
                "topic_id": topic["id"],
                "skill_id": "prac_skill",
                "demonstrated_level": "independent_mastery",
            },
        )
        assert corr_res["status"] == "success"
        assert corr_res["data"]["original_evidence_id"] == wrong_ev_id
        assert corr_res["data"]["action"] == "superseded"

        # Recomputed state must reflect 1 independent success now
        t_state = core_c.learning_service.evidence_repo.get_topic_state(course_id, topic["id"])
        assert t_state.independent_success_count == 1
        assert t_state.assisted_success_count == 1

        # 4. Snapshot Backup
        backup_zip = temp_workspace / "smoke_backup.zip"
        backup_res = core_c.backup(str(backup_zip))
        assert backup_res["source_count"] == 1
        assert backup_zip.is_file()

        # 5. Restore into Clean Workspace and Verify Byte-for-Byte Fidelity
        with tempfile.TemporaryDirectory() as restore_td:
            restore_dir = Path(restore_td) / "restored_lumen"
            restored = LumenCore.restore(str(backup_zip), str(restore_dir))
            assert restored["status"] == "success"
            assert restored["sources_verified"] == 1

            # Open restored workspace and verify data
            restored_core = LumenCore(restore_dir)
            try:
                restored_brief = restored_core.course_brief(course_id, learner_id=learner_id)
                assert restored_brief["course"]["name"] == "Continuous & Discrete Probability"
                assert restored_brief["coverage"]["assessed_topics_count"] == 1
                assert restored_brief["coverage"]["assessed_topics"][0]["assisted"] == 1
                assert restored_brief["coverage"]["assessed_topics"][0]["independent"] == 1
            finally:
                restored_core.close()
    finally:
        core_c.close()


# ==============================================================================
# 4. CLI Cross-Host Invocation Conformance
# ==============================================================================

def test_cross_host_cli_invocation_conformance(temp_workspace):
    """Verify that CLI output envelopes remain consistent across simulated host calls."""
    ws = str(temp_workspace)

    for host_env, expected_host in [
        ({"ANTIGRAVITY": "1"}, "antigravity"),
        ({"CODEX": "1"}, "codex"),
        ({"CLAUDE_CODE": "1"}, "claude_code"),
    ]:
        env = {**os.environ, **host_env}
        cmd = [sys.executable, "-m", "course_tutor.cli", "capabilities", "--workspace", ws]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["status"] == "success"
        assert data["data"]["detected_host"] == expected_host
        assert data["data"]["contract_version"] == "1.0.0"
