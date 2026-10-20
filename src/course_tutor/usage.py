"""Measurement events, independent of learner evidence.

This does not instrument a host or infer billing from its subscription. A JSONL
ledger is useful even when the only honest measurement is 'unavailable'.
"""

from contextlib import contextmanager
from decimal import Decimal
import json
import math
import os
from pathlib import Path

from .errors import ValidationError
from .models import utc_now_iso
from .storage.sync import fcntl


COMMON = {"event_id", "kind", "run_id", "source_note"}
FIELDS = {
    "call": {"task_id", "host", "provider", "model", "status", "usage_source",
             "input_tokens", "output_tokens", "cached_input_tokens", "image_count",
             "latency_ms", "retry_of", "cost_usd", "cost_source"},
    "task": {"task_id", "outcome", "reviewer_reference"},
    "run": {"collection_status"},
    "snapshot": {"host", "session_id", "provider", "models", "usage_source",
                 "input_tokens", "output_tokens", "cached_input_tokens",
                 "reasoning_output_tokens", "observed_at", "source_file"},
}
SNAPSHOT_OPTIONAL = {"usage_scope", "estimated_cost_usd", "session_duration_ms", "reported_usage", "terminal_status"}


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")


def validate_event(event):
    if not isinstance(event, dict):
        raise ValidationError("Usage event must be an object.")
    kind = event.get("kind")
    if not isinstance(kind, str) or kind not in FIELDS:
        raise ValidationError("kind must be call, task, run, or snapshot.")
    required = COMMON | FIELDS[kind]
    optional = SNAPSHOT_OPTIONAL if kind == "snapshot" else set()
    if not required <= set(event) or set(event) - required - optional:
        raise ValidationError(f"Usage fields missing: {sorted(required - set(event))}; unknown: {sorted(set(event) - required)}.")
    for key in COMMON | (FIELDS[kind] & {"task_id", "host", "provider", "model", "reviewer_reference", "session_id", "observed_at", "source_file"}):
        _text(event[key], key)
    choices = {
        "status": {"completed", "failed", "interrupted", "unknown"},
        "usage_source": {"provider_reported", "host_reported", "estimated", "unavailable"},
        "cost_source": {"billed", "estimated", "unavailable"},
        "outcome": {"correct", "incorrect", "pending"},
        "collection_status": {"complete", "partial"},
    }
    for key, allowed in choices.items():
        if key in event and (not isinstance(event[key], str) or event[key] not in allowed):
            raise ValidationError(f"{key} must be one of {sorted(allowed)}.")
    if kind == "snapshot":
        if "terminal_status" in event:
            _text(event["terminal_status"], "terminal_status")
        if event["usage_source"] != "host_reported":
            raise ValidationError("Snapshot usage_source must be host_reported.")
        if not isinstance(event["models"], list):
            raise ValidationError("Snapshot models must be a list of observed model names.")
        for model in event["models"]:
            _text(model, "models entry")
        if "usage_scope" in event and event["usage_scope"] not in {"session", "transcript_messages", "context_window", "conversation"}:
            raise ValidationError("Invalid snapshot usage_scope.")
        cost = event.get("estimated_cost_usd")
        if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
            raise ValidationError("Snapshot estimated cost must be finite and non-negative or null.")
        duration = event.get("session_duration_ms")
        if duration is not None and (type(duration) is not int or duration < 0):
            raise ValidationError("Snapshot session duration must be a non-negative integer or null.")
        reported = event.get("reported_usage", {})
        allowed = {"input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens", "uncached_input_tokens", "cache_creation_input_tokens"}
        if not isinstance(reported, dict) or set(reported) - allowed:
            raise ValidationError("Unsupported reported_usage fields.")
        if any(value is not None and (type(value) is not int or value < 0) for value in reported.values()):
            raise ValidationError("Reported usage counters must be non-negative integers or null.")
    if kind not in {"call", "snapshot"}:
        return
    for key in ("input_tokens", "output_tokens", "cached_input_tokens", "image_count", "latency_ms"):
        value = event.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValidationError(f"{key} must be a non-negative integer or null.")
    cached, inputs = event["cached_input_tokens"], event["input_tokens"]
    if cached is not None and (inputs is None or cached > inputs):
        raise ValidationError("cached_input_tokens is a subset of input_tokens, not an additional charge.")
    if kind == "snapshot":
        reasoning = event["reasoning_output_tokens"]
        if reasoning is not None and (type(reasoning) is not int or reasoning < 0
                                      or event["output_tokens"] is None or reasoning > event["output_tokens"]):
            raise ValidationError("reasoning_output_tokens must be a non-negative subset of output_tokens or null.")
        return
    if event["usage_source"] == "unavailable" and any(event[k] is not None for k in ("input_tokens", "output_tokens", "cached_input_tokens")):
        raise ValidationError("Unavailable token usage must use null counts.")
    cost = event["cost_usd"]
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        raise ValidationError("cost_usd must be a finite non-negative number or null.")
    if (cost is None) != (event["cost_source"] == "unavailable"):
        raise ValidationError("Unknown cost requires cost_usd=null and cost_source=unavailable.")
    if event["retry_of"] is not None:
        _text(event["retry_of"], "retry_of")


@contextmanager
def _ledger(path, *, write=False):
    if fcntl is None:
        raise ValidationError("Usage ledger locking is unsupported on this platform.")
    path = Path(path)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.exists():
        yield None
        return
    with path.open("a+" if write else "r", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        try:
            stream.seek(0)
            yield stream
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read(stream):
    rows = []
    seen = {}
    if stream is None:
        return rows
    for number, line in enumerate(stream, 1):
        try:
            if not line.endswith("\n"):
                raise ValueError("incomplete line")
            row = json.loads(line)
            event = {k: v for k, v in row.items() if k != "recorded_at"}
            validate_event(event)
            _text(row.get("recorded_at"), "recorded_at")
            _validate_history(event, seen)
        except (ValueError, TypeError, AttributeError, ValidationError) as exc:
            raise ValidationError(f"Usage ledger line {number} is invalid; preserve and repair it before continuing: {exc}") from exc
        rows.append(row)
        seen[row["event_id"]] = row
    return rows


def _validate_history(event, rows):
    indexed = rows if isinstance(rows, dict) else {row["event_id"]: row for row in rows}
    if event["event_id"] in indexed:
        raise ValidationError("Duplicate usage event_id.")
    if event["kind"] == "call" and event["retry_of"] is not None:
        parent = indexed.get(event["retry_of"])
        if not parent or parent["kind"] != "call" or any(parent[k] != event[k] for k in ("run_id", "task_id")):
            raise ValidationError("retry_of must identify an earlier call for the same run and task.")


def record_usage(path, event):
    validate_event(event)
    with _ledger(path, write=True) as stream:
        rows = _read(stream)
        previous = next((row for row in rows if row["event_id"] == event["event_id"]), None)
        if previous:
            # Native callbacks often repeat unchanged counters without a source
            # timestamp. Replaying that snapshot keeps its first observation time.
            ignored = {"recorded_at", "observed_at"} if event["kind"] == "snapshot" else {"recorded_at"}
            if {k: v for k, v in previous.items() if k not in ignored} != {k: v for k, v in event.items() if k not in ignored}:
                raise ValidationError("event_id already records a different usage event.")
            return {"event": previous, "replayed": True, "log_path": str(path)}
        _validate_history(event, rows)
        row = {**event, "recorded_at": utc_now_iso()}
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"event": row, "replayed": False, "log_path": str(path)}


def summarize_usage(path, run_id=None):
    with _ledger(path) as stream:
        rows = _read(stream)
    if run_id is not None:
        _text(run_id, "run_id")
        rows = [r for r in rows if r["run_id"] == run_id]
    runs = []
    for rid in sorted({r["run_id"] for r in rows}):
        events = [r for r in rows if r["run_id"] == rid]
        calls = [r for r in events if r["kind"] == "call"]
        tasks = {r["task_id"]: r for r in events if r["kind"] == "task"}
        run_notes = [r for r in events if r["kind"] == "run"]
        snapshots = {}
        for event in events:
            if event["kind"] == "snapshot":
                snapshots[(event["host"], event["session_id"], event.get("usage_scope", "session"))] = event
        # Any call/outcome appended after a completion declaration reopens collection.
        complete = bool(run_notes and run_notes[-1]["collection_status"] == "complete"
                        and events[-1]["kind"] == "run" and not snapshots)
        task_ids = {r["task_id"] for r in calls} | set(tasks)
        correct = sum(tasks[t]["outcome"] == "correct" for t in tasks)
        pending = sum(t not in tasks or tasks[t]["outcome"] == "pending" for t in task_ids)
        costs = {source: sum((Decimal(str(r["cost_usd"])) for r in calls if r["cost_source"] == source), Decimal(0))
                 for source in ("billed", "estimated")}
        groups = {}
        for call in calls:
            key = tuple(call[k] for k in ("host", "provider", "model", "usage_source"))
            group = groups.setdefault(key, {**dict(zip(("host", "provider", "model", "usage_source"), key)), "calls": 0})
            group["calls"] += 1
            for field in ("input_tokens", "output_tokens", "cached_input_tokens", "image_count", "latency_ms"):
                group[field + "_known_sum"] = group.get(field + "_known_sum", 0) + (call[field] or 0)
                group[field + "_unknown_calls"] = group.get(field + "_unknown_calls", 0) + (call[field] is None)
        eligible = (complete and bool(calls) and correct > 0 and pending == 0
                    and not snapshots
                    and {r["task_id"] for r in calls} == task_ids
                    and all(r["cost_source"] == "billed" for r in calls))
        runs.append({
            "run_id": rid, "collection_status": "complete" if complete else "partial",
            "collection_note": run_notes[-1]["source_note"] if run_notes else "No collection declaration recorded.",
            "calls": len(calls), "retries": sum(r["retry_of"] is not None for r in calls),
            "failed_or_interrupted_calls": sum(r["status"] in {"failed", "interrupted"} for r in calls),
            "correct_tasks": correct, "incorrect_tasks": sum(r["outcome"] == "incorrect" for r in tasks.values()),
            "pending_tasks": pending,
            "known_billed_cost_usd": str(costs["billed"]), "known_estimated_cost_usd": str(costs["estimated"]),
            "unknown_cost_calls": sum(r["cost_usd"] is None for r in calls),
            "billed_cost_per_correct_task_usd": str(costs["billed"] / correct) if eligible else None,
            "usage_groups": list(groups.values()),
            "session_snapshots": list(snapshots.values()),
        })
    return {"log_path": str(path), "events": len(rows), "runs": runs,
            "limits": "Calls are supplied observations; snapshots are automatically imported host counters. Latest snapshots are selected per host/session/scope; context-window, transcript and conversation counters stay separate. Snapshots are not added to call totals or each other. They do not establish per-call, retry, image or billing coverage. Known sums exclude unknown data; cached input is included in normalized input. Cost per correct task requires complete per-call collection, reviewed outcomes and billed costs."}
