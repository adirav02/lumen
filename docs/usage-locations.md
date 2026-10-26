TL;DR: Configure explicit log roots and read measured scope separately from unavailable totals.
Status: active; date: 2026-10-20.

# Usage log locations

`collect-usage` and `watch-usage` accept repeatable `--usage-log-location PATH`
flags or a JSON `log_locations` list for Codex logs. Locations can be files,
session directories or whole Codex homes, including outside this project.
`LUMEN_USAGE_LOG_LOCATIONS` supplies the same list separated by the platform
path separator (`:` on Linux). Explicit flags override JSON, which overrides
the environment. An unreadable/missing configured root is an error. Existing
`codex_home`, `CODEX_HOME` and default host discovery remain available when no
log locations are configured. Roots apply to Codex; select `hosts:["codex"]`
when measuring that scope alone. Other hosts retain their own home settings.

```sh
.venv/bin/lumen collect-usage -w development/work/my-task/usage \
  --usage-log-location /path/to/codex/sessions \
  --usage-log-location /path/to/codex/archived_sessions \
  -j '{"hosts":["codex"]}'
```

The native per-task collector accepts repeatable `--log-location` flags and the
same environment variable. Its root/descendant ownership, response-ID deduplication
and UTC-window rules are unchanged. Existing verified totals remain reproducible:

```sh
.venv/bin/python development/scripts/collect_native_usage.py --repo "$PWD" \
  --root-thread THREAD --since UTC_START --until UTC_END \
  --log-location /path/to/codex --json
```

`usage_state` is `measured` when usable counters cover the selected log scope,
`partial` when some hosts/tails/records are missing, or `unavailable` when no
usable counters exist. Every report describes scope limits. Unavailable usage
is null, never synthetic zero tokens or cost. Collector file/event counts can
be observed zero; they are not token totals. Native CLI failures return unavailable
with a reason and nonzero exit; ambiguous ownership is never silently guessed.
Snapshot counters remain session-wide and may include inherited context; measured
snapshots do not certify task totals. Billing, hidden retries and image accounting
remain unavailable unless separately observed. The native collector remains strict
about incomplete/malformed per-response records, to preserve verified totals.
