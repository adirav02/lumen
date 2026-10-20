"""Scoped desktop-app hooks. Only numeric transcript counters enter the ledger."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import sqlite3
import sys
from urllib.parse import unquote, urlsplit
from uuid import UUID

from .errors import ValidationError
from .host_usage import _atomic_settings, _count, _settings_lock, _snapshot, _sum
from .usage import record_usage


def collect_app_usage(log_path, project_path, *, app_home=None):
    """Discover project identity from native metadata before opening transcripts."""
    home = Path(app_home or Path.home()/".gemini/antigravity").resolve()
    database = home/"conversation_summaries.db"
    report = {"host": "antigravity-app", "files_scanned": 0, "sessions_with_usage": 0,
              "snapshots_appended": 0, "snapshots_replayed": 0, "pending_tails": 0,
              "errors": [], "collection_status": "partial"}
    if not database.exists():
        return report
    try:
        # Never read titles, previews, search-index bodies, or conversation DBs.
        with closing(sqlite3.connect(database.as_uri()+"?mode=ro", uri=True, timeout=1)) as con:
            rows = con.execute("SELECT conversation_id, workspace_uris, app_data_dir FROM conversation_summaries").fetchall()
        for session, encoded, surface in rows:
            if surface != "antigravity":
                continue
            try:
                uris = json.loads(encoded)
                if not isinstance(uris, list) or not uris:
                    raise ValidationError("Invalid desktop workspace metadata.")
                workspaces = []
                for uri in uris:
                    if not isinstance(uri, str):
                        raise ValidationError("Invalid desktop workspace URI.")
                    parsed = urlsplit(uri)
                    if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
                        raise ValidationError("Unsupported desktop workspace URI.")
                    workspaces.append(str(Path(unquote(parsed.path)).resolve()))
                if set(workspaces) != {str(Path(project_path).resolve())}:
                    continue
                transcript = home/"brain"/session/".system_generated/logs/transcript.jsonl"
                report["files_scanned"] += 1
                result = capture_app_usage(log_path, project_path,
                                           {"workspacePaths": workspaces, "conversationId": session,
                                            "transcriptPath": str(transcript)}, app_home=home)
                if result:
                    report["sessions_with_usage"] += 1
                    report["snapshots_replayed"] += int(result["replayed"])
                    report["snapshots_appended"] += int(not result["replayed"])
            except (ValueError, TypeError, OSError, ValidationError) as exc:
                report["errors"].append({"reason": str(exc) if isinstance(exc, ValidationError) else type(exc).__name__})
    except sqlite3.Error:
        report["errors"].append({"reason": "Desktop metadata database unavailable or incompatible."})
    return report


def capture_app_usage(log_path, project_path, payload, *, app_home=None):
    if not isinstance(payload, dict):
        raise ValidationError("Desktop hook payload must be an object.")
    workspaces = payload.get("workspacePaths")
    if not isinstance(workspaces, list) or not all(isinstance(p, str) for p in workspaces):
        raise ValidationError("Desktop hook requires workspacePaths.")
    # Multiple mounted projects cannot be attributed to this workspace alone.
    if {Path(p).resolve() for p in workspaces} != {Path(project_path).resolve()}:
        return None
    session = payload.get("conversationId")
    try:
        if str(UUID(session)) != session:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Invalid desktop conversation identity.") from None
    home = Path(app_home or Path.home()/".gemini/antigravity").resolve()
    expected = home/"brain"/session/".system_generated/logs/transcript.jsonl"
    transcript = payload.get("transcriptPath")
    if not isinstance(transcript, str) or Path(transcript).expanduser().resolve() != expected:
        return None  # CLI and IDE share hooks; their transcripts are excluded.
    if expected.resolve() != expected:
        raise ValidationError("Desktop transcript must not redirect outside its conversation.")
    messages = {}
    with expected.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                break  # live host may still be writing the last record
            try:
                row = json.loads(line)
            except ValueError:
                raise ValidationError(f"Invalid desktop transcript JSON on line {number}.") from None
            if not isinstance(row, dict):
                raise ValidationError("Invalid desktop transcript record.")
            if row.get("source") != "MODEL" or row.get("type") != "PLANNER_RESPONSE":
                continue
            if not any(k in row for k in ("input_tokens", "output_tokens", "cache_read_tokens")):
                continue
            idx = row.get("step_index")
            if type(idx) is not int or idx < 0:
                raise ValidationError("Desktop usage requires a stable step index.")
            counts = {k: _count(row.get(k), k) for k in ("input_tokens", "output_tokens", "cache_read_tokens")}
            if counts["input_tokens"] is None or counts["output_tokens"] is None:
                raise ValidationError("Desktop usage lacks input/output counters.")
            stamp = row.get("created_at")
            try:
                observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise ValidationError("Desktop usage timestamp must identify an absolute time.") from None
            messages[idx] = (counts, observed.astimezone(timezone.utc).isoformat())
    if not messages:
        return None
    raw = {k: _sum([v[0][k] for v in messages.values()]) for k in
           ("input_tokens", "output_tokens", "cache_read_tokens")}
    # Exposed transcript formats do not promise cache inclusion semantics.
    inclusive = raw["input_tokens"] if raw["cache_read_tokens"] == 0 else None
    event = _snapshot("antigravity-app", session, expected, [],
                      {"input_tokens": inclusive, "output_tokens": raw["output_tokens"],
                       "cached_input_tokens": 0 if inclusive is not None else None,
                       "reasoning_output_tokens": None}, "transcript_messages",
                      "Desktop transcript: sum of unique MODEL/PLANNER_RESPONSE step counters; latest record replaces streamed duplicates. Raw cache semantics are unverified, so inclusive input is unknown when cache reads are nonzero or missing. No chat text copied. Hidden retries, billing, thinking and image completeness unknown; shared/fork histories are not pooled.",
                      observed=max(v[1] for v in messages.values()), reported_usage=raw)
    return record_usage(log_path, event)


def configure_app_usage(project_path, log_path):
    project, log = Path(project_path).resolve(), Path(log_path).resolve()
    path = project/".agents/hooks.json"
    command = shlex.join([sys.executable, "-m", "course_tutor.antigravity_app_usage",
                          "--project", str(project), "--log", str(log)])
    entry = {"enabled": True, **{event: [{"type": "command", "command": command, "timeout": 10}]
                                for event in ("PostInvocation", "Stop")}}
    with _settings_lock(path):
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except (ValueError, OSError):
            raise ValidationError("Cannot safely read desktop hooks; no replacement written.") from None
        if not isinstance(data, dict):
            raise ValidationError("Desktop hooks must be an object.")
        key = "lumen-desktop-usage"
        if key in data and data[key] != entry:
            raise ValidationError("Existing Lumen desktop hook differs; preserve it for review.")
        changed = data.get(key) != entry
        data[key] = entry
        backup = _atomic_settings(path, data) if changed else None
    return {"host": "antigravity-app", "settings_path": str(path), "changed": changed,
            "backup_path": backup}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    try:
        capture_app_usage(args.log, args.project, json.load(sys.stdin))
    except (ValueError, OSError, ValidationError, TypeError):
        print("Lumen: desktop usage capture unavailable; no save acknowledged.", file=sys.stderr)
        print("{}")
        return 1
    # Hooks must not inject chat text or change agent execution behavior.
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
