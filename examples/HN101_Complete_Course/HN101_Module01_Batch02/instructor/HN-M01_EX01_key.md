---
assessment_id: HN-M01-EX01
content_type: instructor_answer_key
language: en
version: "1.0"
status: current
total_points: 100
---

# Module 1 Examination — Instructor Key

Keep this file outside a student-only or blind-evaluation ingestion run. Answers refer to M01-Q identifiers, not the separate Lesson 1.1 Q identifiers.

| Question | Expected answer and marking |
| --- | --- |
| M01-Q01 | 500 × 4.184 = 2,092 kJ (3 points). kcal/day is a rate (2). |
| M01-Q02 | The label does not establish a measurement (1). Any two of units, method, fasting, prior rest, posture, wakefulness, thermal conditions, calibration or stability, with explanation (2 each). |
| M01-Q03 | No exact fat-gain calculation (2). Body mass does not identify tissue composition and includes fluctuating non-fat components (3). |
| M01-Q04 | Require actual equation or coefficients/version (3), inputs and units/assumptions for reproducibility (2). |
| M01-Q05 | Rows 0–27 describe the 28 intervals ending at morning day 28 (3). There is no following interval in this dataset for row 28 (2). |
| M01-Q06 | No causal measurement finding (2). Curves were generated from equations while changing an input; no measured intervention data (3). |
| M01-Q07 | F = 64 kg (2), MSJ = 1,805 (2), CUN = 1,908 (2), FFM = 1,752.4 kcal/day (2), models changed rather than the person (2). |
| M01-Q08 | F decreases 2.4 kg (2); CUN decreases 52.8 kcal/day to 1,855.2 (3); three percentage points = 15% relative to 20% (2); sensitivity interval covers selected input variation, not all error or a sampling distribution (3). |
| M01-Q09 | Gross 168 kcal (3); standard-rest-net 126 kcal (3); gross contains baseline expenditure already represented in the whole-day baseline, so use a compatible incremental definition or rebuild the accounting (4). |
| M01-Q10 | Window centers 4 and 25, separated by 21 days (3); slope −1.05/21 = −0.05 kg/day (2); 2,400 − 7,700(−0.05) = 2,785 kcal/day, conditional on assumptions (3); 28 is not the separation of these windows (2). |
| M01-Q11 | Total decline 250 (2); expected decline 150 (2); residual −100 kcal/day, or 100 below the prediction (3); changed mass/composition and other modeled factors explain part of the decline, with model/measurement uncertainty (3). |
| M01-Q12 | Five distinct errors, 4 points each: 2 for identifying the error and 2 for repairing it. Use the accepted set below. |

Accepted Q12 error categories:

1. Prediction is labeled measurement; report predicted resting expenditure with the actual equation.
2. RMR is identified with TDEE; distinguish resting from whole-day expenditure.
3. Walking is added on top of a factor already including it; avoid that duplicate.
4. Gross exercise is added to an existing full resting baseline without checking overlap; use a compatible increment.
5. Weekly-window separation is mislabeled as 28 days; use 21 for the means described.
6. The approximate calibration is labeled exact/actual; state the intake and k assumptions and limitations.
7. Missing intake is replaced with zero; flag it and apply an explicit missing-data policy.
8. A one-day plateau is treated as proof of permanent metabolic damage; do not infer that mechanism or permanence from the observation.

Credit at most five categories. Distinguish factor overlap from resting-baseline overlap only when the student clearly explains the two accounting boundaries. Do not award duplicate credit for repeated phrasing of the same error.

Common distractor value: 2,688.75 comes from the deliberately wrong calculation 2,400 + 7,700 × 1.05/28. It is quoted as an error in Q12, not approved as the CAL-A estimate.

## Practice and lab answers

### Lesson 1.2

- L02-P01: Blair MSJ = 700 + 1,031.25 − 150 − 161 = 1,420.25 kcal/day. Lean-mass predictions lack a required input.
- L02-P02: F falls from 64.0 to 61.6 kg; CUN falls from 1,908 to 1,855.2 kcal/day, a decrease of 52.8.
- L02-P03: Mean signed error = 0; mean absolute error = 200 kcal/day. Signed errors cancel.
- L02-P04: Example: “CUN-1980 predicts approximately 1,908 kcal/day using a 64 kg FFM proxy for the lean-mass input; this is not a measured value.”
- L02-P05: Model-generated curves only.
- CASE-ALEX-01: 1,805; 1,908; 1,752.4 kcal/day.
- CASE-ALEX-02: MSJ unchanged; CUN decreases 52.8; FFM-370-21.6 decreases 51.84 kcal/day to 1,700.56.
- CASE-UNIT-01: 176.37 lb = approximately 80.000086 kg; 1.80 m = 180 cm; MSJ approximately 1,805.00 kcal/day. Rounded to the nearest kcal/day, 1,805.

### Lesson 1.3

- L03-P01: WALK-B gross 168; standard-rest-net 126 kcal.
- L03-P02: Gross 147; standard-rest-net 122.5 kcal.
- L03-P03: 2,320 − 2,700 = −380 kcal/day. TDEE already includes the assigned TEF; subtracting it from intake again double counts the same effect.
- L03-P04: Components are assigned synthetic values for two days, not a sampled population.
- L03-P05: Unknown means unobserved or unestimated, not physically absent.
- EST-A: The explicitly inclusive factor already contains usual exercise; no automatic addition.
- EST-B: Baseline overlap exists unless corrected in the accounting.
- EST-C: The model increment over a 1,800 kcal/day resting baseline for 45 minutes; not the standard-1-MET-net value.
- L03-SOURCE01: Code 17016, 4.0 MET, carrying a 5–14 lb load on level ground at moderate pace; a different load, grade, or pace may not match.

### Lesson 1.4

- Four weekly means: 80.20, 79.85, 79.50, 79.15 kg.
- Window-center slope: −1.05/21 = −0.05 kg/day.
- Endpoint slope: (78.95 − 80.35)/28 = −0.05 kg/day. Agreement is designed into the synthetic data, not guaranteed generally.
- CAL-A = 2,785; CAL-B = 2,700; CAL-C = 2,850; CAL-D = 2,935 kcal/day.
- Missing-data variant: day-12 weight absent; intake for interval 19→20 absent. The day-28 blank is structural in both files.
- L04-P01: The endpoint blank refers to no modeled interval; the internal blank refers to an interval that exists but was not observed.
- L04-P02: Estimated expenditure decreases to 2,700 because k changes; observed weights, intake records, and slope remain unchanged.
- L04-P03: Examples: changed movement/expenditure, different actual intake or logging error, fluid fluctuation, model misspecification, insufficient observation duration. A plateau alone cannot isolate a cause.
- L04-P04: False; the mean summarizes measured body mass, not body-fat percentage.
- L04-P05: The number is a conditional estimate for a synthetic dataset, not a personal recommendation or measured requirement.

Suggested mastery: 80/100 with no unresolved confusion between prediction and measurement, gross and net energy, or missing and zero values. This threshold is a course design choice, not a clinical standard.
