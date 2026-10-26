# TL;DR: Retire generated development profiles and sync the solo instruction section.
# Status: active; date: 2026-10-19.
"""Disable development subagent deployment; --check performs no writes."""
import argparse
from pathlib import Path
from _agent_render import MARK, merge_section, outputs
from _agent_sources import RETIRED_ROLES, sources
from _devtools import ROOT, write_generated


def sync(root, check=False):
    roles, hosts = sources(root)
    files, section = outputs(root, roles, hosts)
    agents = root / 'AGENTS.md'
    old = agents.read_text()
    updated = merge_section(old, section)
    retired = [root / folder / (role + suffix)
               for folder, suffix in (('.codex/agents', '.toml'), ('.claude/agents', '.md'))
               for role in RETIRED_ROLES
               if (root / folder / (role + suffix)).exists()]
    for path in retired:
        if not any(marker in '\n'.join(path.read_text().splitlines()[:15])
                   for marker in (MARK, 'GENERATED from agents/ - edit the source')):
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
            try:
                path.unlink()
            except OSError as exc:
                print(f'BLOCKED removing generated profile {path}: {exc}')
                ok = False
    if old != updated:
        if check:
            print('OUTDATED AGENTS.md generated section')
            ok = False
        else:
            agents.write_text(updated)
    print('Solo instructions synced; development subagent deployment disabled.')
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
