TL;DR: Development uses one main session; native delegated profiles are archived and no longer deployed.
Status: active; date: 2026-10-26.

# Development host support

Codex, Claude Code and AGY use the same solo workflow in `docs/agents.md` and
`development/agents/manager.md`. Delegate only when the user explicitly requests delegation.
Root `AGENTS.md` loads the shared contract; `CLAUDE.md` imports that loader.

`development/scripts/sync_agents.py` renders only the marked root instruction section. It
removes its own marked retired Codex/Claude development profiles and refuses to
remove unmarked files. It leaves course profiles and host settings untouched.
No AGY development profile format was verified or emitted; sync still emits none.

The four development sources are preserved unchanged in
[the archive](../archive/delegated-agents/README.md), with restoration steps.
`development/agents/hosts.yaml` preserves historical model mappings; it does not select the
already running main-session model or authorize delegation. Archived prompts and
historical benchmark reports are evidence, not active workflow instructions.

Historical checks on 2026-10-19 found that Codex's explorer invocation did not
apply the configured model/effort, Claude IDs/reasoning were unverified locally,
and AGY exposed no verified native profile schema. Restoring profiles requires
fresh host discovery checks rather than assuming static files prove execution.
