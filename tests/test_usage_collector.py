"""Automatic measurement uses observed session totals without fabricating calls."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import pytest

from course_tutor.errors import ValidationError
from course_tutor.usage import record_usage, summarize_usage
from course_tutor.usage_collector import collect_usage, read_codex_snapshot, watch_usage


def event(inputs=100, outputs=20, timestamp="2026-10-19T00:01:00Z", **changes):
    return {"timestamp": timestamp, "type": "event_msg", "payload": {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": inputs, "output_tokens": outputs,
                              "cached_input_tokens": 80, "reasoning_output_tokens": 5, **changes},
        # The 'last' value is not a second charge to add to cumulative totals.
        "last_token_usage": {"input_tokens": 50, "output_tokens": 10}}}}


def fixture(tmp_path, *, cwd=None, session="session-1", rows=None, name="rollout-test.jsonl"):
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    home = tmp_path / "codex"
    directory = home / "sessions/2026/10/19"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    data = [{"type": "session_meta", "payload": {"id": session, "cwd": str(cwd or project), "model_provider": "openai"}},
            {"type": "turn_context", "payload": {"model": "fixture-model"}},
            {"type": "response_item", "payload": {"content": "PRIVATE learner text must never enter the ledger"}}]
    path.write_text("".join(json.dumps(row)+"\n" for row in data + (rows if rows is not None else [event()])))
    return path, project, home, tmp_path / "measurements/usage.jsonl"


def test_collects_actual_totals_and_is_idempotent(tmp_path):
    path, project, home, log = fixture(tmp_path)
    first = collect_usage(log, project, codex_home=home)
    second = collect_usage(log, project, codex_home=home)
    assert first["snapshots_appended"] == second["snapshots_replayed"] == 1
    assert second["snapshots_appended"] == 0
    run = summarize_usage(log)["runs"][0]
    snap = run["session_snapshots"][0]
    assert snap["input_tokens"] == 100 and snap["cached_input_tokens"] == 80
    assert snap["output_tokens"] == 20 and snap["reasoning_output_tokens"] == 5
    assert snap["models"] == ["fixture-model"]
    assert run["calls"] == 0 and run["billed_cost_per_correct_task_usd"] is None
    assert run["collection_status"] == "partial"
    assert "PRIVATE" not in log.read_text()
    assert not (project / "lumen.db").exists()


def test_refresh_replaces_cumulative_totals_instead_of_adding(tmp_path):
    path, project, home, log = fixture(tmp_path)
    collect_usage(log, project, codex_home=home)
    with path.open("a") as stream:
        stream.write(json.dumps(event(160, 30, "2026-10-19T00:02:00Z"))+"\n")
        stream.write(json.dumps(event(160, 30, "2026-10-19T00:02:00Z"))+"\n")
    collect_usage(log, project, codex_home=home)
    result = summarize_usage(log)
    assert result["events"] == 2
    assert len(result["runs"][0]["session_snapshots"]) == 1
    assert result["runs"][0]["session_snapshots"][0]["input_tokens"] == 160
    assert result["runs"][0]["usage_groups"] == []


def test_session_snapshot_cannot_establish_per_call_completeness(tmp_path):
    _, project, home, log = fixture(tmp_path)
    collect_usage(log, project, codex_home=home)
    record_usage(log, {"event_id": "claimed-complete", "run_id": "codex-session:session-1", "kind": "run",
                       "collection_status": "complete", "source_note": "Test that a declaration cannot fill missing per-call evidence."})
    report = summarize_usage(log)["runs"][0]
    assert report["collection_status"] == "partial"
    assert report["billed_cost_per_correct_task_usd"] is None


def test_other_projects_are_excluded_before_body_is_parsed(tmp_path):
    path, project, home, log = fixture(tmp_path, cwd=tmp_path / "unrelated")
    with path.open("a") as stream:
        stream.write("PRIVATE malformed content must not be inspected\n")
    result = collect_usage(log, project, codex_home=home)
    assert result["snapshots_appended"] == 0 and result["errors"] == []
    assert not log.exists()


def test_empty_or_missing_telemetry_is_explicit(tmp_path):
    _, project, home, log = fixture(tmp_path, rows=[{"type": "event_msg", "payload": {"type": "token_count", "info": None}}])
    result = collect_usage(log, project, codex_home=home)
    assert result["sessions_with_usage"] == 0 and result["collection_status"] == "unavailable"
    assert not log.exists()
    assert collect_usage(log, project, codex_home=tmp_path / "absent")["files_scanned"] == 0


def test_incomplete_final_line_is_deferred_but_corruption_is_reported(tmp_path):
    path, project, home, log = fixture(tmp_path)
    with path.open("a") as stream:
        stream.write('{"payload":')
    result = collect_usage(log, project, codex_home=home)
    assert result["pending_tails"] == result["snapshots_appended"] == 1
    with path.open("a") as stream:
        stream.write(" PRIVATE data\n")
    result = collect_usage(log, project, codex_home=home)
    assert result["snapshots_appended"] == 0
    assert len(result["errors"]) == 1 and "PRIVATE" not in str(result)


@pytest.mark.parametrize("changes", [
    {"input_tokens": True}, {"input_tokens": -2}, {"output_tokens": 2.5},
    {"cached_input_tokens": 101}, {"reasoning_output_tokens": 21},
    {"reasoning_output_tokens": float("nan")},
])
def test_invalid_host_counters_do_not_become_measurements(tmp_path, changes):
    row = event()
    row["payload"]["info"]["total_token_usage"].update(changes)
    _, project, home, log = fixture(tmp_path, rows=[row])
    result = collect_usage(log, project, codex_home=home)
    assert len(result["errors"]) == 1 and result["snapshots_appended"] == 0
    assert not log.exists()


def test_mixed_models_and_missing_optional_counters_remain_honest(tmp_path):
    row = event()
    totals = row["payload"]["info"]["total_token_usage"]
    del totals["cached_input_tokens"], totals["reasoning_output_tokens"]
    path, project, home, log = fixture(tmp_path, rows=[{"type": "turn_context", "payload": {"model": "another-model"}}, row])
    collect_usage(log, project, codex_home=home)
    snap = summarize_usage(log)["runs"][0]["session_snapshots"][0]
    assert snap["models"] == ["another-model", "fixture-model"]
    assert snap["cached_input_tokens"] is snap["reasoning_output_tokens"] is None


def test_rotated_session_copies_and_forks_are_not_pooled(tmp_path):
    path, project, home, log = fixture(tmp_path)
    fixture(tmp_path, rows=[event(150, timestamp="2026-10-19T00:03:00Z")], name="rollout-copy.jsonl")
    fixture(tmp_path, session="fork", name="rollout-fork.jsonl")
    result = collect_usage(log, project, codex_home=home)
    assert result["sessions_with_usage"] == 2
    runs = summarize_usage(log)["runs"]
    assert len(runs) == 2
    original = next(run for run in runs if run["run_id"].endswith("session-1"))
    assert original["session_snapshots"][0]["input_tokens"] == 150
    assert "input_tokens_known_sum" not in summarize_usage(log)


def test_parallel_collectors_append_snapshot_once(tmp_path):
    _, project, home, log = fixture(tmp_path)
    def collect(_):
        return collect_usage(log, project, codex_home=home)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(collect, range(6)))
    assert sum(r["snapshots_appended"] for r in results) == 1
    assert summarize_usage(log)["events"] == 1


def test_watch_automatically_collects_new_host_data(tmp_path, watcher_clock):
    path, project, home, log = fixture(tmp_path)
    output = []
    emitted_at = []
    def capture(result):
        output.append(result)
        emitted_at.append(watcher_clock.monotonic())
        if len(output) == 1:
            with path.open("a") as stream:
                stream.write(json.dumps(event(200, timestamp="2026-10-19T00:05:00Z"))+"\n")
    result = watch_usage(log, project, hosts=["codex"], codex_home=home, duration_seconds=.15, poll_seconds=.05, emit=capture)
    assert result == {"stopped": "duration", "log_path": str(log)}
    assert len(output) == 2
    assert emitted_at == pytest.approx([0, .05])
    assert watcher_clock.sleeps == pytest.approx([.05, .05, .05])
    assert watcher_clock.elapsed == pytest.approx(.15)
    for emitted, events, inputs in zip(output, (1, 2), (100, 200)):
        data = emitted["data"]
        assert data["collector"]["sessions_with_usage"] == 1
        assert data["collector"]["snapshots_appended"] == 1
        assert data["summary"]["events"] == events
        run, = data["summary"]["runs"]
        assert run["run_id"] == "codex-session:session-1"
        snapshot, = run["session_snapshots"]
        assert snapshot["host"] == "codex"
        assert snapshot["session_id"] == "session-1"
        assert snapshot["input_tokens"] == inputs
    assert summarize_usage(log) == output[-1]["data"]["summary"]
    for invalid in (None, True, float("nan"), 0, 31):
        with pytest.raises(ValidationError):
            watch_usage(log, project, poll_seconds=invalid)


def test_watch_duration_includes_emit_time(tmp_path, watcher_clock):
    _, project, home, log = fixture(tmp_path)
    output = []
    def slow_emit(result):
        output.append(result)
        watcher_clock.elapsed += .2  # work exhausts the original .15 budget
    result = watch_usage(log, project, hosts=["codex"], codex_home=home,
                         duration_seconds=.15, poll_seconds=.05, emit=slow_emit)
    assert result == {"stopped": "duration", "log_path": str(log)}
    assert len(output) == 1
    assert output[0]["data"]["summary"]["events"] == 1
    assert watcher_clock.sleeps == []


def test_cli_collection_and_bounded_watch(tmp_path):
    _, project, home, log = fixture(tmp_path)
    for operation in ("collect-usage", "watch-usage"):
        result = subprocess.run([sys.executable, "-m", "course_tutor.cli", operation, "-w", str(log.parent), "-j", json.dumps({
            "project_path": str(project), "codex_home": str(home), "duration_seconds": .05, "poll_seconds": .05})],
            text=True, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
        assert all(json.loads(line)["status"] == "success" for line in result.stdout.splitlines())
    assert summarize_usage(log)["events"] == 1
