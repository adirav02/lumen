TL;DR: Verbatim legacy roadmap: 7. Retrieval and token efficiency.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 7. Retrieval and token efficiency

Start with FTS5/BM25, course/topic/source filters, and a multilingual alias map. BM25 is a lexical ranking score, not a probability of relevance or truth. Keep formula text unchanged; any search normalization is derived data. Evaluate Hebrew phrasing and math notation explicitly.

Load compact context at session startup. Retrieve metadata first, then complete relevant units and their necessary dependencies. Expand to another unit or original page when the retrieved material is insufficient, contradictory, or uncertain. Do not enforce a fixed top-k or token cap that drops a required assumption.

Filter and aggregate in code before returning data. Update only changed records; avoid rereading the entire course or rewriting all learner history. Cache by content/policy revision and invalidate on relevant changes. Use clear text for explanations and compact structured payloads for operations; measure formats with actual content before adopting TOON or another encoding.

Measure total cost per correct completed task, including prompts, tool schemas/results, follow-up calls, vision/OCR, retries, and output. Distinguish provider-reported usage from tokenizer estimates and actual billed cost. Unknown billing data stays unknown. Token counts from different tokenizers are not interchangeable monetary costs.

Semantic search, reranking, or provider-specific prompt caching enters the plan only after a measured retrieval or cost problem justifies it.

