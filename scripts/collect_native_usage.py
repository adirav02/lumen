# TL;DR: Report task root and descendant usage directly from local native logs.
# Status: active; date: 2026-10-19.
"""Deterministic task usage; no events file, network access or LLM calls."""
import argparse
import json
import os
from pathlib import Path
from _native_usage import COUNTERS, discover, read_thread, spawn, summarize, utc


def collect(repo, *, root_thread=None, since=None, until=None, task=None, codex_home=None):
    repo = Path(repo).resolve()
    if task:
        state = json.loads((Path(task) / 'status.json').read_text())
        since = since or state.get('started_utc')
        until = until or state.get('ended_utc')
        root_thread = root_thread or state.get('root_thread_id')
        if not since or not until:
            raise ValueError('Task default window requires started_utc and ended_utc; supply --since/--until')
    if bool(since) != bool(until):
        raise ValueError('Supply both --since and --until')
    since, until = utc(since) if since else None, utc(until) if until else None
    if since and since > until:
        raise ValueError('--since must not follow --until')
    if not root_thread and not since:
        raise ValueError('Supply --root-thread, --since/--until, or --task with timestamps')
    home = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home()/'.codex')
    sessions = discover(home)
    parsed = {}
    if not root_thread:
        candidates = []
        for key, entry in sessions.items():
            if Path(entry['meta']['cwd']).resolve() != repo or spawn(entry['meta']).get('parent_thread_id'):
                continue
            parsed[key] = read_thread(key, entry, since, until)
            if parsed[key][0]:
                candidates.append(key)
        if len(candidates) != 1:
            raise ValueError(f'Expected one active root in window; found {len(candidates)}: {", ".join(candidates)}; supply --root-thread')
        root_thread = candidates[0]
    if root_thread not in sessions:
        raise ValueError(f'Root session log missing: {root_thread}')
    if Path(sessions[root_thread]['meta']['cwd']).resolve() != repo:
        raise ValueError('Root session cwd does not match --repo')
    if spawn(sessions[root_thread]['meta']).get('parent_thread_id'):
        raise ValueError('--root-thread identifies a child, not a root')
    selected = {root_thread}
    while True:
        children = {key for key, entry in sessions.items()
                    if spawn(entry['meta']).get('parent_thread_id') in selected
                    and (not until or utc(entry['meta'].get('timestamp')) <= until)} - selected
        if not children:
            break
        selected.update(children)
    rows, all_responses, all_tools = [], {}, {}
    for key in [root_thread] + sorted(selected - {root_thread}):
        responses, tools = parsed.get(key) or read_thread(key, sessions[key], since, until)
        if not responses and key != root_thread and (since or until) and not tools:
            if read_thread(key, sessions[key], None, None)[0]:
                continue  # Existing child was inactive during this task's window.
        if not responses:
            raise ValueError(f'{key}: no native per-response usage in selected window')
        for identity in responses:
            if identity in all_responses:
                raise ValueError(f'Response identity shared between threads: {identity}')
        if all_tools.keys() & tools.keys():
            raise ValueError('Tool identity shared between threads; ownership is ambiguous')
        role = 'manager' if key == root_thread else spawn(sessions[key]['meta']).get('agent_role')
        if not role:
            raise ValueError(f'{key}: child metadata lacks agent_role')
        rows.append(summarize(key, role, responses, tools))
        all_responses.update(responses)
        all_tools.update(tools)
    return dict(root_thread_id=root_thread, threads=rows,
                total=summarize('TOTAL', 'all', all_responses, all_tools),
                note='Root counters exclude children; total adds root and descendants. Cached input is a subset of input; reasoning is a subset of output. Counts are observed native records, not billing or hidden-retry completeness.')


def table(report):
    columns = ('thread_id', 'role', *COUNTERS[:2], 'fresh_input_tokens', *COUNTERS[2:], 'model_calls', 'tool_calls')
    lines = ['| Thread | Role | Input | Cached | Fresh | Output | Reasoning | Model calls | Tool calls |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in report['threads'] + [report['total']]:
        lines.append('| ' + ' | '.join(f'{row[k]:,}' if isinstance(row[k], int) else row[k] for k in columns) + ' |')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--root-thread')
    parser.add_argument('--since')
    parser.add_argument('--until')
    parser.add_argument('--task', type=Path)
    parser.add_argument('--codex-home', type=Path)
    parser.add_argument('--json', action='store_true')
    args = vars(parser.parse_args())
    as_json = args.pop('json')
    try:
        report = collect(**args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps(report, indent=2) if as_json else table(report) + '\n' + report['note'])


if __name__ == '__main__':
    main()
