# Module 5 data dictionary

All records are synthetic teaching inputs, not participant measurements. Distinct case ids must remain separate. Missing current_RIR in DP-D is unknown, not zero. DP-F reports only two of three prescribed sets. Comparable is a supplied task-comparison assertion; it is not inferred from matching kilograms. Progression requires two different consecutive exposures, not duplicate rows of one exposure.

M05_progression_cases.csv: external total load/increment in kg, repetitions per set, RIR in repetitions, positive integer prescribed set count, explicit comparability/concern fields. The two exposures are assumed distinct and consecutive in these synthetic cases.

M05_mesocycles.csv: proposed weekly DIRECT sets for ONE selected target category; not completed sets, whole-body physical sets, or fractional sets. Week 6 uses ceil(week 5×0.5). RIR targets are planning conventions.

M05_schedules.csv: same-day clock intervals; end after start, times within a single day. Boundaries that touch do not overlap for a positive duration. Sleep uses a separate overnight clock convention in the tool.

M05_trend_A.csv:14 consecutive assigned morning body masses. Compare complete adjacent seven-day means; centers 7days apart. Assigned intake 2517.975 kcal/day is a model input. Static 7700 kcal/kg proxy is model-dependent, not measured TDEE or measured fat loss. Missing masses must not become zero.

training_templates.json: three-day template 15 exercise rows×2sets=30 physical work sets; four-day template 24rows×2=48. These are alternative authored candidate structures, not per-muscle counts or personalized prescriptions. Every row requires apparatus/ROM/load convention and individual review. Neither automatically receives the single-category mesocycle ramp.

capstone_cases.json: null override in CAP-A means use MSJ 1805×1.55; CAP-B explicitly overrides TDEE with 2800. Branch constant is explicitly supplied. Body-fat-derived FFM is an estimate, not directly measured muscle. Exported snapshots remain proposed scenarios, not completed training logs.
