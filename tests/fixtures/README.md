TL;DR: Test-owned generated material; no real course content or learner data.
Status: active; date: 2026-10-20.

# Synthetic test fixtures

Small text and checked question/case definitions preserve the original synthetic
regression contracts independently of the deleted example collection. The test
session recreates tiny PDF, PPTX and graph fixtures with local dependencies only.
Binary output is ignored. These are deterministic application-policy fixtures,
not evidence of real students, host integration or model accuracy.

`installed/lecture.txt` is the tracked, lightweight installed-distribution smoke
source: three structured units with resolvable title-based prerequisites and an
explicit Bayes assumption. `scripts/smoke_installed.py` copies it outside the
checkout before ingestion. The standalone `demo.py` owns separate inline sample
data and never loads test fixtures. Existing HN101 hash-bound regressions retain
the tracked fictional example originals because the implementation's reviewed
constraints are keyed to those exact bytes; do not regenerate those originals.

Native usage archive tests generate synthetic JSONL in temporary directories;
they never discover developer session logs or depend on personal archives.
