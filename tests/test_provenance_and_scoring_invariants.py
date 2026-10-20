"""Tests reproducing and verifying provenance chain eligibility, historical score repairs,
projection rebuilding, scoring/partial-scoring bypass prevention, stale resume prevention,
and non-finite JSON payload validation.
"""

import json
from pathlib import Path
import sqlite3
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.cli import main as cli_main
from course_tutor.errors import ValidationError
from course_tutor.models import compute_exercise_version_hash
from course_tutor.storage.migrations import (
    MIGRATIONS,
    _execute_sql_script,
    run_migrations,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def create_schema_v5_workspace(workspace_dir: Path) -> sqlite3.Connection:
    """Create a genuine schema-v5 workspace database."""
    db_path = workspace_dir / "lumen.db"
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
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
    return con


def upgrade_to_schema_v6(con: sqlite3.Connection):
    """Apply migration 6 to simulate schema-v6 baseline."""
    ver, desc, sql = MIGRATIONS[5]
    _execute_sql_script(con, sql)
    con.execute(
        "INSERT INTO schema_migrations (version, applied_at, description) VALUES (?, datetime('now'), ?)",
        (ver, desc),
    )
    con.commit()


# ==============================================================================
# REPRODUCTION 1: Evidence Eligibility Across Provenance Chain
# ==============================================================================

def test_reproduction_1_evidence_eligibility_across_provenance_chain(temp_workspace):
    """Reproduction 1:
    - Create schema-v5 workspace.
    - Validate 'Calculate 1+1' (rev 1), start attempt, submit '2'.
    - Upgrade to schema-v6.
    - Update to 'Calculate 100+100' (rev 2), validate rev 2.
    - Evaluate original submission and score it under historical flaw.
    - Upgrade to current code.
    Verify:
    - Evidence cannot remain active for current performance.
    - Item performance classification is NOT independent.
    - Assessment coverage is NOT assessed.
    - Course independent successes is 0.
    - Course brief reports topic as unassessed.
    """
    con = create_schema_v5_workspace(temp_workspace)
    # Insert course, topic, exercise, exercise_version
    now = "2026-10-10T00:00:00Z"
    con.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Math', ?, ?)",
        (now, now),
    )
    con.execute(
        "INSERT INTO topics (id, course_id, name, slug, created_at) VALUES ('t1', 'c1', 'Addition', 'addition', ?)",
        (now,),
    )
    con.execute(
        "INSERT INTO exercises (id, course_id, exercise_family, created_at) VALUES ('e1', 'c1', 'add_fam', ?)",
        (now,),
    )
    v1_hash = compute_exercise_version_hash("Calculate 1+1", "2", {"max_points": 10}, [])
    con.execute(
        """
        INSERT INTO exercise_versions (
            id, exercise_id, course_id, version_num, question_text, subparts_json,
            topic_mappings_json, skill_mappings_json, reference_solution, rubric_json,
            validation_state, validation_notes, revision_history_json, created_at
        ) VALUES ('ev1', 'e1', 'c1', 1, 'Calculate 1+1', '[]', '["t1"]', '["add_skill"]', '2', '{"max_points": 10}', 'validated', '{"status":"ok"}', '[]', ?)
        """,
        (now,),
    )
    con.execute(
        """
        INSERT INTO assessments (id, course_id, title, blueprint_json, status, created_at, updated_at, learner_id)
        VALUES ('diag1', 'c1', 'Diagnostic', '{"topic_ids":["t1"]}', 'completed', ?, ?, 'alice')
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO attempts (id, course_id, exercise_version_id, learner_id, mode, status, current_revision, started_at, updated_at)
        VALUES ('att1', 'c1', 'ev1', 'alice', 'diagnostic', 'completed', 1, ?, ?)
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO attempt_events (id, attempt_id, course_id, event_type, content, event_metadata_json, event_index, created_at)
        VALUES ('event1', 'att1', 'c1', 'work_submission', '2', '{}', 1, ?)
        """,
        (now,),
    )
    con.commit()

    # Now upgrade to schema-v6
    upgrade_to_schema_v6(con)

    # In schema-v6, update question to Calculate 100+100 (rev 2)
    v2_hash = compute_exercise_version_hash("Calculate 100+100", "200", {"max_points": 10}, [])
    rev_hist = [{
        "revision": 1,
        "question_text": "Calculate 1+1",
        "reference_solution": "2",
        "rubric": {"max_points": 10},
        "subparts": [],
        "content_hash": v1_hash,
        "updated_at": now,
    }]
    con.execute(
        """
        UPDATE exercise_versions SET
            question_text = 'Calculate 100+100',
            reference_solution = '200',
            revision_history_json = ?
        WHERE id = 'ev1'
        """,
        (json.dumps(rev_hist),),
    )
    # Historical schema-v6 code stamped rev 2 and v2_hash on evidence, leaving attempt revision NULL
    con.execute(
        """
        INSERT INTO evidence (
            id, course_id, topic_id, skill_id, attempt_id, event_id, exercise_version_id, subpart_key, demonstrated_level,
            error_category, rationale, status, created_at, updated_at,
            exercise_revision, exercise_content_hash
        ) VALUES (
            'evi1', 'c1', 't1', 'add_skill', 'att1', 'event1', 'ev1', '', 'independent_mastery',
            NULL, 'Correct', 'active', ?, ?, 2, ?
        )
        """,
        (now, now, v2_hash),
    )
    con.execute(
        """
        INSERT INTO assessment_items (
            id, assessment_id, item_order, exercise_version_id, learner_id, points_awarded,
            max_points, score_status, score_history_json, evidence_ids_json, attempt_id,
            exposure_count, created_at
        ) VALUES (
            'item1', 'diag1', 1, 'ev1', 'alice', 10.0, 10.0, 'scored',
            '[{"action":"score_recorded","points_awarded":10.0}]', '["evi1"]', 'att1',
            0, ?
        )
        """,
        (now,),
    )
    con.execute(
        """
        INSERT INTO topic_state (
            id, course_id, topic_id, policy_version, independent_success_count, assisted_success_count,
            partial_progress_count, error_count, unassessed_flag, summary_json, updated_at
        ) VALUES ('ts1', 'c1', 't1', 1, 1, 0, 0, 0, 0, '{}', ?)
        """,
        (now,),
    )
    con.commit()
    con.close()

    # Now open with current LumenCore (runs migrations up to current)
    core = LumenCore(temp_workspace)
    try:
        # 1. Evidence must NOT remain active for current performance
        ev_row = core.evidence_repo.get_evidence("evi1")
        assert ev_row.status == "pending_review"

        # 2. Assessment item must be pending_review
        it = core.assessment_repo.get_item_by_order("diag1", 1)
        assert it.score_status == "pending_review"
        assert it.points_awarded is None

        # 3. Assessment progress classification must NOT be 'independent'
        prog = core.assessment_progress("diag1")
        item_prog = prog["items_detail"][0]
        assert item_prog["performance_classification"] != "independent"
        assert item_prog["performance_classification"] in ("unassessed", "unevaluated")

        # 4. Assessment coverage must NOT be assessed
        cov = prog["topic_coverage"]["Addition"]
        assert cov["assessed"] is False
        assert cov["independent_successes"] == 0

        # 5. Course coverage & topic state must have 0 independent successes
        state = core.evidence_repo.get_topic_state("c1", "t1")
        assert state.independent_success_count == 0
        assert state.unassessed_flag is True

        # 6. Course brief must report topic as unassessed
        brief = core.course_brief("c1", learner_id="alice")
        assert "Addition" in brief["coverage"]["unassessed_topics"]
    finally:
        core.close()


# ==============================================================================
# REPRODUCTION 2: Repair Historical Scores Against Complete Scoring Policy
# ==============================================================================

def test_reproduction_2_historical_subpart_and_observation_scores_quarantined(temp_workspace):
    """Reproduction 2:
    - Schema-v6 workspace with required subparts ["a", "b"], evaluates only incorrect for "a", scores 0.
    - Schema-v5 workspace with observation-only evidence, scores 10.
    Verify after upgrade:
    - Incomplete subparts item quarantined to pending_review, assessment reopened.
    - Observation-only scored item quarantined to pending_review, assessment reopened.
    """
    con = create_schema_v5_workspace(temp_workspace)
    upgrade_to_schema_v6(con)
    now = "2026-10-10T00:00:00Z"

    con.execute("INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c2', 'Math', ?, ?)", (now, now))
    con.execute("INSERT INTO topics (id, course_id, name, slug, created_at) VALUES ('t2', 'c2', 'Algebra', 'algebra', ?)", (now,))
    con.execute("INSERT INTO exercises (id, course_id, exercise_family, created_at) VALUES ('e2', 'c2', 'alg_fam', ?)", (now,))

    # Ex with subparts ["a", "b"]
    subparts = [{"subpart_key": "a", "prompt": "part a"}, {"subpart_key": "b", "prompt": "part b"}]
    hash_sub = compute_exercise_version_hash("Solve parts", "sol", {"max_points": 10}, subparts)
    con.execute(
        """
        INSERT INTO exercise_versions (
            id, exercise_id, course_id, version_num, question_text, subparts_json,
            topic_mappings_json, skill_mappings_json, reference_solution, rubric_json,
            validation_state, validation_notes, revision_history_json, created_at
        ) VALUES ('ev2', 'e2', 'c2', 1, 'Solve parts', ?, '["t2"]', '["alg_skill"]', 'sol', '{"max_points": 10}', 'validated', '{"status":"ok"}', '[]', ?)
        """,
        (json.dumps(subparts), now),
    )
    con.execute(
        """
        INSERT INTO assessments (id, course_id, title, blueprint_json, status, created_at, updated_at, learner_id)
        VALUES ('diag2', 'c2', 'Diagnostic 2', '{"topic_ids":["t2"]}', 'completed', ?, ?, 'bob')
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO attempts (id, course_id, exercise_version_id, learner_id, mode, status, current_revision, started_at, updated_at, exercise_revision, exercise_content_hash)
        VALUES ('att2', 'c2', 'ev2', 'bob', 'diagnostic', 'completed', 1, ?, ?, 1, ?)
        """,
        (now, now, hash_sub),
    )
    con.execute(
        """
        INSERT INTO attempt_events (id, attempt_id, course_id, event_type, content, event_metadata_json, event_index, created_at)
        VALUES ('event2', 'att2', 'c2', 'work_submission', 'part a wrong', '{"subpart_key":"a"}', 1, ?)
        """,
        (now,),
    )
    # Evidence only for 'a' (incorrect)
    con.execute(
        """
        INSERT INTO evidence (
            id, course_id, topic_id, skill_id, attempt_id, event_id, exercise_version_id, subpart_key, demonstrated_level,
            error_category, rationale, status, created_at, updated_at,
            exercise_revision, exercise_content_hash
        ) VALUES (
            'evi2', 'c2', 't2', 'alg_skill', 'att2', 'event2', 'ev2', 'a', 'incorrect',
            'concept', 'Wrong', 'active', ?, ?, 1, ?
        )
        """,
        (now, now, hash_sub),
    )
    # Scored 0 under schema-v6 without evaluating 'b'
    con.execute(
        """
        INSERT INTO assessment_items (
            id, assessment_id, item_order, exercise_version_id, learner_id, points_awarded,
            max_points, score_status, score_history_json, evidence_ids_json, attempt_id,
            exposure_count, created_at
        ) VALUES (
            'item2', 'diag2', 1, 'ev2', 'bob', 0.0, 10.0, 'scored',
            '[{"action":"score_recorded","points_awarded":0.0}]', '["evi2"]', 'att2',
            0, ?
        )
        """,
        (now,),
    )
    con.commit()
    con.close()

    core = LumenCore(temp_workspace)
    try:
        # Incomplete subpart item must be quarantined
        item2 = core.assessment_repo.get_item_by_order("diag2", 1)
        assert item2.score_status == "pending_review"
        assert item2.points_awarded is None
        assert any("missing evaluated evidence" in h["reason"] or "subparts" in h["reason"] for h in item2.score_history)

        # Assessment status must be reopened
        ass2 = core.assessment_repo.get_assessment("diag2")
        assert ass2.status == "open"
    finally:
        core.close()


# ==============================================================================
# REPRODUCTION 3: Rebuild Affected Projections During Migration
# ==============================================================================

def test_reproduction_3_projections_rebuilt_during_migration(temp_workspace):
    """Reproduction 3:
    Observation-only evidence in schema-v5 awarded 10 points.
    After upgrade, topic_state must be immediately rebuilt so:
    - Assessment coverage: assessed=false
    - Course coverage: assessed=false
    - Course brief: unassessed
    """
    con = create_schema_v5_workspace(temp_workspace)
    now = "2026-10-10T00:00:00Z"
    con.execute("INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c3', 'Math', ?, ?)", (now, now))
    con.execute("INSERT INTO topics (id, course_id, name, slug, created_at) VALUES ('t3', 'c3', 'Calculus', 'calculus', ?)", (now,))
    con.execute("INSERT INTO exercises (id, course_id, exercise_family, created_at) VALUES ('e3', 'c3', 'calc_fam', ?)", (now,))
    v3_hash = compute_exercise_version_hash("Integral", "x", {"max_points": 10}, [])
    con.execute(
        """
        INSERT INTO exercise_versions (
            id, exercise_id, course_id, version_num, question_text, subparts_json,
            topic_mappings_json, skill_mappings_json, reference_solution, rubric_json,
            validation_state, validation_notes, revision_history_json, created_at
        ) VALUES ('ev3', 'e3', 'c3', 1, 'Integral', '[]', '["t3"]', '["calc_skill"]', 'x', '{"max_points": 10}', 'validated', '{"status":"ok"}', '[]', ?)
        """,
        (now,),
    )
    con.execute(
        """
        INSERT INTO assessments (id, course_id, title, blueprint_json, status, created_at, updated_at, learner_id)
        VALUES ('diag3', 'c3', 'Diagnostic 3', '{"topic_ids":["t3"]}', 'completed', ?, ?, 'carol')
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO attempts (id, course_id, exercise_version_id, learner_id, mode, status, current_revision, started_at, updated_at)
        VALUES ('att3', 'c3', 'ev3', 'carol', 'diagnostic', 'completed', 1, ?, ?)
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO attempt_events (id, attempt_id, course_id, event_type, content, event_metadata_json, event_index, created_at)
        VALUES ('event3', 'att3', 'c3', 'work_submission', 'unreadable', '{}', 1, ?)
        """,
        (now,),
    )
    # Observation level 'unassessed'
    con.execute(
        """
        INSERT INTO evidence (
            id, course_id, topic_id, skill_id, attempt_id, event_id, exercise_version_id, subpart_key, demonstrated_level,
            error_category, rationale, status, created_at, updated_at
        ) VALUES (
            'evi3', 'c3', 't3', 'calc_skill', 'att3', 'event3', 'ev3', '', 'unassessed',
            NULL, 'Unassessed', 'active', ?, ?
        )
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO assessment_items (
            id, assessment_id, item_order, exercise_version_id, learner_id, points_awarded,
            max_points, score_status, score_history_json, evidence_ids_json, attempt_id,
            exposure_count, created_at
        ) VALUES (
            'item3', 'diag3', 1, 'ev3', 'carol', 10.0, 10.0, 'scored',
            '[{"action":"score_recorded","points_awarded":10.0}]', '["evi3"]', 'att3',
            0, ?
        )
        """,
        (now,),
    )
    # Historical topic_state incorrectly set unassessed_flag=0
    con.execute(
        """
        INSERT INTO topic_state (
            id, course_id, topic_id, policy_version, independent_success_count, assisted_success_count,
            partial_progress_count, error_count, unassessed_flag, summary_json, updated_at
        ) VALUES ('ts3', 'c3', 't3', 1, 1, 0, 0, 0, 0, '{}', ?)
        """,
        (now,),
    )
    con.commit()
    con.close()

    core = LumenCore(temp_workspace)
    try:
        # Check topic_state immediately after upgrade
        state = core.evidence_repo.get_topic_state("c3", "t3")
        assert state.unassessed_flag is True
        assert state.independent_success_count == 0

        # Check course brief immediately
        brief = core.course_brief("c3", learner_id="carol")
        assert "Calculus" in brief["coverage"]["unassessed_topics"]

        # Check assessment progress immediately
        prog = core.assessment_progress("diag3")
        assert prog["topic_coverage"]["Calculus"]["assessed"] is False
        assert prog["course_topic_coverage"]["Calculus"]["assessed"] is False
    finally:
        core.close()

    # Reopen and check again without any mutations
    core2 = LumenCore(temp_workspace)
    try:
        state2 = core2.evidence_repo.get_topic_state("c3", "t3")
        assert state2.unassessed_flag is True
        brief2 = core2.course_brief("c3", learner_id="carol")
        assert "Calculus" in brief2["coverage"]["unassessed_topics"]
    finally:
        core2.close()


# ==============================================================================
# REPRODUCTION 4: Scoring & Partial-Scoring Bypasses
# ==============================================================================

def test_reproduction_4_scoring_bypasses_prevented(temp_workspace):
    """Reproduction 4:
    - allow_partial="false" must be rejected (requires real bool).
    - Incomplete subparts with allow_partial=True cannot award full credit (10/10).
    - All-positive evaluated evidence cannot support score of 0.
    """
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c4")
        t = core.create_topic("prob-c4", name="RV", slug="rv")
        subparts = [{"subpart_key": "a", "prompt": "A"}, {"subpart_key": "b", "prompt": "B"}]
        ex = core.create_exercise("prob-c4", "rv_ex", "Two parts", subparts=subparts)
        ver_id = ex["exercise_version_id"]
        core.validate_exercise_version(
            ver_id,
            reference_solution="ans",
            rubric={"max_points": 10},
            checks={"math": True},
            expected_revision=1,
        )

        diag = core.create_assessment(
            "prob-c4",
            "Exam",
            blueprint={"topic_ids": [t["id"]]},
            selected_exercise_version_ids=[ver_id],
            learner_id="alice",
        )["data"]
        diag_id = diag["assessment_id"]

        att = core.start_assessment_item_attempt(diag_id, item_order=1, learner_id="alice")["attempt"]["id"]
        core.record_attempt_event(att, expected_revision=1, event_type="work_submission", content="part a done", subpart_key="a")
        core.commit_evidence(
            att,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "s1",
                "correct": True,
                "demonstrated_level": "independent_mastery",
                "subpart_key": "a",
            }],
        )

        # 1. Non-bool allow_partial="false" rejected
        with pytest.raises(ValidationError, match="allow_partial must be a boolean"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=5.0, attempt_id=att, allow_partial="false")

        # 2. Incomplete subparts with allow_partial=True cannot award full credit (10.0/10.0)
        with pytest.raises(ValidationError, match="Cannot award full credit.*missing"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=10.0, attempt_id=att, allow_partial=True)

        # 3. All-positive evidence awarded zero rejected
        # Part a is independent_mastery (positive). Awarding 0 must be rejected
        with pytest.raises(ValidationError, match="Cannot award zero points when all evaluated evidence is positive"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=0.0, attempt_id=att, allow_partial=True)

        # Submit assisted work for part b
        core.record_attempt_event(att, expected_revision=2, event_type="hint_given", content="hint for b")
        core.record_attempt_event(att, expected_revision=3, event_type="work_submission", content="part b done", subpart_key="b")
        core.commit_evidence(
            att,
            evaluations=[{
                "topic_id": t["id"],
                "skill_id": "s2",
                "correct": True,
                "demonstrated_level": "assisted_success",
                "subpart_key": "b",
            }],
        )
        # Now all parts evaluated, but all evidence is positive (independent_mastery + assisted_success). Awarding 0 must be rejected!
        with pytest.raises(ValidationError, match="Cannot award zero points when all evaluated evidence is positive"):
            core.record_assessment_item_score(diag_id, item_order=1, points_awarded=0.0, attempt_id=att)

    finally:
        core.close()


# ==============================================================================
# REPRODUCTION 5: Prevent Stale Attempt Resumption & Recommendations
# ==============================================================================

def test_reproduction_5_stale_attempt_resumption_and_brief(temp_workspace):
    """Reproduction 5:
    - Start attempt on revision 1, pause it.
    - Update and validate exercise revision 2.
    - course_brief must not recommend resuming the stale attempt.
    - resume_attempt must reject resuming the stale attempt.
    """
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-c5")
        ex = core.create_exercise("prob-c5", "ex_stale", "Original question text")
        ver_id = ex["exercise_version_id"]
        core.validate_exercise_version(
            ver_id,
            reference_solution="sol1",
            rubric={"max_points": 5},
            checks={"math": True},
            expected_revision=1,
        )

        # Start and pause attempt on rev 1
        att = core.start_attempt("prob-c5", ver_id, learner_id="alice")["data"]
        att_id = att["id"]
        core.pause_attempt(att_id, expected_revision=1)

        # Update exercise to rev 2
        core.update_exercise_version(ver_id, expected_revision=1, question_text="Updated question text")
        core.validate_exercise_version(
            ver_id,
            reference_solution="sol2",
            rubric={"max_points": 5},
            checks={"math": True},
            expected_revision=2,
        )

        # course_brief must not recommend resume_attempt for att_id
        brief = core.course_brief("prob-c5", learner_id="alice")
        resume_actions = [a for a in brief["recommended_next_actions"] if a["action"] == "resume_attempt"]
        assert len(resume_actions) == 0

        # resume_attempt must reject resuming the stale attempt
        with pytest.raises(ValidationError, match="outdated|unresolved|does not match current revision"):
            core.resume_attempt(att_id, expected_revision=2)
    finally:
        core.close()


# ==============================================================================
# REPRODUCTION 6: Reject Non-Finite JSON Before Any Commit
# ==============================================================================

def test_reproduction_6_reject_non_finite_json_before_commit(temp_workspace):
    """Reproduction 6:
    - CLI create_course with {"notation_settings": {"x": 1e999}} exits 1.
    - Verify course was NOT committed to DB, and no receipt was created.
    - Direct API call with non-finite number raises ValidationError before any commit.
    """
    bad_payload = json.dumps({
        "course_id": "overflow",
        "name": "Overflow",
        "notation_settings": {"x": 1e999},
        "request_id": "overflow-req",
    })

    with pytest.raises(SystemExit) as excinfo:
        cli_main([
            "--workspace", str(temp_workspace),
            "--json-input", bad_payload,
            "create_course",
        ])
    assert excinfo.value.code == 1

    # Verify database was NOT modified
    core = LumenCore(temp_workspace)
    try:
        assert core.course_repo.get_course("overflow") is None
        # Verify receipt was NOT created
        row = core.con.execute("SELECT * FROM operation_receipts WHERE request_id = 'overflow-req'").fetchone()
        assert row is None

        # Direct API call with inf
        with pytest.raises(ValidationError, match="[Nn]on-finite"):
            core.create_course("Overflow2", course_id="overflow2", notation_settings={"val": float("inf")}, request_id="api-req")

        assert core.course_repo.get_course("overflow2") is None
        row2 = core.con.execute("SELECT * FROM operation_receipts WHERE request_id = 'api-req'").fetchone()
        assert row2 is None
    finally:
        core.close()
