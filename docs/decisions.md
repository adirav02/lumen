TL;DR: Development workflow decisions and their reasons, not application design changes.
Status: active; date: 2026-10-19; based on commit: 935d1ab.

# Development decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-10-19 | Pass references, not content | Keep turns and context small; artifacts retain details. |
| 2026-10-19 | One writer per file | Prevent overlapping edits and ambiguous ownership. |
| 2026-10-19 | Manager is the thin main session | Avoid a second coordinator and repeated broad context. |
| 2026-10-19 | Exact tier/model mapping in agents/hosts.yaml | Keep requested IDs explicit; flag unverified acceptance. |
| 2026-10-19 | Reasoning per role, not tier | dev_worker defaults low; only explicitly hard plan steps allow medium. |
| 2026-10-19 | Dev tooling separate from runtime | Preserve application and learner-state contracts. |
| 2026-10-19 | Generate maps, indexes and host files | Deterministic work needs no model tokens. |
| 2026-10-19 | Exempt the fixed legacy doc inventory from new layout rules | Avoid unrelated content moves, extra navigation and link risk. |
| 2026-10-19 | Skip unverified AGY profile generation | Local CLI hooks do not prove a native subagent format. |
| 2026-10-19 | Limits/scopes are prompt contracts | Existing formats do not prove native turn caps or filesystem isolation. |
| 2026-10-20 | Default to solo for known files and testable criteria; planner only for real design ambiguity or several affected modules; one reviewer pass with criterion evidence, high-severity corrective-diff re-review only | One paired record-results run: solo 2,081,534 input / 98,686 fresh / 36 model calls / 5 of 5 criteria; delegated 2,304,994 / 140,514 / 43 / 3 of 5. Wall time about equal (302.2 vs 303.4 s). This is one pair, not general evidence of superiority; [comparison](evaluation/record-results-comparison.md). |
| 2026-10-26 | One agent completes every task by default; delegation requires an explicit user request; archive four development profiles and require final self-check | User-reported HN101 comparison: better solo generator at about one third of the cost; delegated reviewer caught no defects. No new cost measurement is claimed. |

Append dated decisions with a concrete reason. Split and link before 150 lines.
