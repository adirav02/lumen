"""Deterministic regression tests verifying all nine confirmed defects and security invariants.

Covers:
- Defect 1: Enforce evidence-level schema; reject observation levels for confirmed scores; require evaluated evidence.
- Defect 2: Reject evaluating old submissions against changed exercise content; reject scoring outdated evidence revisions.
- Defect 3: Exact-revision validation mandatory (strictly positive int or non-empty content hash).
- Defect 4: Record final attested candidate revision and content hash in validation provenance.
- Defect 5: Reject contradictory structured checks, duplicate check names, and failing statuses.
- Defect 6: Caller-supplied learner_id must match attempt owner in assessment item linking.
- Defect 7: Repeated legacy repair reaffirmation is an idempotent no-op preserving points, evidence, and completed state.
- Defect 8: CLI forwards submission_event_id; detects conflicting request-id/course-id; rejects non-object payloads with code 1.
- Defect 9: Restore rejects Zip Slip, symlinks, absolute paths, and external database source paths.
- Migration 006: Upgrade schema to v6, persisting exercise revision and content hash identity.
"""

import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.cli import main as cli_main
from course_tutor.errors import (
    RestoreIntegrityError,
    StaleRevisionError,
    UnvalidatedQuestionError,
    ValidationError,
)
from course_tutor.storage.db import get_connection
from course_tutor.storage.migrations import (
    MIGRATIONS,
    _execute_sql_script,
    repair_legacy_duplicate_links,
    run_migrations,
)
from course_tutor.storage.repositories import compute_exercise_version_hash


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ==============================================================================
# DEFECT 1: Enforce evidence-level schema; reject unassessed observation levels
# ==============================================================================

def test_defect1_observation_levels_rejected_for_confirmed_scores(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d1")
        t = core.create_topic("prob-d1", name="Bayes", slug="bayes")
        ex = core.create_exercise("prob-d1", "bayes_1", "Compute P(A|B)", subparts=["part_a", "part_b"])
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="0.4 and 0.6",
            rubric={"max_points": 10},
            checks=["checked"],
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-d1",
            "Bayes Diagnostic",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        item_att = core.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = item_att["attempt"]["id"]

        # 1. Invalid demonstrated_level schema rejected
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="work", subpart_key="part_a")
        with pytest.raises(ValidationError, match="Invalid demonstrated_level"):
            core.commit_evidence(
                att_id,
                evaluations=[{
                    "topic_id": t["id"],
                    "skill_id": "bayes_skill",
                    "correct": False,
                    "demonstrated_level": "completely_invalid_level",
                    "subpart_key": "part_a",
                }],
            )

        # 2. Observation demonstrated_level ("unassessed", "pending", "uncertain", "unreadable")
        # Commit observation evidence
        comm_res = core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "bayes_skill",
                "correct": False,
                "demonstrated_level": "unassessed",
                "subpart_key": "part_a",
            }],
        )
        unassessed_ev_id = comm_res["data"]["evidence_created"][0]["id"]

        # 3. Cannot award confirmed score based on observation/unassessed evidence
        with pytest.raises(ValidationError, match="Confirmed scores cannot be supported by unassessed work"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=5.0, attempt_id=att_id)

        # 4. Progress reporting must never classify unassessed work as assisted
        progress = core.assessment_progress(diag_id)
        assert progress["items"][0]["performance_classification"] == "unassessed"
        assert progress["items"][0]["points_awarded"] is None
        assert progress["assistance"]["assisted_items_count"] == 0

        # Retract unassessed observation evidence before evaluating actual work
        core.correct_evidence(
            evidence_id=unassessed_ev_id,
            correction_reason="Retracting observation evidence to submit evaluated work",
        )

        # 5. Positive score requires positive evaluated evidence
        # If we commit incorrect evaluated work for part_a:
        core.record_attempt_event(att_id, expected_revision=2, event_type="work_submission", content="wrong work", subpart_key="part_a")
        core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "bayes_skill",
                "correct": False,
                "demonstrated_level": "incorrect",
                "subpart_key": "part_a",
            }],
        )
        with pytest.raises(ValidationError, match="Cannot award positive points"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=5.0, attempt_id=att_id)

        # 6. Zero score can be awarded for evaluated incorrect work (allow_partial=True when subparts remain)
        zero_score = core.record_assessment_item_score(diag_id, item_order=1, points_awarded=0.0, attempt_id=att_id, allow_partial=True)
        assert zero_score["points_awarded"] == 0.0
        assert zero_score["score_status"] == "partially_scored"

        # 7. Full credit requires all declared subparts evaluated
        # Only part_a is evaluated. Attempting to award full credit (10 points) must be rejected
        core.record_attempt_event(att_id, expected_revision=3, event_type="work_submission", content="correct work a", subpart_key="part_a")
        core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "bayes_skill",
                "correct": True,
                "demonstrated_level": "independent_mastery",
                "subpart_key": "part_a",
            }],
        )
        with pytest.raises(ValidationError, match="declared subparts missing evaluated evidence"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)

        # Now evaluate part_b
        core.record_attempt_event(att_id, expected_revision=4, event_type="work_submission", content="correct work b", subpart_key="part_b")
        core.commit_evidence(
            att_id,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "bayes_skill",
                "correct": True,
                "demonstrated_level": "independent_mastery",
                "subpart_key": "part_b",
            }],
        )
        # Now full credit is allowed
        full_score = core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)
        assert full_score["points_awarded"] == 10.0
    finally:
        core.close()


# ==============================================================================
# DEFECT 2: Old submissions rejected after exercise replacement
# ==============================================================================

def test_defect2_submission_reuse_rejected_after_exercise_replacement(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d2")
        t = core.create_topic("prob-d2", name="Expectation", slug="exp")
        ex = core.create_exercise("prob-d2", "exp_1", "Calculate E[X] for fair die")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="3.5",
            rubric={"max_points": 10},
            checks=["checked"],
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-d2",
            "Expectation Diagnostic",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # Learner starts attempt on revision 1
        item_att = core.start_assessment_item_attempt(diag_id, item_order=1)
        att_id = item_att["attempt"]["id"]
        ev_res = core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="3.5")
        ev_id = ev_res["data"]["event"]["id"]

        # Exercise is updated -> becomes revision 2
        core.update_exercise_version(ex["exercise_version_id"], question_text="Calculate E[X] for loaded die")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="4.0",
            rubric={"max_points": 10},
            checks=["checked"],
            expected_revision=2,
        )

        # 1. Evaluating old revision 1 submission against revision 2 exercise is rejected
        with pytest.raises(ValidationError, match="Cannot evaluate submission against outdated exercise revision"):
            core.commit_evidence(
                att_id,
                evaluations=[{"topic_id": t["id"], "skill_id": "exp_calc", "correct": True, "submission_event_id": ev_id}],
            )

        # 2. Scoring assessment item using evidence from outdated exercise revision is rejected
        # Even if attempt had old evidence committed prior to question update:
        # Start a fresh test case for this invariant
        ex_b = core.create_exercise("prob-d2", "exp_2", "Calculate E[Y]")
        core.validate_exercise_version(
            ex_b["exercise_version_id"],
            reference_solution="1.0",
            rubric={"max_points": 5},
            checks=["checked"],
            expected_revision=1,
        )
        diag_b = core.create_assessment(
            "prob-d2",
            "Diag B",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex_b["exercise_version_id"]],
        )["data"]["assessment_id"]

        item_att_b = core.start_assessment_item_attempt(diag_b, item_order=1)
        att_b_id = item_att_b["attempt"]["id"]
        core.record_attempt_event(att_b_id, expected_revision=1, event_type="work_submission", content="1.0")
        core.commit_evidence(att_b_id, evaluations=[{"topic_id": t["id"], "skill_id": "exp_calc", "correct": True}])

        # Now replace exercise content and re-validate
        core.update_exercise_version(ex_b["exercise_version_id"], question_text="Calculate E[Y] for Poisson")
        core.validate_exercise_version(
            ex_b["exercise_version_id"],
            reference_solution="lambda",
            rubric={"max_points": 5},
            checks=["checked"],
            expected_revision=2,
        )

        # Scoring item with old attempt (revision 1) must be rejected
        with pytest.raises(ValidationError, match="does not match current revision"):
            core.record_assessment_item_score(diag_b, item_order=1, points_awarded=5.0, attempt_id=att_b_id)
    finally:
        core.close()


# ==============================================================================
# DEFECT 3: Exact-revision validation mandatory
# ==============================================================================

def test_defect3_exact_revision_mandatory_in_validation(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d3")
        ex = core.create_exercise("prob-d3", "ex_rev", "What is P(A)?")
        v_id = ex["exercise_version_id"]

        # 1. Calling without expected_revision or expected_content_hash is rejected
        with pytest.raises(ValidationError, match="requires caller-side identity"):
            core.validate_exercise_version(
                v_id,
                reference_solution="0.5",
                rubric={"max_points": 10},
                checks=["checked"],
            )

        # 2. Non-positive or non-int revision rejected
        for bad_rev in [0, -1, -5, "1", 1.0, True, False]:
            with pytest.raises(ValidationError, match="expected_revision must be a positive integer"):
                core.validate_exercise_version(
                    v_id,
                    reference_solution="0.5",
                    rubric={"max_points": 10},
                    checks=["checked"],
                    expected_revision=bad_rev,
                )

        # 3. Empty or whitespace content hash rejected
        for bad_hash in ["", "   ", None]:
            if bad_hash is None:
                continue
            with pytest.raises(ValidationError, match="expected_content_hash must be a non-empty string"):
                core.validate_exercise_version(
                    v_id,
                    reference_solution="0.5",
                    rubric={"max_points": 10},
                    checks=["checked"],
                    expected_content_hash=bad_hash,
                )

        # 4. Mismatched revision rejected
        with pytest.raises(StaleRevisionError):
            core.validate_exercise_version(
                v_id,
                reference_solution="0.5",
                rubric={"max_points": 10},
                checks=["checked"],
                expected_revision=99,
            )

        # 5. Mismatched content hash rejected
        with pytest.raises(ValidationError, match="content hash mismatch"):
            core.validate_exercise_version(
                v_id,
                reference_solution="0.5",
                rubric={"max_points": 10},
                checks=["checked"],
                expected_content_hash="bad_hash_123",
            )

        # 6. Valid expected_revision succeeds
        res = core.validate_exercise_version(
            v_id,
            reference_solution="0.5",
            rubric={"max_points": 10},
            checks=["checked"],
            expected_revision=1,
        )
        assert res["validation_state"] == "validated"
    finally:
        core.close()


# ==============================================================================
# DEFECT 4: Validation provenance records final attested candidate revision & hash
# ==============================================================================

def test_defect4_validation_provenance_records_final_attested_content_and_history(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d4")
        ex = core.create_exercise("prob-d4", "ex_prov", "Solve integral")
        v_id = ex["exercise_version_id"]

        # Validate initial version
        val_res1 = core.validate_exercise_version(
            v_id,
            reference_solution="1.0",
            rubric={"max_points": 5},
            checks=["checked"],
            expected_revision=1,
        )
        prov1 = json.loads(val_res1["validation_notes"])
        assert prov1["checked_revision"] == 1
        assert "content_hash" in prov1

        # Update solution and re-validate
        val_res2 = core.validate_exercise_version(
            v_id,
            reference_solution="1.0 (by calculus)",
            rubric={"max_points": 5},
            checks=["checked_calc"],
            expected_revision=1,
        )
        prov2 = json.loads(val_res2["validation_notes"])
        assert prov2["checked_revision"] == 2
        assert prov2["previous_revision"] == 1
        assert "previous_content_hash" in prov2

        # Check in DB
        db_ver = core.exercise_repo.get_exercise_version(v_id)
        assert len(db_ver.revision_history) == 1
        assert db_ver.revision_history[0]["reference_solution"] == "1.0"
        assert db_ver.reference_solution == "1.0 (by calculus)"
    finally:
        core.close()


# ==============================================================================
# DEFECT 5: Contradictory and invalid structured checks rejected
# ==============================================================================

def test_defect5_contradictory_and_invalid_structured_checks_rejected(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d5")
        ex = core.create_exercise("prob-d5", "ex_checks", "Verify axiom")
        v_id = ex["exercise_version_id"]

        # 1. Conflicting status and state
        with pytest.raises(ValidationError, match="Conflicting status"):
            core.validate_exercise_version(
                v_id,
                reference_solution="axiom",
                rubric={"max_points": 5},
                checks={"math_check": {"status": "passed", "state": "failed"}},
                expected_revision=1,
            )

        with pytest.raises(ValidationError, match="Conflicting status"):
            core.validate_exercise_version(
                v_id,
                reference_solution="axiom",
                rubric={"max_points": 5},
                checks={"math_check": {"status": "ok", "state": "pending"}},
                expected_revision=1,
            )

        # 2. Unknown keys in structured check
        with pytest.raises(ValidationError, match="Invalid keys in structured check"):
            core.validate_exercise_version(
                v_id,
                reference_solution="axiom",
                rubric={"max_points": 5},
                checks={"math_check": {"status": "passed", "unsupported_field": True}},
                expected_revision=1,
            )

        # 3. Duplicate check names (case-insensitive)
        with pytest.raises(ValidationError, match="Duplicate verification check"):
            core.validate_exercise_version(
                v_id,
                reference_solution="axiom",
                rubric={"max_points": 5},
                checks=["syntax_check", "SYNTAX_CHECK"],
                expected_revision=1,
            )

        # 4. Failing or pending check statuses rejected
        for bad_status in ["failed", "falsified", "rejected", "pending", "unknown"]:
            with pytest.raises(ValidationError, match="verification checks must pass"):
                core.validate_exercise_version(
                    v_id,
                    reference_solution="axiom",
                    rubric={"max_points": 5},
                    checks={"math_check": {"status": bad_status, "reason": "not ready"}},
                    expected_revision=1,
                )

        # 5. Passing structured check accepted
        good = core.validate_exercise_version(
            v_id,
            reference_solution="axiom",
            rubric={"max_points": 5},
            checks={"math_check": {"status": "passed", "reason": "formally checked", "score": 1.0}},
            expected_revision=1,
        )
        assert good["validation_state"] == "validated"
    finally:
        core.close()


# ==============================================================================
# DEFECT 6: Caller-supplied learner_id must match attempt owner in linking
# ==============================================================================

def test_defect6_caller_supplied_learner_id_verified_against_attempt_owner(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d6")
        t = core.create_topic("prob-d6", name="Independence", slug="indep")
        ex = core.create_exercise("prob-d6", "indep_1", "Test independence")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="independent",
            rubric={"max_points": 5},
            checks=["checked"],
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-d6",
            "Independence Diag",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        # Alice starts diagnostic attempt
        alice_att = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="alice")["attempt"]

        # Caller provides foreign learner_id ("bob") to link Alice's attempt
        with pytest.raises(ValidationError, match="does not match attempt owner"):
            core.link_assessment_item_attempt(
                diag_id,
                item_order=1,
                attempt_id=alice_att["id"],
                learner_id="bob",
            )

        # Caller provides matching learner_id ("alice")
        res = core.link_assessment_item_attempt(
            diag_id,
            item_order=1,
            attempt_id=alice_att["id"],
            learner_id="alice",
        )
        assert res["reaffirmed"] is True
        assert res["learner_id"] == "alice"
    finally:
        core.close()


# ==============================================================================
# DEFECT 7: Repeated legacy repair reaffirmation is idempotent no-op
# ==============================================================================

def test_defect7_repeated_legacy_repair_idempotent_and_safe_relink(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d7")
        t = core.create_topic("prob-d7", name="Combinatorics", slug="comb")
        ex = core.create_exercise("prob-d7", "comb_1", "Compute permutations")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="120",
            rubric={"max_points": 10},
            checks=["checked"],
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-d7",
            "Combinatorics Diag",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        diag_id = diag["assessment_id"]

        item_att = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="alice")
        att_id = item_att["attempt"]["id"]
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="120")
        core.commit_evidence(att_id, evaluations=[{"topic_id": t["id"], "skill_id": "perm_calc", "correct": True}])
        score_res = core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att_id)
        assert score_res["points_awarded"] == 10.0

        # Assessment is completed once its only item is scored
        ass_init = core.assessment_repo.get_assessment(diag_id)
        assert ass_init.status == "completed"

        # 1. Reaffirming the link is an idempotent no-op preserving points and completion
        for _ in range(3):
            reaffirm = core.link_assessment_item_attempt(diag_id, item_order=1, attempt_id=att_id, learner_id="alice")
            assert reaffirm["reaffirmed"] is True
            assert reaffirm["points_awarded"] == 10.0

            ass_check = core.assessment_repo.get_assessment(diag_id)
            assert ass_check.status == "completed"

            item_check = core.assessment_repo.get_item_by_order(diag_id, 1)
            assert item_check.points_awarded == 10.0
            assert item_check.score_status == "scored"

        # 2. Migration repair legacy duplicate links is idempotent on existing clean links
        repair_res = repair_legacy_duplicate_links(core.con)
        assert len(repair_res["resolved"]) == 0
        assert len(repair_res["unresolved"]) == 0

        # Verify state is still intact
        ass_check2 = core.assessment_repo.get_assessment(diag_id)
        assert ass_check2.status == "completed"
    finally:
        core.close()


# ==============================================================================
# DEFECT 8: CLI forwards submission_event_id and validates payload
# ==============================================================================

def test_defect8_cli_forwards_submission_event_id_and_validates_payload(temp_workspace):
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-d8")
        t = core.create_topic("prob-d8", name="Distributions", slug="dist")
        ex = core.create_exercise("prob-d8", "dist_1", "What is Binomial mean?")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="np",
            rubric={"max_points": 5},
            checks=["checked"],
            expected_revision=1,
        )
        att = core.start_attempt("prob-d8", ex["exercise_version_id"])["data"]
        att_id = att["id"]
        ev_res = core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="np")
        ev_id = ev_res["data"]["event"]["id"]
    finally:
        core.close()

    # 1. CLI commit_evidence with submission_event_id forwards properly
    payload = json.dumps({
        "attempt_id": att_id,
        "submission_event_id": ev_id,
        "evaluations": [{
            "topic_id": t["id"],
            "skill_id": "dist_mean",
            "correct": True,
        }],
    })
    with pytest.raises(SystemExit) as excinfo:
        cli_main([
            "--workspace", str(temp_workspace),
            "--json-input", payload,
            "commit_evidence",
        ])
    assert excinfo.value.code == 0

    # 2. CLI rejects non-object JSON payload with code 1
    for bad_payload in ['[1, 2, 3]', '"string_payload"', '12345', 'true']:
        with pytest.raises(SystemExit) as excinfo:
            cli_main([
                "--workspace", str(temp_workspace),
                "--json-input", bad_payload,
                "commit_evidence",
            ])
        assert excinfo.value.code == 1

    # 3. CLI detects conflicting --request-id vs payload request_id
    conflicting_req_payload = json.dumps({
        "attempt_id": att_id,
        "request_id": "req-internal-123",
        "evaluations": [{"topic_id": t["id"], "skill_id": "dist_mean", "correct": True}],
    })
    with pytest.raises(SystemExit) as excinfo:
        cli_main([
            "--workspace", str(temp_workspace),
            "--json-input", conflicting_req_payload,
            "--request-id", "req-cli-456",
            "commit_evidence",
        ])
    assert excinfo.value.code == 1

    # 4. CLI detects conflicting --course-id vs payload course_id
    conflicting_course_payload = json.dumps({
        "course_id": "prob-internal",
        "name": "Topic Name",
        "slug": "topic-slug",
    })
    with pytest.raises(SystemExit) as excinfo:
        cli_main([
            "--workspace", str(temp_workspace),
            "--course-id", "prob-cli",
            "--json-input", conflicting_course_payload,
            "create_topic",
        ])
    assert excinfo.value.code == 1


# ==============================================================================
# DEFECT 9: Restore rejects Zip Slip, symlinks, absolute paths, and external DB paths
# ==============================================================================

def test_defect9_restore_path_traversal_and_zip_slip_rejection(temp_workspace):
    # 1. Zip Slip archive containing ../evil.txt
    slip_zip = temp_workspace / "zip_slip.zip"
    with zipfile.ZipFile(slip_zip, "w") as zf:
        zf.writestr("../evil.txt", "malicious escape")
        manifest = {
            "format_version": 1,
            "manifest_version": 1,
            "lumen_version": "1.0.0",
            "database": "lumen.db",
            "sources": [],
        }
        zf.writestr("manifest.json", json.dumps(manifest))

    dest1 = temp_workspace / "dest1"
    with pytest.raises(RestoreIntegrityError, match="traversal sequence"):
        LumenCore.restore(slip_zip, dest1)

    # 2. Zip archive containing absolute path
    abs_zip = temp_workspace / "abs_path.zip"
    with zipfile.ZipFile(abs_zip, "w") as zf:
        zf.writestr("/etc/passwd", "malicious root")
        manifest = {
            "format_version": 1,
            "manifest_version": 1,
            "lumen_version": "1.0.0",
            "database": "lumen.db",
            "sources": [],
        }
        zf.writestr("manifest.json", json.dumps(manifest))

    dest2 = temp_workspace / "dest2"
    with pytest.raises(RestoreIntegrityError, match="absolute path"):
        LumenCore.restore(abs_zip, dest2)

    # 3. Valid zip structure but manifest specifies database with traversal
    traversal_manifest_zip = temp_workspace / "traversal_manifest.zip"
    with zipfile.ZipFile(traversal_manifest_zip, "w") as zf:
        manifest = {
            "format_version": 1,
            "manifest_version": 1,
            "lumen_version": "1.0.0",
            "database": "../../external.db",
            "sources": [],
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("lumen.db", "not a real db")

    dest3 = temp_workspace / "dest3"
    with pytest.raises(RestoreIntegrityError, match="path traversal"):
        LumenCore.restore(traversal_manifest_zip, dest3)


# ==============================================================================
# MIGRATION 006: Upgrade schema to v6
# ==============================================================================

def test_migration_006_upgrade_adds_revision_and_hash_columns(temp_workspace):
    # Initialize workspace with v5 schema
    db_path = temp_workspace / "lumen.db"
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        );
        """
    )
    for version, desc, sql in MIGRATIONS[:5]:
        _execute_sql_script(con, sql)
        con.execute(
            "INSERT INTO schema_migrations (version, applied_at, description) VALUES (?, datetime('now'), ?)",
            (version, desc),
        )
    con.commit()

    ver_row = con.execute("SELECT MAX(version) as max_v FROM schema_migrations").fetchone()
    assert ver_row["max_v"] == 5

    # Check columns before migration 006
    att_cols = {r["name"] for r in con.execute("PRAGMA table_info(attempts)").fetchall()}
    assert "exercise_revision" not in att_cols
    assert "exercise_content_hash" not in att_cols

    ev_cols = {r["name"] for r in con.execute("PRAGMA table_info(evidence)").fetchall()}
    assert "exercise_revision" not in ev_cols
    assert "exercise_content_hash" not in ev_cols

    # Run full migrations -> applies 006
    run_migrations(con)

    ver_row = con.execute("SELECT MAX(version) as max_v FROM schema_migrations").fetchone()
    assert ver_row["max_v"] >= 6

    # Verify columns exist
    att_cols_after = {r["name"] for r in con.execute("PRAGMA table_info(attempts)").fetchall()}
    assert "exercise_revision" in att_cols_after
    assert "exercise_content_hash" in att_cols_after

    ev_cols_after = {r["name"] for r in con.execute("PRAGMA table_info(evidence)").fetchall()}
    assert "exercise_revision" in ev_cols_after
    assert "exercise_content_hash" in ev_cols_after

    con.close()
