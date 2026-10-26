TL;DR: Verbatim legacy roadmap: 12. Evaluation protocol.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 12. Evaluation protocol

Build a representative sample including a text PDF, scan, slide deck, formula/table, diagram, submitted solution image, and an exam when available. Confirm reference answers and source locations. Keep some questions held out from retrieval/prompt tuning.

Under the same model and checking protocol, compare complete relevant source content, structured retrieval, and summary-only retrieval. Summary-only is a failure probe, not the intended product design. Keep failures and retries in the result set.

Report task correctness, assumption preservation, source-location accuracy, retrieval sufficiency, repeated calls, uncertainty handling, restore behavior, total usage, and latency. Report critical failures separately from averages. Choose the configuration with lower measured cost among those meeting the agreed correctness gate; do not optimize a short payload that increases wrong answers or retries.

An evaluation gate may be strict for known critical fixtures without pretending that zero fixture failures proves general reliability. Further statistical claims require larger representative data.

