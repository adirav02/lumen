# Usage and cost log

`lumen record-usage -w <directory>` appends a measurement event to
`<directory>/usage.jsonl`. `lumen usage-summary -w <directory>` prints a readable
JSON report. Use `-j '{"run_id":"..."}'` to filter the summary. The log is plain
UTF-8 JSON Lines: open it in an editor, or save the summary as a JSON file.

Automatic collection supports all three host adapters. Their data has different
scope, so the report keeps context windows, transcript totals and conversation
counters separate. Only counters and selected metadata enter the ledger.

| Host | Automatic route | Current evidence |
|---|---|---|
| Codex | Poll project-matched local rollout logs | Actual local sessions |
| Claude Code | Native status-line callback; watcher can also read project transcripts | Configured here; fixtures/subprocesses tested; Claude executable unavailable |
| Antigravity CLI | Native status-line callback; measured headless launcher | Both exercised in actual CLI 1.4.2 |
| Antigravity desktop app | Poll native project metadata and matching local transcripts; hooks are optional | Actual app conversation captured through metadata-scoped polling; hook delivery failed the first live check |

## Automatic Antigravity desktop app capture

Enable this separately from CLI capture, from the repository root:

```bash
.venv/bin/lumen configure-usage -w .lumen -j '{"hosts":["antigravity-app"]}'
```

This installs a named entry in ignored, project-local `.agents/hooks.json`,
preserving other hooks and backing up existing settings. However, a restarted
Antigravity desktop 2.24.0 session produced a transcript without a hook snapshot.
Hook configuration alone is therefore not sufficient evidence of automatic capture.

The verified fallback discovers conversations from the desktop app's native
`conversation_summaries.db`, reading only conversation IDs, workspace URIs and
surface metadata. It opens a transcript only after its workspace exactly matches.
Titles, previews, search-index text and conversation database bodies are not read.
Run a single collection or a continuous watcher:

```bash
.venv/bin/lumen collect-usage -w .lumen -j '{"hosts":["antigravity-app"]}'
.venv/bin/lumen watch-usage -w .lumen -j '{"hosts":["antigravity-app"],"poll_seconds":5}'
```

On this machine a user systemd service,
`lumen-antigravity-usage-5622d24b2597.service`, runs the watcher every five seconds
and is enabled for subsequent user logins. It was installed explicitly for this
workspace after the failed hook test; ordinary setup/summary commands do not
install background services. Inspect with `systemctl --user status
lumen-antigravity-usage-5622d24b2597.service`; stop and disable with `systemctl
--user disable --now lumen-antigravity-usage-5622d24b2597.service`.
The configured Python environment must remain available.

Read saved snapshots with `.venv/bin/lumen usage-summary -w .lumen`. This does
not add a counter to the desktop app's chat UI. Both polling and hooks use the
same snapshot identity so they cannot add the same counters twice.

Capture requires an exact workspace match and desktop conversation/transcript
identity; shared multi-workspace sessions and CLI/IDE callbacks are excluded.
Only `MODEL` / `PLANNER_RESPONSE` counters are included, with the latest record
per step replacing earlier fragments. An incomplete final line is deferred.
Chat text, tool arguments and thinking text are never copied into the ledger.
Raw input/output/cache counters remain visible under `reported_usage`.
Inclusive input stays unknown when cache reads are nonzero or absent, because
the native transcript's cache inclusion semantics have not been established.
Snapshots are transcript totals, not billing receipts or complete retry/image
accounting. Historical/fork sessions are not pooled.

The actual practice conversation was captured into the real ledger through native
workspace metadata and the running watcher. Native hook delivery remains unverified. Restore the returned backup to undo an existing-settings
change; otherwise remove only the `lumen-desktop-usage` hook entry.
The hook interface and paths follow the official
[Antigravity hooks documentation](https://www.antigravity.google/docs/hooks).

## Enable Claude and Antigravity callbacks

From the repository root, run once after installing Lumen:

```bash
.venv/bin/lumen configure-usage -w .lumen
```

This has already been done on the current machine. On a friend's machine or a
moved/reinstalled checkout, run it again. Use `-j '{"hosts":["claude"]}'` or
`-j '{"hosts":["antigravity"]}'` to configure one host. Optional `project_path`,
`claude_home` and `antigravity_home` select explicit locations.

Claude configuration goes in `.claude/settings.local.json`, which is ignored by
Git; its global settings are unchanged. Antigravity CLI uses its documented global
`~/.gemini/antigravity-cli/settings.json`; the callback records only sessions whose
launch project matches this checkout. Existing active display commands are chained with
the same input, and unrelated settings remain intact. Existing files are backed
up byte-for-byte under the settings directory's private `.lumen-usage-backups/`
folder before atomic replacement. Setup returns the actual paths and backup path,
uses a file lock, and is idempotent. Disabled previous display scripts are not
reactivated. If a later host fails setup, the error includes
which earlier configurations succeeded. Restore the returned backup to undo an
existing-settings change; for a newly created local file remove its `statusLine`
entry. No database schema or learner evidence is changed.

A callback invokes the installed Python module, so the configured Python path must
remain available. Existing host sessions may need restarting to load settings.
The callbacks write directly to `.lumen/usage.jsonl`; they do not need a separate
watcher. They retain host permissions and send no data to an external collector.

### Claude accounting

The native callback uses Claude's transcript when available, verifying its own
working directory. The watcher also discovers logs under project-specific
`CLAUDE_CONFIG_DIR`/`~/.claude/projects/` directories, including separate child
transcripts. Streamed records are deduplicated by assistant message ID; the latest
usage replaces earlier fragments. Inclusive input is uncached input plus cache
creation plus cache reads. If required cache fields are missing, inclusive input
stays unknown and available raw counters remain visible. Child files remain
separate; do not pool possibly inherited histories into a grand total.

When no usable transcript is available, the callback records only the status
line's context-window counts, labeled `usage_scope:"context_window"`. These are
not total session consumption. `cost.total_cost_usd`, when supplied by the host,
is stored as `estimated_cost_usd`; it is not a billing receipt. Session duration
is separate metadata. No cost or model is inferred from an account subscription.

### Antigravity accounting

The native callback captures Antigravity CLI's context-window counts on state
changes and labels them accordingly. It does not infer cumulative consumption
from shrinking/compacted context windows or quota percentages. It targets the CLI;
IDE/app usage is not established by these tests.

For headless runs, the measured launcher records the final native JSON usage:

```bash
.venv/bin/python -m course_tutor.host_usage antigravity-run \
  --project "$PWD" --log "$PWD/.lumen/usage.jsonl" -- \
  --mode plan -p 'Your task here'
```

The launcher supplies `--output-format stream-json`, relays native output to your
terminal and saves only usage metadata. It verifies the stream's initial project
and conversation identity, records terminal results including failed results with
valid usage, and preserves native failure exit codes. Missing/invalid terminal usage
is reported as capture failure, even if the child exits zero. Per-step updates
are not added to cumulative result totals. Continued runs with the same native
conversation retain their identity; snapshots do not add cumulative values twice.

`reported_usage` retains the native input/output/thinking/cache/total counters.
The published examples do not establish consistent cache inclusion for every
exposed format. This adapter therefore leaves normalized inclusive input unknown
when cache reads are nonzero, while retaining raw counts; it does not guess by
adding or subtracting cache. If cache reads are explicitly zero, the reported
input can be used directly. Thinking tokens are a subset of output. Context and
conversation snapshots remain visible side by side under their distinct scopes.

Native interfaces used: [Claude status-line fields](https://code.claude.com/docs/en/statusline),
[Claude transcript paths](https://code.claude.com/docs/en/hooks),
[Antigravity status line](https://antigravity.google/docs/cli/statusline), and
[Antigravity JSON output](https://antigravity.google/docs/cli/headless/).
See [adapter evidence](evaluation/host-usage-2026-10-19.json). Claude runtime
validation remains open; generated fixture payloads are not a live Claude test.

## Automatic Codex collection

From this repository root, run this once in a terminal and leave it running:

```bash
.venv/bin/lumen watch-usage -w .lumen
```

The watcher polls Codex and Claude transcripts every five seconds and notices
native callback updates in the shared log. It appends changed snapshots to
`.lumen/usage.jsonl`. Press Ctrl+C to stop. View the latest saved counters in
another terminal:

```bash
.venv/bin/lumen usage-summary -w .lumen
```

For a single collection pass, run `lumen collect-usage -w .lumen`. Optional JSON
parameters are `project_path` (defaults to the launch directory), `codex_home`
(defaults to `CODEX_HOME` or `~/.codex`), `claude_home`, and `hosts` (a list selecting
`codex`, `claude`, and/or `antigravity`; all three by default). The watcher additionally accepts
`poll_seconds` (0.05–30) and `duration_seconds` (omit for continuous operation):

```bash
.venv/bin/lumen watch-usage -w .lumen -j '{"poll_seconds":5,"duration_seconds":60}'
```

Discovery checks each rollout's session metadata first and reads usage only when
its recorded working directory resolves to the requested project root. It does
not traverse unrelated transcript bodies. Sessions launched from other working
directories are excluded; point `project_path` at the actual launch directory for
those runs. Separate subagent/fork sessions remain separate, even if their
counters include inherited history. No grand total across sessions is inferred.

The collector reads `total_token_usage`, input/cache/output/reasoning counts,
observed model names, provider, session identity and usage timestamps. Snapshot
identity is stable across rescans/restarts and concurrent writers. The summary
shows the **latest snapshot per host/session/scope**, retaining previous snapshots in the
ledger without adding them together. Cached input is part of input; reasoning
output is part of output. Model names come from observed turn contexts, not a
claim that every counter belongs to the last model configured.

These are host-reported cumulative session counters. They cover the host session,
including development conversation, rather than only Lumen tutoring operations.
They do not expose reliable per-request counts, every internal retry, image
counts, latency or actual billing. Hidden activity stays unknown and collection
remains partial; a snapshot cannot support billed cost per correct task. A
subscription price is not a measured task charge.

For deterministic task accounting on logs containing native `token_usage_record`
entries, run `python3 scripts/collect_native_usage.py --repo /path/to/repo
--root-thread ID` (on one line). Alternatively use `--since UTC --until UTC`;
a window must identify exactly one active root, otherwise supply its ID.
`--task work/YYYYMMDD-slug` defaults to status.json's `started_utc`/`ended_utc`;
explicit timestamps override them. Both endpoints are inclusive and require UTC.
The script reads local `sessions/` and `archived_sessions/` under `CODEX_HOME`
(or `~/.codex`), follows explicit `source.subagent.thread_spawn.parent_thread_id`
links, and reports each thread/role plus a total. Native `payload.usage` is keyed
by `response_id`; tool records use `call_id` (or their native `id`). Copies are
deduplicated; conflicting identities, missing counters and malformed logs fail.
Root counters exclude children; the total adds root and descendants. Cached
input is included in input, fresh input is input minus cached, and reasoning
is included in output. No events file or LLM call is needed. Older logs lacking
native per-response records cannot supply this report; cumulative snapshots
remain available through the application collector described above.

The adapter targets the observed local Codex rollout JSONL format, which is
version-dependent. Incomplete final lines are deferred to the next poll; malformed
complete lines or incompatible usage schemas produce explicit collector errors
without copying source contents or silently inventing counters. Missing logs or
counters report zero matched sessions, not zero actual usage. Ordinary CLI calls
and summary reads do not install a service or start background collection; start
the watcher once for the period you want to observe. Local permissions can limit
what is visible. The polling commands do not change host settings; the explicit
`configure-usage` operation installs the native callbacks described above.

Codex also documents opt-in [OpenTelemetry export](https://learn.chatgpt.com/docs/config-file/config-advanced#observability-and-telemetry).
Claude also offers [request/token/cost telemetry](https://code.claude.com/docs/en/monitoring-usage)
for richer exports, including estimated cost and incomplete visibility of internal
retry attempts. The current adapters do not claim full per-request coverage.

The [current collection report](evaluation/codex-usage-2026-10-19.json) retains
numeric evidence with no conversation text. The earlier [validation log](evaluation/usage.jsonl)
retains its initial unavailable-telemetry note and a later correction: host
counters were subsequently found in local logs. Those were not direct per-call
API or billing receipts. No counter has been reconstructed from payload lengths.

## Record a call

Record every provider call, including failed/interrupted calls, retries, tools,
vision/OCR and subsidiary model calls. Count full provider-reported input/output,
including tool context; do not add locally estimated tool text a second time.
Use exact host/provider/model identifiers where exposed, otherwise say unavailable.
Each retry has its own event ID and references the previous call's event ID.
Unknown image counts or latency use null, not zero. Zero means observed none.

The following is a **synthetic example**, isolated from the real validation log:

```bash
.venv/bin/lumen record-usage -w scratch/usage-example -j '{"kind":"call","event_id":"example-call-1","run_id":"example-run","task_id":"example-task","host":"example","provider":"example","model":"synthetic","status":"completed","usage_source":"unavailable","input_tokens":null,"output_tokens":null,"cached_input_tokens":null,"image_count":1,"latency_ms":null,"retry_of":null,"cost_usd":null,"cost_source":"unavailable","source_note":"Synthetic command example; no provider telemetry or bill available."}'
.venv/bin/lumen usage-summary -w scratch/usage-example
```

For an actual call, supply `usage_source` as `provider_reported`, `host_reported`, `estimated`, or
`unavailable`. Token counts are nonnegative integers or null. Cached input is a
subset already included in input, never added twice. Identify the relay/source in `source_note` when using `host_reported`. When a provider separates
uncached and cached input, normalize to their total and describe the conversion
in `source_note`. With unavailable token telemetry, all token fields must be null.
Keep estimated/tokenizer counts in separate groups from provider counts.

`cost_source` is `billed`, `estimated`, or `unavailable`. `cost_usd` is a finite
nonnegative USD number, or null when unavailable. Billed means a documented
per-call charge, with receipt/export reference in `source_note`. A price-table
calculation is estimated; describe the rate/date/cache/image treatment. If billing
is only available at session level and cannot be attributed per call, retain that
export and record the limitation in a run note; do not distribute it arbitrarily.
Image counts are not image tokens or an image surcharge; include actual charges
in the provider's total cost once. No live pricing assumptions are built in.

## Reviewed outcomes and completeness

Once a task is checked against a reference, append its outcome:

```bash
.venv/bin/lumen record-usage -w scratch/usage-example -j '{"kind":"task","event_id":"example-review-1","run_id":"example-run","task_id":"example-task","outcome":"correct","reviewer_reference":"generated:checked-example","source_note":"Synthetic example only; a real review must identify the checked reference and reviewer artifact."}'
.venv/bin/lumen record-usage -w scratch/usage-example -j '{"kind":"run","event_id":"example-collection-1","run_id":"example-run","collection_status":"partial","source_note":"Synthetic example; real per-call coverage and billing are unavailable."}'
```

Outcomes are `correct`, `incorrect` or `pending`. Correct means the completed task
meets its checked reasoning/assumption/feedback criteria, not just a matching final
number. Keep inaccurate results and retries. Append a new task event to correct
an outcome; the latest outcome applies and old events remain. Call records are
immutable: reuse an event ID to retry saving the same observation, not to change
its measurement. A conflicting event ID is rejected. If a call was mismeasured,
preserve that run as invalid/partial and create a corrected run from documented
source telemetry; filter to that run rather than pooling duplicates.

Only declare `collection_status:"complete"` after all calls, retries, images and
outcomes are accounted for. The latest run declaration must follow the last
call/outcome; later events reopen collection until another declaration. Unknown
per-call fields can remain unknown even when the list of calls is complete.
If the host exposes no per-call list, record just a partial run note, never a
fabricated call count. A run with zero logged calls does not mean zero actual calls.

Manually recorded call summaries separate known billed and estimated costs, unknown-cost call counts,
token provenance groups, images, latency, retries, incorrect and pending tasks.
Known sums omit unknown values and are not full totals. Billed cost per correct
task is null unless collection is complete, every task has calls and a final
review, at least one task is correct, and every logged call has a billed cost.
The numerator includes costs of incorrect tasks, failures and retries too.

## Persistence and portability

The append/read lock serializes local processes. Successful append responses
follow flush/fsync. A truncated/invalid line stops further recording and reporting
with a line-numbered error; preserve the file before repairing it from telemetry.
Do not silently skip damaged lines or invent missing data.

The measurement log is separate from authoritative SQLite learner state. Core
backup/restore includes database and referenced sources, **not this ledger or
run transcripts**. Close writers and copy these separately with the handoff
checkpoint; this matters for cross-machine tests. Use `scratch/` for local logs
and keep only intentionally reviewed, nonsensitive evidence under `docs/evaluation/`.
The CLI never changes learner scores or topic state when recording measurements.


## Task-facing usage notes

Present the deliverable first and usage separately. A usage counter is not the
task result, and tracker health belongs in diagnostics only when requested.
For example, if a test was only saved as an assessment, report that PDF delivery
is still incomplete; do not claim a PDF or randomized option order was produced.

For an identified associated session, a concise note can read:

> Task: Assembled a three-question source-based test; PDF delivery pending.
> Session usage: 99,213 input / 9,875 output / 753,273 cache-read tokens.
> Saved counters match the session transcript. Cache inclusion in reported input
> is unknown; these raw counters are not added together.

These are session counters, not proven per-task API charges. If a session contains
other work, say so rather than assigning all its consumption to one task. Do not
infer session identity from whichever concurrent session is latest. A billed cost
requires billing evidence; token counts alone are usage, not a dollar charge.


For routine test creation, keep the usage note to one line after the PDF link
and question count. If cache inclusion is unknown, use a short parenthetical
instead of a separate explanation. Omit collector status, audit stories and
session IDs from the learner-facing reply unless the learner asks for diagnostics.
