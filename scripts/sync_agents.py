# TL;DR: Generate development profiles and merge only the marked AGENTS section.
# Status: active; date: 2026-10-19.
"""Sync agent source profiles; --check performs no writes."""
import argparse
from pathlib import Path
from _agent_render import MARK, merge_section, outputs
from _agent_sources import sources
from _devtools import ROOT, write_generated


def sync(root, check=False):
    roles, hosts = sources(root)
    files, section = outputs(root, roles, hosts)
    agents = root / 'AGENTS.md'
    old = agents.read_text()
    updated = merge_section(old, section)
    retired = [root / folder / (role + suffix)
               for folder, suffix in (('.codex/agents', '.toml'), ('.claude/agents', '.md'))
               for role in ('explorer', 'worker', 'planner', 'reviewer')
               if (root / folder / (role + suffix)).exists()]
    for path in retired:
        if MARK not in '\n'.join(path.read_text().splitlines()[:15]):
            raise ValueError(f'Refusing to remove unmarked retired profile {path}')
    # AGENTS.md is hand-maintained outside the delimiters; preserve those bytes.
    ok = True
    for path, text in files.items():
        ok = write_generated(path, text, check) and ok
    for path in retired:
        if check:
            print(f'OBSOLETE generated profile {path}')
            ok = False
        else:
            path.unlink()
    if old != updated:
        if check:
            print('OUTDATED AGENTS.md generated section')
            ok = False
        else:
            agents.write_text(updated)
    print('TODO Claude: verify requested model IDs and native reasoning override.')
    print('TODO AGY: verify native development-profile format; Gemini 3.8 Flash tiers are set.')
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        return 0 if sync(args.root.resolve(), args.check) else 1
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
