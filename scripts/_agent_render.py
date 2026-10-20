# TL;DR: Render only native agent formats evidenced by existing project profiles.
# Status: active; date: 2026-10-19.
"""Host renderers; model IDs are never silently substituted."""
import hashlib
import json
from _agent_sources import SUBAGENTS
from _devtools import DATE

BEGIN, END = '<!-- AGENTS:BEGIN -->', '<!-- AGENTS:END -->'
MARK = 'GENERATED from agents/ - edit the source'


def outputs(root, roles, hosts):
    result = {}
    digest = hashlib.sha256(''.join(p.read_text() for p in
        sorted((root / 'agents').glob('*')) if p.is_file()).encode()).hexdigest()[:12]
    rows = [BEGIN, f'<!-- {MARK} -->',
            f'TL;DR: Development-only roles; manager is the main session.',
            f'Status: generated; date: {DATE}; source: {digest}.', '',
            '| Role | Model | Reasoning | Soft turns | Source |', '|---|---|---|---|---|']
    for name, (role, body) in roles.items():
        model = hosts['codex'][role['tier']]
        rows.append(f"| {name} | {model} | {role['reasoning']} | {role['max_turns']} | agents/{name}.md |")
        if name not in SUBAGENTS:
            continue
        instructions = (f"{MARK}\nSource: agents/{name}.md\n"
            f"Soft turn target: {role['max_turns']}; returns: {role['returns']}.\n"
            f"Tools policy: {role['tools']}. Read task references, not full history.\n{body}\n")
        toml = [f'# TL;DR: {MARK}', f'# Status: generated; date: {DATE}; source: {digest}.',
                f'name = {json.dumps(name)}', f'description = {json.dumps(role["description"])}',
                f'model = {json.dumps(model)}',
                f'model_reasoning_effort = {json.dumps(role["reasoning"])}',
                f'developer_instructions = {json.dumps(instructions)}', '']
        result[root / f'.codex/agents/{name}.toml'] = '\n'.join(toml)
        # Only fields observed in .claude/agents/course-*.md. No guessed effort/maxTurns.
        tools = 'Read, Glob, Grep, Bash'
        if role['tools'] != 'read-only':
            tools += ', Write, Edit'
        # Read-only roles may write their assigned report through Bash, not code.
        claude = ['---', f'name: {name}', f'description: {role["description"]}',
                  f'tools: {tools}', f'model: {hosts["claude-code"][role["tier"]]}', '---',
                  f'TL;DR: {MARK}', f'Status: generated; date: {DATE}; source: {digest}.', '',
                  f"Requested reasoning: {role['reasoning']}; native Claude field unverified locally.",
                  'Model ID acceptance requires a live Claude check; no alias substituted.',
                  f"Soft turn target: {role['max_turns']}; returns: {role['returns']}.", '', body, '']
        result[root / f'.claude/agents/{name}.md'] = '\n'.join(claude)
    rows += ['', 'These roles develop the repo; tutoring uses the separate course-* profiles.',
             'Read agents/manager.md for main-session routing; never spawn a manager.',
             'dev_worker medium reasoning requires an explicitly hard task-plan step and host override.',
             'Claude native reasoning/model acceptance and AGY: see docs/dev-hosts.md.', END]
    return result, '\n'.join(rows)


def merge_section(text, section):
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError('Malformed AGENTS generated markers')
    if BEGIN in text:
        start, end = text.index(BEGIN), text.index(END) + len(END)
        if end < start:
            raise ValueError('Reversed AGENTS markers')
        return text[:start] + section + text[end:]
    return text.rstrip() + '\n\n' + section + '\n'
