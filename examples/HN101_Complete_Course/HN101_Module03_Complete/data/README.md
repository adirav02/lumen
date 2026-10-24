# Module 3 data dictionary

All records are synthetic. They are not participant observations or exercise recommendations.

## M03_week_A.csv and M03_week_B.csv

Each row is an exercise within a session; completed_work_sets counts physical completed work sets, not warm-ups. assigned_direct_target and assigned_indirect_target are declared coarse classroom assignments, not measured shares of stimulus.

A blank indirect field means no indirect target assigned in this simplified record. The explicit not_assigned entry for squats makes omitted contributions visible. Neither asserts that other muscles biologically perform no work. An importer should retain the supplied classification rather than silently invent anatomical targets.

WEEK-B is a separate comparison case: curls change from 2 to 4 sets; every other row matches WEEK-A. It is not a correction superseding WEEK-A. Do not merge the versions into one week.

Physical work-set totals: A 28, B 30. A per-muscle weighted count may count a compound exercise toward multiple categories and is not a physical-set total.

## M03_rir_calibration.csv

estimated_rir is a hypothetical report before continuation; supplied_additional_valid_reps is the stipulated hypothetical continuation outcome. Error is estimate minus supplied outcome, in repetitions. This is a paper exercise; no actual failure test is requested.

## M03_max_cases.csv

load_kg is total external load under a consistent assumed convention. completed_reps describes the fictional performed set; equation_reps_input is the number actually supplied to the model.

For MAX-C only, equation_reps_input=10 is a declared hypothesis based on 8 completed + 2 estimated reserve. MAX-A and B have blank reserve because no exact RIR report is supplied; near-limit is an assumption, not a measured zero. Unknown is not zero.

## Frequency and time

Count distinct relevant session IDs, not exercise rows, for per-week exposure frequency. A four-set block contains three adjacent-set rests under the lesson definition. No whole-session warm-up/transition duration is supplied by these CSVs.
