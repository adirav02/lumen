"""Measurement accounting must preserve missing data, retries and failures."""

import json
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

import pytest

from course_tutor.errors import ValidationError
from course_tutor.usage import record_usage, summarize_usage


def call(event_id="call-1", **changes):
    return {"kind": "call", "event_id": event_id, "run_id": "run-1", "task_id": "task-1",
            "host": "test", "provider": "fixture", "model": "synthetic",
            "status": "completed", "usage_source": "provider_reported",
            "input_tokens": 100, "output_tokens": 30, "cached_input_tokens": 20,
            "image_count": 1, "latency_ms": 100, "retry_of": None,
            "cost_usd": 0.01, "cost_source": "billed", "source_note": "Synthetic test values, not real billing", **changes}


def task(event_id="task-result", **changes):
    return {"kind": "task", "event_id": event_id, "run_id": "run-1", "task_id": "task-1",
            "outcome": "correct", "reviewer_reference": "fixture:checked-reference",
            "source_note": "Synthetic reviewed outcome", **changes}


def finish(**changes):
    return {"kind": "run", "event_id": "finished", "run_id": "run-1",
            "collection_status": "complete", "source_note": "All fixture calls included", **changes}


def test_cost_per_correct_includes_failed_tasks_retries_and_images(tmp_path):
    path = tmp_path / "usage.jsonl"
    rows = [call(status="failed"), call("retry", retry_of="call-1", cost_usd=0.02),
            call("wrong", task_id="task-2", cost_usd=0.03), task(),
            task("wrong-result", task_id="task-2", outcome="incorrect"), finish()]
    for row in rows:
        record_usage(path, row)
    summary = summarize_usage(path)["runs"][0]
    assert summary["calls"] == 3 and summary["retries"] == 1
    assert summary["failed_or_interrupted_calls"] == 1
    assert summary["incorrect_tasks"] == summary["correct_tasks"] == 1
    assert summary["known_billed_cost_usd"] == "0.06"
    assert summary["billed_cost_per_correct_task_usd"] == "0.06"
    group = summary["usage_groups"][0]
    assert group["input_tokens_known_sum"] == 300  # cache is not added twice
    assert group["image_count_known_sum"] == 3


def test_missing_and_estimated_data_cannot_become_billed_totals(tmp_path):
    path = tmp_path / "usage.jsonl"
    record_usage(path, call(usage_source="unavailable", input_tokens=None, output_tokens=None,
                            cached_input_tokens=None, image_count=None, cost_usd=None, cost_source="unavailable"))
    record_usage(path, call("estimate", usage_source="estimated", cost_source="estimated"))
    record_usage(path, task())
    record_usage(path, finish())
    summary = summarize_usage(path)["runs"][0]
    assert summary["unknown_cost_calls"] == 1
    assert summary["billed_cost_per_correct_task_usd"] is None
    assert len(summary["usage_groups"]) == 2
    assert summary["usage_groups"][0]["input_tokens_unknown_calls"] == 1
    assert summary["known_estimated_cost_usd"] == "0.01"


def test_outcome_corrections_reopen_complete_collection(tmp_path):
    path = tmp_path / "usage.jsonl"
    for row in [call(), task(), finish(), task("correction", outcome="incorrect")]:
        record_usage(path, row)
    result = summarize_usage(path)["runs"][0]
    assert result["correct_tasks"] == 0 and result["collection_status"] == "partial"
    assert result["billed_cost_per_correct_task_usd"] is None
    assert len(path.read_text().splitlines()) == 4


def test_pending_and_unrecorded_tasks_suppress_metric(tmp_path):
    path = tmp_path / "usage.jsonl"
    for row in [call(), task(), call("no-outcome", task_id="unknown"), finish()]:
        record_usage(path, row)
    assert summarize_usage(path)["runs"][0]["pending_tasks"] == 1
    assert summarize_usage(path)["runs"][0]["billed_cost_per_correct_task_usd"] is None


@pytest.mark.parametrize("change", [
    {"input_tokens": True}, {"input_tokens": -1}, {"output_tokens": 2.5},
    {"cost_usd": float("nan")}, {"cost_usd": float("inf")}, {"cost_usd": True},
    {"cost_usd": -0.01}, {"cost_source": "unavailable"}, {"cost_usd": None},
    {"cached_input_tokens": 101}, {"usage_source": "unavailable"},
    {"retry_of": "missing"}, {"model": ""}, {"extra": "unexpected"},
])
def test_invalid_usage_does_not_append(tmp_path, change):
    path = tmp_path / "usage.jsonl"
    record_usage(path, call())
    before = path.read_bytes()
    with pytest.raises(ValidationError):
        record_usage(path, call("invalid", **change))
    assert path.read_bytes() == before


def test_retry_must_stay_within_task_and_run(tmp_path):
    path = tmp_path / "usage.jsonl"
    record_usage(path, call())
    for changes in [{"task_id": "other"}, {"run_id": "other"}]:
        with pytest.raises(ValidationError, match="same run and task"):
            record_usage(path, call("retry", retry_of="call-1", **changes))


def test_idempotency_and_concurrent_processes(tmp_path):
    path = tmp_path / "usage.jsonl"
    def invoke(_):
        result = subprocess.run([sys.executable, "-m", "course_tutor.cli", "record-usage", "-w", str(tmp_path),
                                 "-j", json.dumps(call())], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)["data"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(invoke, range(6)))
    assert sum(not r["replayed"] for r in results) == 1
    assert len(path.read_text().splitlines()) == 1
    with pytest.raises(ValidationError, match="different usage"):
        record_usage(path, call(cost_usd=5))


def test_truncated_log_is_never_silently_ignored(tmp_path):
    path = tmp_path / "usage.jsonl"
    record_usage(path, call())
    with path.open("a") as stream:
        stream.write('{"incomplete":')
    before = path.read_bytes()
    with pytest.raises(ValidationError, match="line 2"):
        record_usage(path, call("new"))
    with pytest.raises(ValidationError, match="line 2"):
        summarize_usage(path)
    assert path.read_bytes() == before


def test_cli_usage_roundtrip_without_learner_database(tmp_path):
    def cli(op, payload):
        result = subprocess.run([sys.executable, "-m", "course_tutor.cli", op, "-w", str(tmp_path),
                                 "-j", json.dumps(payload)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)["data"]
    assert cli("usage-summary", {})["events"] == 0
    assert cli("record-usage", call())["replayed"] is False
    assert cli("record-usage", call())["replayed"] is True
    assert cli("usage-summary", {"run_id": "run-1"})["runs"][0]["calls"] == 1
    assert cli("usage-summary", {"run_id": "other"})["runs"] == []
    assert not (tmp_path / "lumen.db").exists()
