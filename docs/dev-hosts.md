TL;DR: Local format/model verification and remaining host setup TODOs.
Status: native discovery blocker observed; date: 2026-10-19; based on commit: e840d18.

# Development host support

| Host | Evidence | Result |
|---|---|---|
| Codex files | Existing `.codex/agents/course-*.toml`, `docs/agent-profiles.md` | Generated format matches existing files; this does not prove native discovery. |
| Codex | `~/.codex/models_cache.json`, fetched 2026-10-19, client 0.163.0 | Both requested IDs listed: gpt-6.1-sol and gpt-5.6-terra. |
| Codex reasoning | supported_reasoning_levels on both cached models | low, medium, high accepted; use each role's value. |
| Codex native smoke | CLI 0.163.0, fresh-context explorer, no model/effort override | Actual child was gpt-6.1-sol / medium, not configured gpt-5.6-terra / low. |
| Claude Code | Existing `.claude/agents/course-*.md` | Generate the observed Markdown/frontmatter fields only. |
| Claude Code models | No local executable; existing profiles use aliases only | Requested opus/sonnet/haiku 5-5 IDs are unverified, not confirmed mismatches. |
| Claude reasoning | No locally verified native field | Preserve requested effort in instructions; no guessed config field. |
| AGY models | Live `agy models`, 2026-10-19 | Lists gemini-3.8-flash-low, -medium, -high; all tiers use the same medium-listed ID. |
| AGY reasoning | Local `agy --help` | Session --effort supports low, medium, high, xhigh, max; future adapter must use role effort. |
| AGY profiles | Local `agy help agents` documents listing, not a file schema | Skip native profile generation until the file format is verified. |

## TODOs and assumptions

- User selected Gemini 3.8 Flash. All AGY tiers use `gemini-3.8-flash-medium`;
  its catalog preset does not replace the per-role reasoning policy.
- TODO: verify AGY native role format and application of per-role CLI effort
  before adding an adapter. No unverified AGY profile file is emitted.
- TODO: verify exact Claude IDs in an installed host; do not silently use aliases.
- TODO: verify Claude native reasoning settings and then implement that adapter field.
- Dev roles now use dev_explorer, dev_worker, dev_planner and dev_reviewer to
  avoid built-in names. TODO: verify fresh-session native discovery after renaming;
  the pre-rename explorer smoke failed, so generated files are not proof of loading.
- TODO: smoke-test Claude discovery. Static agreement does not establish native execution.
- Codex cache lists both IDs, but the actual explorer did not apply its profile.
  The exact cause and Terra execution availability remain unverified.
- Codex files use the locally observed model_reasoning_effort field; actual loading
  still needs repair. Claude's effort text is intent, not native enforcement.
- Soft turn targets: dev_explorer 15, dev_worker 20, dev_planner 10,
  dev_reviewer 15, manager 30.
  Native limit fields are unverified; record actual turns and overshoot in benchmarks.
- Manager stays in the main session with the requested mid/medium intent; generated
  role files do not switch its already-running model. No manager subagent is emitted.
- Worker medium effort requires a hard task-plan step and supported invocation
  override; the scaffold does not guess a host command for that override.
- Existing project configuration, telemetry hooks, tutoring profiles and skills stay
  owned by their existing workflows; sync touches only its own files/marked section.
- `hosts.yaml` uses a documented small YAML subset (scalar tier/model maps); the
  stdlib parser deliberately rejects unsupported syntax rather than guessing.
