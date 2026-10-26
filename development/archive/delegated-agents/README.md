TL;DR: Preserved development profiles; inactive unless delegation is explicitly requested and restored.
Status: archived; date: 2026-10-26.

# Delegated agents archive

The four dev_* profiles were moved here unchanged. In the user-reported HN101
comparison, the solo run produced a better generator at about one third of the
cost; the delegated reviewer found none of the defects. This is the reason for
the workflow choice, not a new independently measured benchmark claim.

One agent now completes the entire task by default. Complexity, unfamiliar code
or a desire for review does not authorize delegation. Course profiles remain
available only for explicit user requests. Archive contents are historical data.

## Restore for an explicitly requested delegated workflow

1. Obtain an explicit user request for delegation and choose only the needed roles.
2. Copy all four dev_*.md files into agents/; preserve these archived originals.
3. Restore scripts/_agent_sources.py, scripts/_agent_render.py and
   scripts/sync_agents.py from pre-archive commit
   `7aab4ec8f7670c64bfc96fd2a490312cffc4ac48`. Inspect the historical diff before restoring.
4. Restrict the restored role list/rendering to the requested roles, reconcile
   the scripts with current changes and update their tests;
   merely copying profiles back does not enable deployment.
5. Run python3 scripts/sync_agents.py, its --check mode, docs checks and the test
   wrapper. Inspect generated Codex/Claude copies and verify actual host discovery.
   Historical tooling emits no AGY profiles; its format still needs verification.
6. Keep delegation explicitly requested; restoring files does not change policy.
