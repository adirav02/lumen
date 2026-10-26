TL;DR: Host output records how a declaration or marker was obtained; it is not integration evidence.
Status: active; date: 2026-10-20.

# Host detection

`lumen capabilities --host codex` explicitly declares host context. `LUMEN_HOST`
provides the same override; the flag takes precedence. Allowed values are `codex`,
`claude_code`, `antigravity` and `generic_cli`. Invalid declarations fail.
Without an override, recognized host markers select a host. Conflicting markers
or no markers select `generic_cli` with an explanation.

`host_detection.method` is `override`, `marker` or `fallback`; `evidence` names the
flag/environment variable/marker. `verified:false` explicitly means this is not
proof of native tool integration, instruction discovery, images or handover.
No marker values, credentials or thread identifiers are returned. Marker tests
are simulations. Live integration claims still need independent smoke evidence.
