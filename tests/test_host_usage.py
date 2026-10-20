"""Native usage adapters: accounting scope, privacy, setup and real CLI plumbing."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from course_tutor.errors import ValidationError
from course_tutor.host_usage import capture_antigravity_result, capture_statusline, configure_usage, read_claude_snapshot
from course_tutor.usage import summarize_usage
from course_tutor.usage_collector import collect_usage, watch_usage


def claude_file(root, project, name="session-1", child=False):
    directory = root/"projects"/str(project).replace("/", "-")
    if child:
        directory = directory/"parent-session/subagents"
    directory.mkdir(parents=True, exist_ok=True)
    return directory/(name+".jsonl")


def message(project, mid="m1", output=20, **usage):
    return {"type": "assistant", "cwd": str(project), "timestamp": "2026-10-19T00:01:00Z",
            "message": {"id": mid, "model": "claude-fixture", "content": "PRIVATE actual work",
                        "usage": {"input_tokens": 10, "output_tokens": output,
                                  "cache_creation_input_tokens": 30, "cache_read_input_tokens": 100, **usage}}}


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row)+"\n" for row in rows))


def status(project, host="claude", **changes):
    return {"cwd": str(project), "workspace": {"project_dir": str(project)},
            "session_id": "session-1", "conversation_id": "session-1", "model": {"id": "fixture-model"},
            "context_window": {"total_input_tokens": 300, "total_output_tokens": 50},
            "cost": {"total_cost_usd": .04, "total_duration_ms": 1000}, **changes}


def test_claude_stream_fragments_cache_and_distinct_messages(tmp_path):
    path = claude_file(tmp_path/"claude", tmp_path)
    write_rows(path, [message(tmp_path, output=1), message(tmp_path), message(tmp_path, mid="m2", output=30)])
    snap, pending = read_claude_snapshot(path, tmp_path)
    assert not pending
    assert snap["input_tokens"] == 280  # both requests include uncached+write+read
    assert snap["cached_input_tokens"] == 200
    assert snap["output_tokens"] == 50  # final m1 count replaces its fragment
    assert snap["usage_scope"] == "transcript_messages"
    assert "PRIVATE" not in json.dumps(snap)


def test_missing_cache_counts_do_not_silently_become_zero(tmp_path):
    row = message(tmp_path)
    del row["message"]["usage"]["cache_read_input_tokens"]
    path = claude_file(tmp_path/"claude", tmp_path)
    write_rows(path, [row])
    snap, _ = read_claude_snapshot(path, tmp_path)
    assert snap["input_tokens"] is snap["cached_input_tokens"] is None
    assert snap["reported_usage"]["uncached_input_tokens"] == 10


def test_claude_filter_errors_and_incomplete_tail(tmp_path):
    path = claude_file(tmp_path/"claude", tmp_path)
    write_rows(path, [message(tmp_path/"other")])
    with path.open("a") as stream:
        stream.write("PRIVATE malformed body\n")
    assert read_claude_snapshot(path, tmp_path) == (None, False)
    write_rows(path, [message(tmp_path), {**message(tmp_path, "error"), "isApiErrorMessage": True}])
    with path.open("a") as stream:
        stream.write('{"unfinished":')
    snap, pending = read_claude_snapshot(path, tmp_path)
    assert pending and snap["output_tokens"] == 20
    with path.open("a") as stream:
        stream.write(" private-data\n")
    with pytest.raises(ValidationError, match="Invalid Claude JSON"):
        read_claude_snapshot(path, tmp_path)


def test_claude_discovery_child_identity_and_repeat_collection(tmp_path):
    home = tmp_path/"claude"
    write_rows(claude_file(home, tmp_path), [message(tmp_path)])
    write_rows(claude_file(home, tmp_path, "agent-1", child=True), [message(tmp_path)])
    log = tmp_path/"usage.jsonl"
    first = collect_usage(log, tmp_path, hosts=["claude"], claude_home=home)
    second = collect_usage(log, tmp_path, hosts=["claude"], claude_home=home)
    assert first["snapshots_appended"] == 2 and second["snapshots_appended"] == 0
    assert len(summarize_usage(log)["runs"]) == 2
    assert not (tmp_path/"lumen.db").exists()


@pytest.mark.parametrize("host", ["claude", "antigravity"])
def test_native_statusline_scope_cost_replay_and_filter(tmp_path, host):
    log = tmp_path/"usage.jsonl"
    payload = status(tmp_path, host)
    first = capture_statusline(log, tmp_path, host, payload)
    second = capture_statusline(log, tmp_path, host, payload)
    assert first["replayed"] is False and second["replayed"] is True
    snap = first["event"]
    assert snap["usage_scope"] == "context_window" and snap["estimated_cost_usd"] == .04
    assert snap["cached_input_tokens"] is None
    assert summarize_usage(log)["runs"][0]["billed_cost_per_correct_task_usd"] is None
    assert capture_statusline(log, tmp_path/"other", host, payload) is None


def test_claude_statusline_uses_full_transcript_when_available(tmp_path):
    path = claude_file(tmp_path/"claude", tmp_path)
    write_rows(path, [message(tmp_path), message(tmp_path, "m2")])
    result = capture_statusline(tmp_path/"usage.jsonl", tmp_path, "claude", status(tmp_path, transcript_path=str(path)))
    assert result["event"]["usage_scope"] == "transcript_messages"
    assert result["event"]["input_tokens"] == 280
    assert result["event"]["estimated_cost_usd"] == .04


def test_antigravity_cumulative_result_does_not_guess_cache_basis(tmp_path):
    init = {"cwd": str(tmp_path), "conversation_id": "ag-1", "model": "fixture-model"}
    result = {"conversation_id": "ag-1", "status": "SUCCESS", "response": "PRIVATE response",
              "usage": {"input_tokens": 5, "output_tokens": 8, "thinking_tokens": 2, "cache_read_tokens": 100, "total_tokens": 13}}
    log = tmp_path/"usage.jsonl"
    first = capture_antigravity_result(log, tmp_path, result, init)
    assert first["event"]["input_tokens"] is None
    assert first["event"]["reported_usage"]["cache_read_tokens"] == 100
    assert first["event"]["output_tokens"] == 8
    assert "PRIVATE" not in log.read_text()
    assert capture_antigravity_result(log, tmp_path, result, init)["replayed"]
    with pytest.raises(ValidationError):
        capture_antigravity_result(log, tmp_path, {**result, "conversation_id": "other"}, init)
    with pytest.raises(ValidationError):
        capture_antigravity_result(log, tmp_path/"other", result, init)


def test_context_snapshot_cannot_hide_cumulative_conversation_usage(tmp_path):
    log = tmp_path/"usage.jsonl"
    init = {"cwd": str(tmp_path), "conversation_id": "session-1"}
    result = {"conversation_id": "session-1", "status": "ERROR", "usage": {
        "input_tokens": 100, "output_tokens": 20, "thinking_tokens": 3, "cache_read_tokens": 0, "total_tokens": 120}}
    capture_antigravity_result(log, tmp_path, result, init)
    capture_statusline(log, tmp_path, "antigravity", status(tmp_path))
    snapshots = summarize_usage(log)["runs"][0]["session_snapshots"]
    assert {s["usage_scope"] for s in snapshots} == {"conversation", "context_window"}
    assert next(s for s in snapshots if s["usage_scope"] == "conversation")["terminal_status"] == "ERROR"


@pytest.mark.parametrize("counter", [True, -1, 2.5, float("nan")])
def test_invalid_native_counters_never_append(tmp_path, counter):
    with pytest.raises(ValidationError):
        capture_statusline(tmp_path/"usage.jsonl", tmp_path, "antigravity", status(tmp_path, context_window={"total_input_tokens": counter}))
    assert not (tmp_path/"usage.jsonl").exists()


def test_settings_preserve_display_and_other_keys_and_backup(tmp_path):
    project = tmp_path/"project with spaces"
    home = tmp_path/"agy-home"
    home.mkdir()
    original = '{"other":{"preserve":true},"statusLine":{"type":"command","command":"printf existing","padding":2}}\n'
    (home/"settings.json").write_text(original)
    result = configure_usage(project, tmp_path/"usage.jsonl", hosts=["antigravity"], antigravity_home=home)
    setting = json.loads((home/"settings.json").read_text())
    assert setting["other"] == {"preserve": True}
    assert setting["statusLine"]["padding"] == 2
    command = shlex.split(setting["statusLine"]["command"])
    assert command[command.index("--project")+1] == str(project)
    assert command[-2:] == ["--previous-command", "printf existing"]
    assert Path(result["configured"][0]["backup_path"]).read_text() == original
    assert not configure_usage(project, tmp_path/"usage.jsonl", hosts=["antigravity"], antigravity_home=home)["configured"][0]["changed"]


def test_claude_local_setup_preserves_inherited_global_display(tmp_path):
    home = tmp_path/"claude-home"
    home.mkdir()
    (home/"settings.json").write_text('{"statusLine":{"command":"printf inherited"},"other":1}')
    configure_usage(tmp_path/"project", tmp_path/"usage.jsonl", hosts=["claude"], claude_home=home)
    settings = json.loads((tmp_path/"project/.claude/settings.local.json").read_text())
    assert "inherited" in settings["statusLine"]["command"]
    assert json.loads((home/"settings.json").read_text())["other"] == 1


def test_corrupt_settings_are_never_replaced(tmp_path):
    home = tmp_path/"agy"
    home.mkdir()
    path = home/"settings.json"
    path.write_text("invalid PRIVATE config")
    with pytest.raises(ValidationError):
        configure_usage(tmp_path, tmp_path/"usage.jsonl", hosts=["antigravity"], antigravity_home=home)
    assert path.read_text() == "invalid PRIVATE config"


def test_default_antigravity_settings_and_concurrent_setup(tmp_path):
    home = tmp_path/"agy"
    home.mkdir()
    (home/"settings.json").write_text('{"statusLine":{"type":"","command":"","enabled":true}}')
    def setup(_):
        return configure_usage(tmp_path, tmp_path/"usage.jsonl", hosts=["antigravity"], antigravity_home=home)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(setup, range(5)))
    assert sum(result["configured"][0]["changed"] for result in results) == 1
    assert json.loads((home/"settings.json").read_text())["statusLine"]["type"] == "command"


def test_setup_does_not_reactivate_a_disabled_previous_script(tmp_path):
    home = tmp_path/"agy"
    home.mkdir()
    (home/"settings.json").write_text('{"statusLine":{"type":"command","command":"printf disabled-private-script","enabled":false}}')
    configure_usage(tmp_path, tmp_path/"usage.jsonl", hosts=["antigravity"], antigravity_home=home)
    setting = json.loads((home/"settings.json").read_text())["statusLine"]
    assert setting["enabled"] is True
    assert "disabled-private-script" not in setting["command"]
    assert "--previous-command" not in setting["command"]


def test_measured_launcher_missing_result_fails_without_inventing_usage(tmp_path):
    fake = tmp_path/"fake-agy"
    fake.write_text('#!'+sys.executable+'\nprint(\'{"event":"init","init":{}}\')\n')
    fake.chmod(0o700)
    log = tmp_path/"usage.jsonl"
    result = subprocess.run([sys.executable, "-m", "course_tutor.host_usage", "antigravity-run", "--project", str(tmp_path),
                             "--log", str(log), "--executable", str(fake), "--", "-p", "fixture"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "no valid terminal" in result.stderr
    assert not log.exists()


def test_statusline_subprocess_preserves_old_display_and_does_not_store_payload(tmp_path):
    payload = status(tmp_path, private_field="PRIVATE data")
    command = [sys.executable, "-m", "course_tutor.host_usage", "statusline", "--host", "claude", "--project", str(tmp_path),
               "--log", str(tmp_path/"usage.jsonl"), "--previous-command", "printf original-display"]
    result = subprocess.run(command, input=json.dumps(payload), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and result.stdout == "original-display", result.stderr
    assert "PRIVATE" not in (tmp_path/"usage.jsonl").read_text()


def test_measured_launcher_captures_only_result_not_steps(tmp_path):
    fake = tmp_path/"fake-agy"
    rows = [{"event": "init", "conversation_id": "ag-1", "init": {"cwd": str(tmp_path)}},
            {"event": "step_update", "step_update": {"usage": {"input_tokens": 9999}}},
            {"event": "result", "result": {"conversation_id": "ag-1", "status": "SUCCESS", "response": "PRIVATE reply",
                                             "usage": {"input_tokens": 5, "output_tokens": 4, "thinking_tokens": 1, "cache_read_tokens": 0, "total_tokens": 9}}}]
    fake.write_text('#!'+sys.executable+'\nimport sys\nsys.stdout.write('+repr(''.join(json.dumps(row)+'\n' for row in rows))+')\n')
    fake.chmod(0o700)
    log = tmp_path/"usage.jsonl"
    result = subprocess.run([sys.executable, "-m", "course_tutor.host_usage", "antigravity-run", "--project", str(tmp_path),
                             "--log", str(log), "--executable", str(fake), "--", "-p", "fixture"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "PRIVATE reply" in result.stdout and "PRIVATE" not in log.read_text()
    snap = summarize_usage(log)["runs"][0]["session_snapshots"][0]
    assert snap["input_tokens"] == 5 and snap["output_tokens"] == 4


def test_watcher_observes_native_callbacks_between_polls(tmp_path):
    log = tmp_path/"usage.jsonl"
    output = []
    def emit(result):
        output.append(result)
        if len(output) == 1:
            capture_statusline(log, tmp_path, "antigravity", status(tmp_path))
    watch_usage(log, tmp_path, hosts=["antigravity"], duration_seconds=.15, poll_seconds=.05, emit=emit)
    assert len(output) == 2
