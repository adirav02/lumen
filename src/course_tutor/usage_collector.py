"""Read Codex's local usage counters without copying conversation content.

The rollout JSONL format is version-dependent. These are cumulative session
snapshots, never fabricated per-request records or invoices.
"""

import hashlib
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import time

from .errors import ValidationError
from .usage import record_usage, summarize_usage


def _object(line, number):
    try:
        row = json.loads(line)
    except ValueError:
        raise ValidationError(f"Invalid JSON on line {number}.") from None
    if not isinstance(row, dict):
        raise ValidationError(f"Expected object on line {number}.")
    return row


def read_codex_snapshot(path, project_path):
    """Inspect metadata first; ignore other projects before reading their bodies."""
    project = Path(project_path).resolve()
    with Path(path).open(encoding="utf-8") as stream:
        first = stream.readline()
        if not first.endswith("\n"):
            return None, True
        row = _object(first, 1)
        meta = row.get("payload")
        if row.get("type") != "session_meta" or not isinstance(meta, dict):
            return None, False
        cwd = meta.get("cwd")
        if not isinstance(cwd, str) or Path(cwd).resolve() != project:
            return None, False
        session = meta.get("id")
        if not isinstance(session, str) or not session.strip():
            raise ValidationError("Matching session metadata lacks an ID.")
        models = set()
        latest = None
        pending_tail = False
        for number, line in enumerate(stream, 2):
            if not line.endswith("\n"):
                pending_tail = True
                break  # the host may still be writing this final line
            row = _object(line, number)
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            if row.get("type") == "turn_context":
                model = payload.get("model")
                if isinstance(model, str) and model.strip():
                    models.add(model)
            if row.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            if info is None:  # rate-limit-only event, not a usage update
                continue
            totals = info.get("total_token_usage") if isinstance(info, dict) else None
            if not isinstance(totals, dict):
                raise ValidationError(f"Unsupported token counter schema on line {number}.")
            if not {"input_tokens", "output_tokens"} <= totals.keys():
                raise ValidationError(f"Missing input/output counters on line {number}.")
            latest = (row.get("timestamp"), totals)
    if latest is None:
        return None, pending_tail
    observed_at, totals = latest
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError
        observed_at = observed.astimezone(timezone.utc).isoformat()
    except (AttributeError, ValueError, TypeError):
        raise ValidationError("Usage timestamp must identify an absolute time.") from None
    event = {
        "kind": "snapshot", "run_id": f"codex-session:{session}", "session_id": session,
        "host": "codex", "provider": meta.get("model_provider") or "unavailable",
        "models": sorted(models), "usage_source": "host_reported",
        "observed_at": observed_at, "source_file": str(Path(path).resolve()),
        **{key: totals.get(key) for key in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens")},
        "source_note": "Cumulative counters from a project-matched Codex rollout. Session-wide, possibly including inherited history; not Lumen-only or per-request usage. Cached input and reasoning output are subsets. Billing, retry costs, image counts and latency unavailable. Conversation text is not copied.",
    }
    # Content-derived identity makes rescanning, duplicate events and process
    # restarts idempotent. A changed total appends history, not another charge.
    event["event_id"] = "snapshot:" + hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
    return event, pending_tail


def _collect_codex_usage(log_path, project_path, *, codex_home=None, session_files=None):
    project = Path(project_path).resolve()
    home = Path(codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    paths = (list(session_files) if session_files is not None
             else sorted((home / "sessions").rglob("rollout-*.jsonl")))
    selected = {}
    errors = []
    pending = 0
    for path in paths:
        try:
            event, tail = read_codex_snapshot(path, project)
            pending += int(tail)
            if event:
                from .usage import validate_event
                validate_event(event)
                # Copied/rotated logs of the same session must not contribute
                # multiple totals. Prefer the newest observed counter.
                previous = selected.get(event["session_id"])
                if previous is None or event["observed_at"] > previous["observed_at"]:
                    selected[event["session_id"]] = event
        except (OSError, UnicodeError, ValidationError) as exc:
            # Omit transcript content, filesystem exception paths and raw JSON.
            reason = str(exc) if isinstance(exc, ValidationError) else type(exc).__name__
            errors.append({"file": Path(path).name, "reason": reason})
    appended = replayed = 0
    for event in selected.values():
        result = record_usage(log_path, event)
        replayed += int(result["replayed"])
        appended += int(not result["replayed"])
    return {"host": "codex", "project_path": str(project), "files_scanned": len(paths),
            "sessions_with_usage": len(selected), "snapshots_appended": appended, "snapshots_replayed": replayed,
            "pending_tails": pending, "errors": errors, "collection_status": "partial",
            "limits": "Host session counters only. No per-request completeness, hidden retry/image counts or billing claims.",
            "log_path": str(log_path)}


def _collect_claude_usage(log_path, project_path, claude_home=None):
    from .host_usage import read_claude_snapshot
    home = Path(claude_home or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home()/".claude")
    project = str(Path(project_path).resolve())
    encodings = {project.replace(os.sep, "-"), re.sub(r"[^A-Za-z0-9]", "-", project)}
    paths = sorted({path for encoded in encodings for directory in [home/"projects"/encoded]
                    for pattern in ("*.jsonl", "*/subagents/*.jsonl") for path in directory.glob(pattern)})
    appended = replayed = pending = sessions = 0
    errors = []
    for path in paths:
        try:
            event, tail = read_claude_snapshot(path, project)
            pending += int(tail)
            if event:
                result = record_usage(log_path, event)
                sessions += 1
                replayed += int(result["replayed"])
                appended += int(not result["replayed"])
        except (OSError, UnicodeError, ValidationError) as exc:
            errors.append({"file": path.name, "reason": str(exc) if isinstance(exc, ValidationError) else type(exc).__name__})
    return {"host": "claude", "files_scanned": len(paths), "sessions_with_usage": sessions,
            "snapshots_appended": appended, "snapshots_replayed": replayed,
            "pending_tails": pending, "errors": errors, "collection_status": "partial"}


def collect_usage(log_path, project_path, *, codex_home=None, session_files=None, claude_home=None, hosts=None, antigravity_app_home=None, log_locations=None):
    from .usage_locations import log_files
    try:
        configured_files = log_files(log_locations)
    except (ValueError, OSError) as exc:
        raise ValidationError(str(exc)) from None
    if configured_files is not None:
        if session_files is not None:
            raise ValidationError("Choose log_locations or session_files, not both.")
        session_files = configured_files
    hosts = ["codex", "claude", "antigravity"] if hosts is None else hosts
    if not isinstance(hosts, list) or not hosts or any(not isinstance(host, str) or host not in {"codex", "claude", "antigravity", "antigravity-app"} for host in hosts):
        raise ValidationError("hosts must select codex, claude, antigravity and/or antigravity-app.")
    reports = []
    for host in dict.fromkeys(hosts):
        if host == "codex":
            report = _collect_codex_usage(log_path, project_path, codex_home=codex_home, session_files=session_files)
        elif host == "claude":
            report = _collect_claude_usage(log_path, project_path, claude_home)
        elif host == "antigravity-app":
            from .antigravity_app_usage import collect_app_usage
            report = collect_app_usage(log_path, project_path, app_home=antigravity_app_home)
        else:
            existing = summarize_usage(log_path)
            sessions = {s["session_id"] for run in existing["runs"] for s in run["session_snapshots"] if s["host"] == host}
            report = {"host": host, "collection_mode": "native_statusline_or_measured_launcher",
                      "files_scanned": 0, "sessions_with_usage": len(sessions), "snapshots_appended": 0,
                      "snapshots_replayed": 0, "pending_tails": 0, "errors": [], "collection_status": "partial"}
        reports.append(report)
    available = sum(r['sessions_with_usage'] for r in reports)
    state = ('unavailable' if not available else 'partial' if any(
        not r['sessions_with_usage'] or r['errors'] or r['pending_tails'] for r in reports) else 'measured')
    scope = ('Configured project-matched log snapshots only; not per-task, per-request or billing totals. '
             'Missing hosts, pending tails or parse errors limit partial reports.')
    return {"usage_state": state, "scope_limit": scope,
            "usage": None if not available else {"scope": "session_snapshots", "log_path": str(log_path)},
            "unavailable_reason": "No matching logs with usable counters." if not available else None,
            "host": hosts[0] if len(hosts) == 1 else "all", "hosts": reports,
            **{key: sum(r[key] for r in reports) for key in ("files_scanned", "sessions_with_usage", "snapshots_appended", "snapshots_replayed", "pending_tails")},
            "errors": [{"host": r["host"], **error} for r in reports for error in r["errors"]],
            "collection_status": state, "log_path": str(log_path), "project_path": str(Path(project_path).resolve()),
            "limits": "Snapshot scopes differ by host/source. Native callbacks must be configured; missing callbacks or logs are not zero usage. No billing, hidden retry or image completeness claims."}


def watch_usage(log_path, project_path, *, poll_seconds=5, duration_seconds=None, codex_home=None, claude_home=None, hosts=None, antigravity_app_home=None, log_locations=None, emit=print):
    if type(poll_seconds) not in (int, float) or not 0.05 <= poll_seconds <= 30:
        raise ValidationError("poll_seconds must be between 0.05 and 30.")
    for name, value in (("poll_seconds", poll_seconds), ("duration_seconds", duration_seconds)):
        if value is not None and (type(value) not in (int, float) or not 0 <= value <= 86400):
            raise ValidationError(f"{name} must be a finite number from 0 to 86400.")
    started = time.monotonic()
    previous = None
    try:
        while True:
            result = collect_usage(log_path, project_path, codex_home=codex_home, claude_home=claude_home, hosts=hosts, antigravity_app_home=antigravity_app_home, log_locations=log_locations)
            summary = summarize_usage(log_path)
            state = (result["sessions_with_usage"], result["pending_tails"], result["errors"], summary["events"])
            if previous is None or result["snapshots_appended"] or state != previous:
                emit({"status": "success", "data": {"collector": result, "summary": summary}})
            previous = state
            remaining = None if duration_seconds is None else duration_seconds - (time.monotonic() - started)
            if remaining is not None and remaining <= 0:
                return {"stopped": "duration", "log_path": str(log_path)}
            time.sleep(poll_seconds if remaining is None else min(poll_seconds, remaining))
    except KeyboardInterrupt:
        return {"stopped": "interrupt", "log_path": str(log_path)}
