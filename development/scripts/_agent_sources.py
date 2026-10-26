# TL;DR: Parse the deliberately small role and model mapping formats without YAML deps.
# Status: active; date: 2026-10-19.
"""Only scalar frontmatter and tier: {model: ID} mappings are supported."""
import re

# Archived roles are never read or deployed, even if copied back into development/agents/.
RETIRED_ROLES = ('dev_explorer', 'dev_worker', 'dev_planner', 'dev_reviewer',
                 'explorer', 'worker', 'planner', 'reviewer')
ROLES = ('manager',)
REASONING = {'low', 'medium', 'high'}  # Verified local Codex model cache, 2026-10-19.


def sources(root):
    roles = {}
    required = {'name', 'description', 'tier', 'reasoning', 'tools', 'max_turns', 'returns'}
    for name in ROLES:
        text = (root / 'development/agents' / f'{name}.md').read_text()
        _, front, body = text.split('---', 2)
        data = dict(line.split(': ', 1) for line in front.strip().splitlines())
        if set(data) != required or data['name'] != name:
            raise ValueError(f'Invalid frontmatter for {name}')
        if data['reasoning'] not in REASONING or not data['max_turns'].isdigit():
            raise ValueError(f'Invalid reasoning or max_turns for {name}')
        if data['tier'] not in {'cheap', 'mid', 'strong'}:
            raise ValueError(f'Invalid tier for {name}')
        if data['tools'] not in {'read-only', 'scoped-edit', 'edit-and-test'}:
            raise ValueError(f'Invalid tools for {name}')
        if len(text.splitlines()) > 60 or '\n' in data['description']:
            raise ValueError(f'Role too large: {name}')
        roles[name] = (data, body.strip())
    hosts, host = {}, None
    for line in (root / 'development/agents/hosts.yaml').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if re.fullmatch(r'[a-z-]+:', line):
            host = line[:-1]
            hosts[host] = {}
        else:
            match = re.fullmatch(r'  (strong|mid|cheap):\s*\{model: ([\w.-]+)\}', line)
            if not match or host is None:
                raise ValueError(f'Unsupported hosts.yaml syntax: {line}')
            hosts[host][match[1]] = match[2]
    for host in ('codex', 'claude-code'):
        if set(hosts.get(host, {})) != {'strong', 'mid', 'cheap'}:
            raise ValueError(f'Missing tier mapping for {host}')
    return roles, hosts
