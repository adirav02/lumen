# TL;DR: Render the solo workflow reference without emitting native subagent profiles.
# Status: active; date: 2026-10-19.
"""Maintain the generated root instruction section; archives are never deployed."""
import hashlib
from _devtools import DATE

BEGIN, END = '<!-- AGENTS:BEGIN -->', '<!-- AGENTS:END -->'
MARK = 'GENERATED from agents/ - edit the source'


def outputs(root, roles, hosts):
    """Render the main-session reference only; no native subagent deployment."""
    digest = hashlib.sha256((root / 'agents/manager.md').read_bytes()).hexdigest()[:12]
    rows = [BEGIN, f'<!-- {MARK} -->',
            'TL;DR: One agent completes the whole task by default.',
            f'Status: generated; date: {DATE}; source: {digest}.', '',
            'Read agents/manager.md for the main-session workflow.',
            'Delegate only when the user explicitly asks for delegation.',
            'Development subagent profiles are preserved in archive/delegated-agents/.',
            'sync_agents.py deploys no Codex, Claude Code or AGY development subagents.', END]
    return {}, '\n'.join(rows)


def merge_section(text, section):
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError('Malformed AGENTS generated markers')
    if BEGIN in text:
        start, end = text.index(BEGIN), text.index(END) + len(END)
        if end < start:
            raise ValueError('Reversed AGENTS markers')
        return text[:start] + section + text[end:]
    return text.rstrip() + '\n\n' + section + '\n'
