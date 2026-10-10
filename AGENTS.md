# Project instructions loader

Before working on this project, read and follow [docs/agents.md](docs/agents.md).
It is the canonical shared instruction file for this project. Use `goal.md` for
product requirements and the relevant section of `plan.md` for implementation.

Keep this loader short. Do not duplicate the canonical rules here or add
provider-specific storage or assessment behavior.

## Verified Development Commands

```bash
# Setup virtual environment and dependencies
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Inspect system and core capabilities
.venv/bin/lumen capabilities

# Run full test suite
.venv/bin/pytest

# Run synthetic probability demo
.venv/bin/python demo.py
```
