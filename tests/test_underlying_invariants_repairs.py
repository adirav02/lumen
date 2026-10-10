"""Verification tests for underlying invariants repairs (Defects 1-6).

Covers:
1. Defect 1: Legacy NULL identity resolution & quarantine via Migration 007 and commit_evidence rejection.
2. Defect 2: Correction cannot revive obsolete evidence to active status; topic states, briefs, and reports exclude obsolete evidence.
3. Defect 3: Observation evidence does not count as assessed topic coverage.
4. Defect 4: Incomplete evaluation cannot complete question; requires all required subparts or allow_partial=True for partially_scored.
5. Defect 5: Stale legacy repair rejected with ConflictError; expected_link_states enforced.
6. Defect 6: Non-finite values rejected in verification checks and CLI input/output.
"""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.cli import main as cli_main
from course_tutor.errors import (
    ConflictError,
    ValidationError,
)
from course_tutor.models import compute_exercise_version_hash
from course_tutor.storage.migrations import (
    MIGRATIONS,
    repair_legacy_duplicate_links,
    resolve_and_quarantine_legacy_identities,
    run_migrations,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ==============================================================================
# DEFECT 1: Legacy NULL Identity Resolution, Backup, and Quarantine
# ==============================================================================

def test_defect1_legacy_identity_resolution_and_quarantine(temp_workspace):
    """Test Migration 007 identity resolution on unedited questions, quarantine on modified questions, and commit rejection."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c1")
        t = core.create_topic("prob-c1", name="Bayes", slug="bayes")

        # Ex 1: Unmodified question
        ex1 = core.create_exercise("prob-c1", "bayes_1", "What is P(A)?")
        ver1_id = ex1["exercise_version_id"]
        core.validate_exercise_version(
            ver1_id,
            reference_solution="0.5",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )

        # Ex 2: Modified question (bumped to revision 2)
        ex2 = core.create_exercise("prob-c1", "bayes_2", "What is P(B)?")
        ver2_id = ex2["exercise_version_id"]
        core.validate_exercise_version(
            ver2_id,
            reference_solution="0.7",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )
        core.update_exercise_version(
            ver2_id,
            expected_revision=1,
            question_text="What is P(B)? [updated wording]",
        )
        core.validate_exercise_version(
            ver2_id,
            reference_solution="0.7",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=2,
        )

        diag = core.create_assessment(
            "prob-c1",
            "Test Exam",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ver1_id, ver2_id],
            learner_id="alice",
        )["data"]
        diag_id = diag["assessment_id"]

        # Start and link attempts, commit evidence, and score both items
        att1 = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="alice")["attempt"]["id"]
        core.record_attempt_event(att1, expected_revision=1, event_type="work_submission", content="0.5")
        core.commit_evidence(att1, evaluations=[{"topic_id": t["id"], "skill_id": "b1", "correct": True}])
        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att1)

        att2 = core.start_assessment_item_attempt(diag_id, item_order=2, learner_id="alice")["attempt"]["id"]
        core.record_attempt_event(att2, expected_revision=1, event_type="work_submission", content="0.7")
        core.commit_evidence(att2, evaluations=[{"topic_id": t["id"], "skill_id": "b2", "correct": True}])
        core.record_assessment_item_score(diag_id, item_order=2, points_awarded=10.0, attempt_id=att2)

        # Both items are scored
        assert core.assessment_progress(diag_id)["completed_items"] == 2

        # Simulate legacy state after Migration 006 (attempts & evidence have NULL revision and hash)
        core.con.execute(
            "UPDATE attempts SET exercise_revision = NULL, exercise_content_hash = NULL WHERE id IN (?, ?)",
            (att1, att2),
        )
        core.con.execute(
            "UPDATE evidence SET exercise_revision = NULL, exercise_content_hash = NULL WHERE attempt_id IN (?, ?)",
            (att1, att2),
        )
        core.con.commit()

        # Run Migration 007 action
        resolve_and_quarantine_legacy_identities(core.con)

        # 1. Backups created before material changes
        assert core.con.execute("SELECT COUNT(*) FROM backup_v6_assessment_items").fetchone()[0] == 2
        assert core.con.execute("SELECT COUNT(*) FROM backup_v6_attempts").fetchone()[0] == 2
        assert core.con.execute("SELECT COUNT(*) FROM backup_v6_evidence").fetchone()[0] == 2

        # 2. Unmodified question attempt & evidence authoritatively resolved to rev 1
        att1_row = core.con.execute("SELECT * FROM attempts WHERE id = ?", (att1,)).fetchone()
        assert att1_row["exercise_revision"] == 1
        assert att1_row["exercise_content_hash"] is not None

        item1 = core.assessment_repo.get_item_by_order(diag_id, 1)
        assert item1.points_awarded == 10.0
        assert item1.score_status == "scored"

        # 3. Modified question attempt remains unresolved (NULL)
        att2_row = core.con.execute("SELECT * FROM attempts WHERE id = ?", (att2,)).fetchone()
        assert att2_row["exercise_revision"] is None
        assert att2_row["exercise_content_hash"] is None

        # Item 2 is quarantined to pending_review with audit history
        item2 = core.assessment_repo.get_item_by_order(diag_id, 2)
        assert item2.points_awarded is None
        assert item2.score_status == "pending_review"
        assert any(h["action"] == "invalidated_unresolved_or_outdated_identity" for h in item2.score_history)

        # Assessment reopened
        assert core.assessment_repo.get_assessment(diag_id).status == "open"

        # 4. commit_evidence strictly rejects evaluating attempt with unresolved identity
        core.record_attempt_event(att2, expected_revision=2, event_type="work_submission", content="0.75")
        with pytest.raises(ValidationError, match="unresolved educational identity"):
            core.commit_evidence(
                att2,
                evaluations=[{
                    "topic_id": t["id"],
                    "skill_id": "b2_new",
                    "correct": True,
                }],
            )
    finally:
        core.close()


# ==============================================================================
# DEFECT 2: Corrections on Obsolete Evidence
# ==============================================================================

def test_defect2_correction_on_obsolete_evidence_stays_pending(temp_workspace):
    """Test that correcting obsolete evidence marks replacement as pending_review and excludes it from topic state."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c2")
        t = core.create_topic("prob-c2", name="Conditionals", slug="cond")

        ex = core.create_exercise("prob-c2", "cond_1", "What is P(A|B)?")
        ver_id = ex["exercise_version_id"]
        core.validate_exercise_version(
            ver_id,
            reference_solution="0.4",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )

        # Start attempt and commit incorrect evidence on Revision 1
        att = core.start_attempt("prob-c2", ver_id, learner_id="alice")["data"]
        att_id = att["id"]
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="0.2")
        comm_res = core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "cond_skill",
                "correct": False,
                "demonstrated_level": "incorrect",
            }],
        )
        ev_id = comm_res["data"]["evidence_created"][0]["id"]

        # Check initial topic state: 1 error
        state1 = core.evidence_repo.get_topic_state("prob-c2", t["id"])
        assert state1.error_count == 1
        assert state1.independent_success_count == 0

        # Now exercise version is updated to Revision 2!
        core.update_exercise_version(
            ver_id,
            expected_revision=1,
            question_text="What is P(A|B)? [clarified wording]",
        )
        core.validate_exercise_version(
            ver_id,
            reference_solution="0.4",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=2,
        )

        # Now correct the older revision 1 evidence to independent_mastery
        corr_res = core.correct_evidence(
            evidence_id=ev_id,
            correction_reason="Instructor override on old submission",
            replacement={"demonstrated_level": "independent_mastery"},
        )
        new_ev = corr_res["data"]["resulting_evidence"]
        # Replacement MUST NOT be active; it must be pending_review!
        assert new_ev["status"] == "pending_review"
        assert "Historical correction on obsolete/pending revision" in new_ev["rationale"]

        # Recomputed topic state MUST NOT count the obsolete evidence as a success!
        state2 = core.evidence_repo.get_topic_state("prob-c2", t["id"])
        assert state2.independent_success_count == 0
        assert state2.unassessed_flag is True

        # Course brief must report topic as unassessed
        brief = core.course_brief("prob-c2", learner_id="alice")
        assert "Conditionals" in brief["coverage"]["unassessed_topics"]
    finally:
        core.close()


# ==============================================================================
# DEFECT 3: Observation Evidence Does Not Count as Assessed Coverage
# ==============================================================================

def test_defect3_observation_evidence_excluded_from_assessed_coverage(temp_workspace):
    """Test that observation-level evidence sets assessed=False in diagnostic topic coverage and course brief."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c3")
        t = core.create_topic("prob-c3", name="Independence", slug="indep")

        ex = core.create_exercise("prob-c3", "indep_1", "Are A and B independent?")
        ver_id = ex["exercise_version_id"]
        core.validate_exercise_version(
            ver_id,
            reference_solution="Yes",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-c3",
            "Independence Assessment",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ver_id],
            learner_id="alice",
        )["data"]
        diag_id = diag["assessment_id"]

        item_att = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="alice")
        att_id = item_att["attempt"]["id"]
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="maybe")

        # Commit observation evidence (unassessed level)
        core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "indep_skill",
                "correct": False,
                "demonstrated_level": "unassessed",
            }],
        )

        # Check diagnostic progress coverage
        prog = core.assessment_progress(diag_id)
        coverage = prog["topic_coverage"]["Independence"]
        assert coverage["assessed"] is False
        assert coverage["independent_successes"] == 0
        assert coverage["errors"] == 0

        # Topic state is unassessed
        state = core.evidence_repo.get_topic_state("prob-c3", t["id"])
        assert state.unassessed_flag is True

        # Course brief reports topic as unassessed
        brief = core.course_brief("prob-c3", learner_id="alice")
        assert "Independence" in brief["coverage"]["unassessed_topics"]
    finally:
        core.close()


# ==============================================================================
# DEFECT 4: Subpart Evaluation Completeness & Partial Scoring
# ==============================================================================

def test_defect4_subpart_completeness_and_partial_scoring(temp_workspace):
    """Test that incomplete subpart evaluation cannot mark item as scored without allow_partial=True."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c4")
        t = core.create_topic("prob-c4", name="Random Variables", slug="rv")

        ex = core.create_exercise(
            "prob-c4",
            "rv_2part",
            "Find E[X] and Var(X)",
            subparts=[{"subpart_key": "part_a", "prompt": "E[X]"}, {"subpart_key": "part_b", "prompt": "Var(X)"}],
        )
        ver_id = ex["exercise_version_id"]
        core.validate_exercise_version(
            ver_id,
            reference_solution="E[X]=3, Var(X)=1",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-c4",
            "RV Exam",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ver_id],
            learner_id="alice",
        )["data"]
        diag_id = diag["assessment_id"]

        item_att = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="alice")
        att_id = item_att["attempt"]["id"]

        # Submit work and evaluate only part_a
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="E[X]=3", subpart_key="part_a")
        core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "mean_skill",
                "correct": True,
                "demonstrated_level": "independent_mastery",
                "subpart_key": "part_a",
            }],
        )

        # 1. Scoring without allow_partial=True MUST fail with missing subparts error
        with pytest.raises(ValidationError, match="declared subparts missing evaluated evidence"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=5.0, attempt_id=att_id)

        # 2. Scoring with allow_partial=True succeeds with score_status='partially_scored'
        partial_res = core.record_assessment_item_score(
            diag_id,
            item_order=1,
            points_awarded=5.0,
            attempt_id=att_id,
            allow_partial=True,
        )
        assert partial_res["score_status"] == "partially_scored"
        assert partial_res["completed"] is False
        assert "part_b" in partial_res["missing_subparts"]

        # Assessment remains 'open'
        prog = core.assessment_progress(diag_id)
        assert prog["status"] == "open"
        assert prog["completed_items"] == 0
        assert len(prog["pending_work"]["pending_review_items"]) == 1

        # 3. Now evaluate part_b
        core.record_attempt_event(att_id, expected_revision=2, event_type="work_submission", content="Var(X)=1", subpart_key="part_b")
        core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "var_skill",
                "correct": True,
                "demonstrated_level": "independent_mastery",
                "subpart_key": "part_b",
            }],
        )

        # 4. Now score item completely
        full_res = core.record_assessment_item_score(
            diag_id,
            item_order=1,
            points_awarded=10.0,
            attempt_id=att_id,
        )
        assert full_res["score_status"] == "scored"
        assert full_res["completed"] is True
        assert full_res["missing_subparts"] == []

        prog_full = core.assessment_progress(diag_id)
        assert prog_full["status"] == "completed"
        assert prog_full["completed_items"] == 1
    finally:
        core.close()


# ==============================================================================
# DEFECT 5: Stale Legacy Repair & expected_link_states
# ==============================================================================

def test_defect5_stale_legacy_repair_and_expected_link_states(temp_workspace):
    """Test that already-resolved legacy repairs and unexpected link states raise ConflictError."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c5")
        t = core.create_topic("prob-c5", name="Counting", slug="count")

        ex1 = core.create_exercise("prob-c5", "count_1", "How many permutations?")
        ver1_id = ex1["exercise_version_id"]
        core.validate_exercise_version(
            ver1_id,
            reference_solution="6",
            rubric={"max_points": 5},
            checks={"math": True},
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-c5",
            "Counting Exam",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ver1_id],
            learner_id="alice",
        )["data"]
        diag_id = diag["assessment_id"]

        item = core.assessment_repo.get_item_by_order(diag_id, 1)

        # Create diagnostic attempt
        att = core.start_attempt("prob-c5", ver1_id, learner_id="alice", mode="diagnostic")["data"]
        att_id = att["id"]

        # Ensure quarantine table exists
        core.con.execute(
            """
            CREATE TABLE IF NOT EXISTS legacy_duplicate_attempt_links (
                id TEXT PRIMARY KEY,
                attempt_id TEXT NOT NULL,
                assessment_item_id TEXT NOT NULL,
                assessment_id TEXT NOT NULL,
                item_order INTEGER NOT NULL,
                exercise_version_id TEXT NOT NULL,
                learner_id TEXT,
                points_awarded REAL,
                score_status TEXT,
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                score_history_json TEXT NOT NULL DEFAULT '[]',
                quarantined_at TEXT NOT NULL,
                resolution_status TEXT NOT NULL DEFAULT 'quarantined',
                resolution_notes TEXT NOT NULL DEFAULT ''
            );
            """
        )

        # Insert quarantine record in legacy_duplicate_attempt_links
        core.con.execute(
            """
            INSERT INTO legacy_duplicate_attempt_links (
                id, attempt_id, assessment_item_id, assessment_id, item_order,
                exercise_version_id, learner_id, points_awarded, score_status,
                evidence_ids_json, score_history_json, quarantined_at,
                resolution_status, resolution_notes
            ) VALUES (?, ?, ?, ?, 1, ?, 'alice', NULL, 'pending_review', '[]', '[]', datetime('now'), 'quarantined', 'test')
            """,
            (f"{att_id}_{item.id}", att_id, item.id, diag_id, ver1_id),
        )
        core.con.commit()

        # 1. Resolve it the first time: succeeds
        res1 = core.repair_legacy_duplicate_links(resolved_assignments={att_id: item.id})
        assert len(res1["resolved"]) == 1

        # Now score this item with valid work & evidence
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="6")
        core.commit_evidence(att_id, evaluations=[{"topic_id": t["id"], "skill_id": "p", "correct": True}])
        core.record_assessment_item_score(diag_id, item_order=1, points_awarded=5.0, attempt_id=att_id)

        # 2. Reaffirming the unchanged link is an idempotent no-op
        res_reaffirm = core.repair_legacy_duplicate_links(resolved_assignments={att_id: item.id})
        assert res_reaffirm["resolved"][0]["reaffirmed"] is True

        # 3. Create fresh diagnostic attempt att2 and add quarantine record
        att2 = core.start_attempt("prob-c5", ver1_id, learner_id="alice", mode="diagnostic")["data"]
        att2_id = att2["id"]

        core.con.execute(
            """
            INSERT INTO legacy_duplicate_attempt_links (
                id, attempt_id, assessment_item_id, assessment_id, item_order,
                exercise_version_id, learner_id, points_awarded, score_status,
                evidence_ids_json, score_history_json, quarantined_at,
                resolution_status, resolution_notes
            ) VALUES (?, ?, ?, ?, 1, ?, 'alice', NULL, 'pending_review', '[]', '[]', datetime('now'), 'quarantined', 'test2')
            """,
            (f"{att2_id}_{item.id}", att2_id, item.id, diag_id, ver1_id),
        )
        core.con.commit()

        # 4. Trying to overwrite active scored attempt (att_id) without expected_link_states raises ConflictError
        with pytest.raises(ConflictError, match="Cannot overwrite active scored attempt"):
            core.repair_legacy_duplicate_links(resolved_assignments={att2_id: item.id})

        # 5. Overwriting with wrong expected_link_states raises ConflictError
        with pytest.raises(ConflictError, match="Stale link expectation"):
            core.repair_legacy_duplicate_links(
                resolved_assignments={att2_id: item.id},
                expected_link_states={item.id: "wrong_expected_attempt_id"},
            )

        # 6. Overwriting with matching expected_link_states succeeds and invalidates prior score
        res2 = core.repair_legacy_duplicate_links(
            resolved_assignments={att2_id: item.id},
            expected_link_states={item.id: att_id},
        )
        assert len(res2["resolved"]) == 1
        assert res2["resolved"][0]["reaffirmed"] is False
        prog2 = core.assessment_progress(diag_id)
        assert prog2["status"] == "open"
        assert prog2["completed_items"] == 0

        # 7. Trying to reuse already-resolved quarantine record for att_id now fails with ConflictError!
        with pytest.raises(ConflictError, match="Stale legacy repair"):
            core.repair_legacy_duplicate_links(resolved_assignments={att_id: item.id})
    finally:
        core.close()


# ==============================================================================
# DEFECT 6: Finite Numeric Validation in Checks and CLI
# ==============================================================================

def test_defect6_finite_numeric_checks_and_cli_payload(temp_workspace):
    """Test that non-finite numbers (NaN, Inf, booleans) are rejected in checks and CLI."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c6")
        ex = core.create_exercise("prob-c6", "finite_check", "Check question")
        ver_id = ex["exercise_version_id"]

        # 1. Reject NaN/Inf in structured check score
        for bad_score in [float("nan"), float("inf"), float("-inf"), True, False]:
            with pytest.raises(ValidationError, match="score' for 'math' must be a finite numeric value"):
                core.validate_exercise_version(
                    ver_id,
                    reference_solution="ans",
                    rubric={"max_points": 5},
                    checks={"math": {"status": "passed", "score": bad_score}},
                    expected_revision=1,
                )

        # Reject negative score
        with pytest.raises(ValidationError, match="score' for 'math' must be >= 0.0"):
            core.validate_exercise_version(
                ver_id,
                reference_solution="ans",
                rubric={"max_points": 5},
                checks={"math": {"status": "passed", "score": -1.0}},
                expected_revision=1,
            )

        # 2. Reject non-string reason/notes
        with pytest.raises(ValidationError, match="reason' for 'math' must be a string"):
            core.validate_exercise_version(
                ver_id,
                reference_solution="ans",
                rubric={"max_points": 5},
                checks={"math": {"status": "passed", "reason": 12345}},
                expected_revision=1,
            )

        # 3. Reject non-finite values in nested metadata
        with pytest.raises(ValidationError, match="Non-finite numeric value in Structured check 'metadata'"):
            core.validate_exercise_version(
                ver_id,
                reference_solution="ans",
                rubric={"max_points": 5},
                checks={"math": {"status": "passed", "metadata": {"nested": {"tolerance": float("nan")}}}},
                expected_revision=1,
            )

        # 4. Passing structured check succeeds
        core.validate_exercise_version(
            ver_id,
            reference_solution="ans",
            rubric={"max_points": 5},
            checks={"math": {"status": "passed", "score": 1.0, "reason": "All passed", "metadata": {"run_time": 0.05}}},
            expected_revision=1,
        )
        assert core.exercise_repo.get_exercise_version(ver_id).validation_state == "validated"
    finally:
        core.close()

    # 5. CLI input with raw NaN / Infinity rejected with exit code 1
    for bad_json in ['{"points_awarded": NaN}', '{"score": Infinity}', '{"tolerance": -Infinity}']:
        with pytest.raises(SystemExit) as excinfo:
            cli_main([
                "--workspace", str(temp_workspace),
                "--json-input", bad_json,
                "capabilities",
            ])
        assert excinfo.value.code == 1
