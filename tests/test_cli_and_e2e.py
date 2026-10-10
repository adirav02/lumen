"""End-to-end slice and structured JSON CLI integration tests."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def run_cli(*args: str, input_str: str = "") -> tuple[int, dict]:
    """Execute lumen CLI subprocess and parse JSON stdout."""
    cmd = [sys.executable, "-m", "course_tutor.cli", *args]
    proc = subprocess.run(
        cmd,
        input=input_str,
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"raw_stdout": proc.stdout, "raw_stderr": proc.stderr}
    return proc.returncode, data


def test_cli_capabilities():
    """Verify capabilities output via CLI."""
    code, res = run_cli("capabilities")
    assert code == 0
    assert res["status"] == "success"
    assert res["data"]["contract_version"] == "1.0.0"
    assert res["data"]["runtime"]["fts5_supported"] is True


def test_cli_error_envelopes(temp_workspace):
    """Verify machine-readable error envelopes and exit codes."""
    ws = str(temp_workspace)

    # 1. Unknown operation
    code, res = run_cli("unknown-op", "--workspace", ws)
    assert code == 1
    assert res["status"] == "error"
    assert res["error_code"] == "UNKNOWN_OPERATION"

    # 2. Course not found
    code, res = run_cli("course-brief", "--workspace", ws, "-c", "nonexistent-course")
    assert code == 1
    assert res["status"] == "error"
    assert res["error_code"] == "COURSE_NOT_FOUND"

    # 3. Invalid JSON input
    code, res = run_cli("create-course", "--workspace", ws, "-j", "not-valid-json{")
    assert code == 1
    assert res["status"] == "error"
    assert res["error_code"] == "INVALID_JSON_INPUT"


def test_cli_complete_e2e_workflow(temp_workspace):
    """Full end-to-end slice via structured CLI:

    course creation -> source ingestion -> retrieval with provenance -> learner attempt ->
    recorded evidence -> updated course brief -> session reopening.
    """
    ws = str(temp_workspace)

    # 1. Create Course
    create_payload = json.dumps({
        "name": "Probability Theory",
        "scope": "Undergraduate STEM",
        "default_language": "en",
    })
    code, res = run_cli("create-course", "--workspace", ws, "-c", "prob-e2e", "-j", create_payload)
    assert code == 0
    assert res["status"] == "success"
    assert res["data"]["name"] == "Probability Theory"

    # 2. Ingest Source Material
    lecture_file = temp_workspace / "bayes_lecture.txt"
    lecture_file.write_text(
        """
### Theorem: Bayes Rule
Content: P(A|B) = P(B|A) * P(A) / P(B)
Assumptions: P(B) > 0
Symbols: P(A|B) = posterior probability; P(A) = prior probability
Exceptions: Undefined when P(B) = 0
""",
        encoding="utf-8",
    )
    ingest_payload = json.dumps({
        "file_path": str(lecture_file),
        "logical_name": "bayes_lecture",
        "role": "lecture",
    })
    code, res = run_cli("ingest-source", "--workspace", ws, "-c", "prob-e2e", "-j", ingest_payload)
    assert code == 0
    assert res["status"] == "success"
    unit_id = res["data"]["units"][0]["id"]
    assert unit_id is not None

    # 3. Search & Read with Provenance
    code, res = run_cli("search", "--workspace", ws, "-c", "prob-e2e", "-q", "Bayes Rule")
    assert code == 0
    assert res["status"] == "success"
    assert res["data"]["results_count"] >= 1
    assert res["data"]["results"][0]["title"] == "Bayes Rule"
    assert "bayes_lecture.txt" in res["data"]["results"][0]["provenance"][0]

    read_payload = json.dumps({"unit_ids": [unit_id]})
    code, res = run_cli("read-units", "--workspace", ws, "-c", "prob-e2e", "-j", read_payload)
    assert code == 0
    assert res["data"]["units"][0]["assumptions"] == ["P(B) > 0"]

    # 4. Create Exercise and Topic
    topic_payload = json.dumps({"name": "Bayesian Inference", "slug": "bayes-inf"})
    code, t_res = run_cli("create-topic", "--workspace", ws, "-c", "prob-e2e", "-j", topic_payload)
    topic_id = t_res["data"]["id"]

    ex_payload = json.dumps({
        "exercise_family": "bayes_application_family",
        "question_text": "Calculate posterior probability given prior=0.1, sensitivity=0.9, specificity=0.9.",
        "topic_mappings": ["bayes-inf"],
        "skill_mappings": ["posterior_calc"],
        "reference_solution": "P(D|+) = 0.5",
    })
    code, ex_res = run_cli("create-exercise", "--workspace", ws, "-c", "prob-e2e", "-j", ex_payload)
    ex_ver_id = ex_res["data"]["exercise_version_id"]

    # 5. Learner Attempt
    att_payload = json.dumps({
        "exercise_version_id": ex_ver_id,
        "learner_id": "student_alice",
        "mode": "practice",
    })
    code, att_res = run_cli("start-attempt", "--workspace", ws, "-c", "prob-e2e", "-j", att_payload)
    assert code == 0
    att_id = att_res["data"]["id"]

    # Record event: learner requests hint
    hint_req = json.dumps({
        "attempt_id": att_id,
        "expected_revision": 1,
        "event_type": "hint_request",
    })
    code, _ = run_cli("record-attempt-event", "--workspace", ws, "-j", hint_req)
    assert code == 0

    hint_given = json.dumps({
        "attempt_id": att_id,
        "expected_revision": 2,
        "event_type": "hint_given",
        "content": "Recall P(B) = P(B|A)P(A) + P(B|A^c)P(A^c).",
    })
    code, _ = run_cli("record-attempt-event", "--workspace", ws, "-j", hint_given)
    assert code == 0

    # Record event: learner submits correct answer
    work_sub = json.dumps({
        "attempt_id": att_id,
        "expected_revision": 3,
        "event_type": "work_submission",
        "content": "P(D|+) = (0.9*0.1) / (0.9*0.1 + 0.1*0.9) = 0.5",
    })
    code, _ = run_cli("record-attempt-event", "--workspace", ws, "-j", work_sub)
    assert code == 0

    # 6. Commit Evidence (assisted success due to prior hint)
    commit_payload = json.dumps({
        "attempt_id": att_id,
        "evaluations": [{
            "subpart_key": "default",
            "topic_id": topic_id,
            "skill_id": "posterior_calc",
            "correct": True,
            "rationale": "Correct application after denominator hint.",
        }],
        "complete_attempt": True,
    })
    code, commit_res = run_cli("commit-evidence", "--workspace", ws, "-j", commit_payload)
    assert code == 0
    ev = commit_res["data"]["evidence_created"][0]
    assert ev["demonstrated_level"] == "assisted_success"

    # 7. Course Brief verification
    code, brief_res = run_cli("course-brief", "--workspace", ws, "-c", "prob-e2e", "-j", '{"learner_id": "student_alice"}')
    assert code == 0
    brief = brief_res["data"]
    assert brief["course"]["name"] == "Probability Theory"
    assert brief["coverage"]["assessed_topics_count"] == 1
    assert brief["coverage"]["assessed_topics"][0]["assisted"] == 1

    # 8. Reopening from new session: verify persisted state
    code, reopen_brief = run_cli("course-brief", "--workspace", ws, "-c", "prob-e2e", "-j", '{"learner_id": "student_alice"}')
    assert code == 0
    assert reopen_brief["data"]["coverage"]["assessed_topics"][0]["assisted"] == 1
