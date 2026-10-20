# TL;DR: Parse native Codex records and explicit parent links without model calls.
# Status: active; date: 2026-10-19.
import json
from datetime import datetime, timezone
from pathlib import Path

COUNTERS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')


def utc(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() != timezone.utc.utcoffset(result):
            raise ValueError
        return result
    except (AttributeError, TypeError, ValueError):
        raise ValueError('Expected an explicit UTC timestamp (Z or +00:00)') from None


def records(path):
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if not line.endswith('\n'):
                raise ValueError(f'{path.name}:{number}: incomplete log line')
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError
            except ValueError:
                raise ValueError(f'{path.name}:{number}: invalid JSON object') from None
            yield row


def spawn(meta):
    source = meta.get('source')
    if not isinstance(source, dict):
        return {}
    return source.get('subagent', {}).get('thread_spawn', {})


def discover(home):
    sessions = {}
    for directory in ('sessions', 'archived_sessions'):
        for path in sorted((home / directory).rglob('*.jsonl')):
            first = next(records(path), {})
            if first.get('type') != 'session_meta':
                continue
            meta = first.get('payload', {})
            if not meta.get('id') or not meta.get('cwd'):
                raise ValueError(f'{path.name}: session metadata lacks id/cwd')
            entry = sessions.setdefault(meta['id'], {'meta': meta, 'paths': []})
            if entry['meta'] != meta:
                raise ValueError(f"Conflicting metadata for {meta['id']}")
            entry['paths'].append(path)
    return sessions


def read_thread(key, entry, since, until):
    responses, tools = {}, {}
    for path in entry['paths']:
        for row in records(path):
            kind, payload = row.get('type'), row.get('payload', {})
            native = kind == 'token_usage_record'
            tool = kind == 'response_item' and payload.get('type') in {
                'function_call', 'custom_tool_call', 'web_search_call'}
            if not (native or tool):
                continue
            # Forked/inherited records belong to their recorded emitting thread.
            if native and payload.get('thread_id', key) != key:
                continue
            timestamp = utc(row.get('timestamp'))
            if (since and timestamp < since) or (until and timestamp > until):
                continue
            if tool:
                identity = payload.get('call_id') or payload.get('id')
                if not identity:
                    raise ValueError(f'{key}: tool call lacks an identity')
                tools[identity] = True
                continue
            identity, usage = payload.get('response_id'), payload.get('usage')
            if not identity or not isinstance(usage, dict):
                raise ValueError(f'{key}: missing response identity/usage')
            if any(type(usage.get(k)) is not int or usage[k] < 0 for k in COUNTERS):
                raise ValueError(f'{key}: missing or invalid native token counters')
            if usage['cached_input_tokens'] > usage['input_tokens'] or usage['reasoning_output_tokens'] > usage['output_tokens']:
                raise ValueError(f'{key}: invalid token subsets')
            value = {k: usage[k] for k in COUNTERS}
            if identity in responses and responses[identity] != value:
                raise ValueError(f'{key}: conflicting usage for response {identity}')
            responses[identity] = value
    return responses, tools


def summarize(key, role, responses, tools):
    totals = {k: sum(u[k] for u in responses.values()) for k in COUNTERS}
    return dict(thread_id=key, role=role, **totals,
                fresh_input_tokens=totals['input_tokens']-totals['cached_input_tokens'],
                model_calls=len(responses), tool_calls=len(tools))
