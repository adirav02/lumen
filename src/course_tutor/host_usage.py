"""Native Claude/Antigravity measurement callbacks; never persist message text."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from .errors import ValidationError
from .models import utc_now_iso
from .usage import record_usage, validate_event
from .storage.sync import fcntl


def _count(value, name):
    if value is not None and (type(value) is not int or value < 0):
        raise ValidationError(f"Invalid {name} counter.")
    return value


def _sum(values):
    return sum(values) if all(value is not None for value in values) else None


def _snapshot(host, session, path, models, counts, scope, note, observed=None, **extra):
    event = {"kind": "snapshot", "host": host, "run_id": f"{host}-session:{session}",
             "session_id": session, "provider": "unavailable", "models": sorted(set(models)),
             "usage_source": "host_reported", "usage_scope": scope,
             "source_file": str(path), "source_note": note, **counts, **extra}
    # Callback delivery time is not a new charge; identical counters replay.
    event["event_id"] = "snapshot:" + hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
    event["observed_at"] = observed or utc_now_iso()
    validate_event(event)
    return event


def read_claude_snapshot(path, project_path):
    project = Path(project_path).resolve()
    messages = {}
    matched = False
    pending = False
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                pending = True
                break
            try:
                row = json.loads(line)
            except ValueError:
                raise ValidationError(f"Invalid Claude JSON on line {number}.") from None
            if not isinstance(row, dict):
                raise ValidationError(f"Invalid Claude record on line {number}.")
            cwd = row.get("cwd")
            if not matched and isinstance(cwd, str):
                if Path(cwd).resolve() != project:
                    return None, False
                matched = True
            if not matched or row.get("type") != "assistant" or row.get("isApiErrorMessage"):
                continue
            message = row.get("message")
            if not isinstance(message, dict) or message.get("usage") is None:
                continue
            mid, usage = message.get("id"), message["usage"]
            if not isinstance(mid, str) or not mid or not isinstance(usage, dict):
                raise ValidationError(f"Claude usage lacks stable message identity on line {number}.")
            values = {key: _count(usage.get(key), key) for key in
                      ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
            if values["input_tokens"] is None or values["output_tokens"] is None:
                raise ValidationError(f"Claude usage lacks input/output counters on line {number}.")
            model = message.get("model")
            if model is not None and (not isinstance(model, str) or not model.strip()):
                raise ValidationError("Invalid Claude model metadata.")
            # A message may occur in several streamed content records. Last usage
            # for the same message replaces prior fragments rather than summing.
            messages[mid] = (values, model, row.get("timestamp"))
    if not messages:
        return None, pending
    records = list(messages.values())
    raw = {key: _sum([r[0][key] for r in records]) for key in records[0][0]}
    total_input = _sum([raw["input_tokens"], raw["cache_creation_input_tokens"], raw["cache_read_input_tokens"]])
    # Separate child logs, even when they carry the parent's session_id.
    source = Path(path).resolve()
    session = source.stem if source.parent.name != "subagents" else f"{source.parent.parent.name}:{source.stem}"
    observed = records[-1][2]
    if observed is not None:
        try:
            stamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError
            observed = stamp.astimezone(timezone.utc).isoformat()
        except (AttributeError, ValueError, TypeError):
            raise ValidationError("Invalid Claude usage timestamp.") from None
    return _snapshot("claude", session, source, [r[1] for r in records if r[1]],
                     {"input_tokens": total_input, "cached_input_tokens": raw["cache_read_input_tokens"] if total_input is not None else None,
                      "output_tokens": raw["output_tokens"], "reasoning_output_tokens": None},
                     "transcript_messages", "Sum of unique observed Claude assistant message usage, including cache creation/read in input. Stream fragments are replaced by message ID. Missing cache fields keep inclusive input unknown. Error-only requests and hidden retries may be absent; no billing or image completeness claim.",
                     observed=observed, reported_usage={"uncached_input_tokens": raw["input_tokens"], "cache_creation_input_tokens": raw["cache_creation_input_tokens"], "cache_read_tokens": raw["cache_read_input_tokens"]}), pending


def capture_statusline(log_path, project_path, host, payload):
    if host not in {"claude", "antigravity"}:
        raise ValidationError("Unsupported status-line host.")
    workspace = payload.get("workspace") or {}
    if not isinstance(workspace, dict):
        raise ValidationError("Invalid status-line workspace.")
    cwd = workspace.get("project_dir") or payload.get("cwd") or workspace.get("current_dir")
    if not isinstance(cwd, str) or Path(cwd).resolve() != Path(project_path).resolve():
        return None
    session = payload.get("conversation_id") if host == "antigravity" else payload.get("session_id")
    session = session or payload.get("session_id")
    if not isinstance(session, str) or not session:
        raise ValidationError("Missing status-line session identity.")
    context = payload.get("context_window")
    if not isinstance(context, dict):
        return None
    inputs = _count(context.get("total_input_tokens"), "input_tokens")
    outputs = _count(context.get("total_output_tokens"), "output_tokens")
    if inputs is None and outputs is None:
        return None
    model = payload.get("model") or {}
    model = model.get("id") if isinstance(model, dict) else None
    if model is not None and not isinstance(model, str):
        raise ValidationError("Invalid status-line model.")
    snapshot = _snapshot(host, session, f"{host}:statusline", [model] if model else [],
                         {"input_tokens": inputs, "output_tokens": outputs, "cached_input_tokens": None, "reasoning_output_tokens": None},
                         "context_window", "Native status-line context counters, not cumulative session consumption. Current model is not an attribution of all historical use. Billing, cache totals, images and hidden retries unknown.")
    if host == "claude" and isinstance(payload.get("transcript_path"), str) and Path(payload["transcript_path"]).expanduser().is_file():
        # Validate the transcript's own cwd as well as the callback metadata.
        candidate, pending = read_claude_snapshot(Path(payload["transcript_path"]).expanduser(), project_path)
        if candidate:
            snapshot = candidate
    cost = payload.get("cost")
    if isinstance(cost, dict):
        snapshot["estimated_cost_usd"] = cost.get("total_cost_usd")
        snapshot["session_duration_ms"] = cost.get("total_duration_ms")
    # Include callback cost/scope in identity, but exclude delivery time.
    snapshot.pop("event_id")
    snapshot["event_id"] = "snapshot:" + hashlib.sha256(json.dumps({k: v for k, v in snapshot.items() if k != "observed_at"}, sort_keys=True).encode()).hexdigest()
    validate_event(snapshot)
    return record_usage(log_path, snapshot)


def capture_antigravity_result(log_path, project_path, result, init):
    if not isinstance(init, dict) or not isinstance(init.get("cwd"), str) or Path(init["cwd"]).resolve() != Path(project_path).resolve():
        raise ValidationError("Antigravity stream must begin with matching project metadata.")
    session = result.get("conversation_id")
    if not isinstance(session, str) or not session or session != init.get("conversation_id"):
        raise ValidationError("Antigravity result identity does not match stream initialization.")
    usage = result.get("usage")
    if not isinstance(usage, dict):
        raise ValidationError("Antigravity result lacks usage metadata.")
    raw = {key: _count(usage.get(key), key) for key in ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens")}
    if raw["input_tokens"] is None or raw["output_tokens"] is None:
        raise ValidationError("Antigravity result lacks input/output counters.")
    model = init.get("model")
    snapshot = _snapshot("antigravity", session, "antigravity:stream-json", [model] if isinstance(model, str) else [],
                         {"input_tokens": raw["input_tokens"] if raw["cache_read_tokens"] == 0 else None,
                          "output_tokens": raw["output_tokens"], "cached_input_tokens": None,
                          "reasoning_output_tokens": raw["thinking_tokens"]},
                         "conversation", "Native cumulative Antigravity result counters. Cache inclusion in input varies across exposed formats; raw input/cache counters are retained without guessing inclusive input. Step updates are not added to final totals. Terminal status does not prove retry/image/billing completeness.", reported_usage=raw,
                         terminal_status=result.get("status", "unknown"))
    return record_usage(log_path, snapshot)


def _atomic_settings(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_bytes() if path.exists() else None
    backup = None
    if old is not None:
        directory = path.parent / ".lumen-usage-backups"
        directory.mkdir(mode=0o700, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(old)
            stream.flush()
            os.fsync(stream.fileno())
        backup = str(name)
    fd, name = tempfile.mkstemp(prefix=".lumen-usage-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()
    return backup


@contextmanager
def _settings_lock(path):
    if fcntl is None:
        raise ValidationError("Settings locking is unsupported on this platform.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent/".lumen-usage-settings.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def configure_usage(project_path, log_path, *, hosts=None, claude_home=None, antigravity_home=None):
    hosts = ["claude", "antigravity"] if hosts is None else hosts
    if not isinstance(hosts, list) or not hosts or any(not isinstance(host, str) or host not in {"claude", "antigravity", "antigravity-app"} for host in hosts):
        raise ValidationError("hosts must select claude, antigravity and/or antigravity-app.")
    project, log = Path(project_path).resolve(), Path(log_path).resolve()
    results = []
    try:
        for host in dict.fromkeys(hosts):
            if host == "antigravity-app":
                from .antigravity_app_usage import configure_app_usage
                results.append(configure_app_usage(project, log))
                continue
            home = (Path(claude_home or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home()/".claude") if host == "claude"
                    else Path(antigravity_home or Path.home()/".gemini/antigravity-cli"))
            path = project/".claude/settings.local.json" if host == "claude" else home/"settings.json"
            with _settings_lock(path):
                try:
                    data = json.loads(path.read_text()) if path.exists() else {}
                    inherited = json.loads((home/"settings.json").read_text()) if host == "claude" and (home/"settings.json").exists() else {}
                except (OSError, ValueError):
                    raise ValidationError(f"Cannot safely read {host} settings; no replacement written.") from None
                if not isinstance(data, dict) or not isinstance(inherited, dict):
                    raise ValidationError(f"{host} settings must be an object.")
                previous = data.get("statusLine", inherited.get("statusLine", {})) or {}
                if not isinstance(previous, dict) or previous.get("type", "command") not in {None, "", "command"}:
                    raise ValidationError(f"Unsupported existing {host} status line; no replacement written.")
                old_command = previous.get("command", "")
                if not isinstance(old_command, str):
                    raise ValidationError("Status-line command must be a string.")
                # Enabling measurement must not execute an older display script
                # that the user had explicitly disabled.
                if host == "antigravity" and previous.get("enabled") is False:
                    old_command = ""
                args = [sys.executable, "-m", "course_tutor.host_usage", "statusline", "--host", host,
                        "--project", str(project), "--log", str(log)]
                base = shlex.join(args)
                if old_command == base or old_command.startswith(base + " --previous-command "):
                    results.append({"host": host, "settings_path": str(path), "changed": False})
                    continue
                if old_command:
                    args += ["--previous-command", old_command]
                status = {**previous, "type": "command", "command": shlex.join(args)}
                if host == "antigravity":
                    status["enabled"] = True
                data["statusLine"] = status
                backup = _atomic_settings(path, data)
                results.append({"host": host, "settings_path": str(path), "changed": True,
                                "backup_path": backup, "preserved_existing_statusline": bool(old_command)})
    except ValidationError as exc:
        exc.details = {**exc.details, "configured_before_error": results, "failed_host": host}
        raise
    except OSError as exc:
        raise ValidationError("Could not persist host settings.", details={"configured_before_error": results, "failed_host": host, "failure_type": type(exc).__name__}) from None
    return {"configured": results, "log_path": str(log), "project_path": str(project),
            "limits": "Configuration is not proof of native invocation. Desktop hooks and CLI status lines are separate adapters; native runtime checks are required."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["statusline", "antigravity-run"])
    parser.add_argument("--host", choices=["claude", "antigravity"], default="antigravity")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--previous-command")
    parser.add_argument("--executable", default="agy")
    argv = list(sys.argv[1:] if argv is None else argv)
    split = argv.index("--") if "--" in argv else len(argv)
    command = argv[split+1:]
    args = parser.parse_args(argv[:split])
    if args.mode == "antigravity-run":
        if not any(arg in {"-p", "--print", "--prompt"} or arg.startswith(("--print=", "--prompt=")) for arg in command):
            parser.error("The measured launcher requires a headless --print/-p prompt.")
        if any(arg.startswith("--output-format") for arg in command):
            parser.error("The measured launcher controls --output-format.")
        process = subprocess.Popen([args.executable, *command, "--output-format", "stream-json"], cwd=args.project,
                                   stdout=subprocess.PIPE, text=True)
        init = None
        failed = False
        saw_result = False
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            try:
                row = json.loads(line)
                if row.get("event") == "init":
                    init = {**row["init"], "conversation_id": row.get("conversation_id")}
                elif row.get("event") == "result":
                    capture_antigravity_result(args.log, args.project, row["result"], init)
                    saw_result = True
            except (ValueError, KeyError, TypeError, AttributeError, ValidationError, OSError):
                print("Lumen: usage capture failed; native output retained on stdout.", file=sys.stderr)
                failed = True
        code = process.wait()
        if not saw_result:
            print("Lumen: no valid terminal usage result observed.", file=sys.stderr)
        raise SystemExit(code or (1 if failed or not saw_result else 0))
    raw = sys.stdin.read()
    saved = None
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValidationError("Status-line input must be an object.")
        saved = capture_statusline(args.log, args.project, args.host, payload)
    except (ValueError, ValidationError, OSError, TypeError):
        print("Lumen: usage capture unavailable; no save acknowledged.", file=sys.stderr)
    if args.previous_command:
        try:
            old = subprocess.run(args.previous_command, shell=True, input=raw, text=True, capture_output=True, timeout=5)
            sys.stdout.write(old.stdout)
            if old.returncode:
                print("Lumen: previous status-line command failed.", file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired):
            print("Lumen: previous status-line command unavailable.", file=sys.stderr)
    elif saved:
        event = saved["event"]
        print(f"Lumen usage: {event['input_tokens'] if event['input_tokens'] is not None else '?'} in / {event['output_tokens'] if event['output_tokens'] is not None else '?'} out ({event.get('usage_scope', 'session')})")


if __name__ == "__main__":
    main()
