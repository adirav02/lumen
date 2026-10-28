TL;DR: Exact bounded Claude/fresh-session handoff using the saved synthetic attempt.
Status: not run in Claude Code; date: 2026-10-28.

# Remaining live-host check

Claude Code was absent from PATH in the 2026-10-28 follow-up. This protocol
requires a real Claude installation and normal user authentication. Do not change
host markers to claim a pass. Run from this repository, with its local candidate
diff and the private task evidence present. No implementation work is delegated.
The historical [Claude protocol](reports/claude-handoff.md) remains historical;
use the current inputs and test wrapper below rather than its obsolete example paths.

```sh
claude --version
.venv/bin/lumen capabilities
# Run the wrapper only if verifying a changed environment/candidate:
.venv/bin/python development/scripts/run_tests.py
mkdir -p .tmp
```

Prepare a new owned restore (never open a real learner workspace):

```sh
.venv/bin/python - <<'PY'
import json, tempfile
from pathlib import Path
from course_tutor.api import LumenCore
run = Path('development/work/20261028-reliability-20261028/live-followup')
workspace = Path(tempfile.mkdtemp(dir='.tmp', prefix='claude-handoff-')).resolve()/'workspace'
LumenCore.restore(run/'host-before.zip', workspace)
checkpoint = json.loads((run/'host-checkpoint.json').read_text())
checkpoint['workspace'] = str(workspace)
output = run/'claude-checkpoint.json'
output.write_text(json.dumps(checkpoint, indent=2))
print(output.resolve())
with LumenCore(workspace) as core:
    print(json.dumps(core.attempt_history('host-smoke', 'integration', checkpoint['attempt_id']), indent=2))
PY
claude
```

Before manual file reads, capture loaded project instructions and available skills
using the host's native inspector. Expect root CLAUDE.md and the shared routing;
record actual discovery, not an assumption from files being present. Invoke the
Lumen skill natively; record if unavailable. Do not invoke subagents.

Give the first conversation this exact bounded request:

> This is a live-host test with fictional work, not real learner performance.
> Use the Lumen skill and public core only. Read
> development/work/20261028-reliability-20261028/live-followup/claude-checkpoint.json.
> Inspect the actual workspace attempt-history for course host-smoke, learner
> integration and the exact checkpoint attempt ID. Before writing, report its
> revision, independent (a) work 2*3+2*4=6+8=14, and prior (b) hint “Multiply your
> earlier result by 3.” Resolve checkpoint source_version_id using read_source_region;
> open the immutable image with your image-capable tool and describe numeric labels.
> Run capabilities against this workspace. Change no learner state yet. Save actual
> command/tool evidence and a compact durable checkpoint; do not edit implementation,
> originals, settings or Git. Do not use subagents. Report unsupported operations.

Exit the host and start `claude` again without resume or copied conversation text.
Give only the checkpoint path plus this request:

> Resume the same paused attempt using its current revision. The simulated learner
> now submits (b): 3*14=42. Record that work_submission for b, then commit evaluated
> correct evidence against its returned event ID using checkpoint topic_id and
> skill_id arithmetic. Pause at the new revision. Read back full history. The exact
> earlier submission/hint/evidence IDs must remain; (a) must stay independent_mastery
> and (b) must be assisted_success. Open the saved source image again. Save actual
> receipts, host/session version and the final checkpoint. Do not create a new attempt.

Return to Codex and inspect the same history through the core. For a different
machine, close the writer, back up through LumenCore.backup, transfer the ZIP and
checkpoint, and restore into a new empty destination; never sync a live SQLite DB.

Capture: native discovery evidence, executable version, both distinct session IDs,
actual capability/history/image tool calls, pre/post histories with unchanged IDs,
mutation receipts, image SHA256/labels, and backup SHA256. The source image labels
are 140 N, 0.50 m and 0.30 m; these expected values cannot replace an image-tool call.
A missing image tool, permission denial, timeout or auth failure leaves that check open.
Keep the independent unseen educational and complete usage/billing gates open.

After verification, preserve a final core backup and receipts in the private task,
close all writers, and remove only the generated `.tmp/claude-handoff-*` directory.
No commit, push, release or remote-setting change is authorized by this protocol.
