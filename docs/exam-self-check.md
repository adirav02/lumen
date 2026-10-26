TL;DR: The same agent verifies exam correctness, layout, reproduction and cleanup before reporting done.
Status: active; date: 2026-10-26.

# Exam completion self-check

Complete every applicable check with evidence in the private task report or exam
manifest before delivering the paper. Mark genuine blockers explicitly; do not
claim an incomplete exam is done. This self-check applies to every course.

1. Compare section structure, question counts, types, points and topic allocations
   with the saved blueprint and original source papers. Record any authorized
   deviations; do not infer the source structure from bank labels alone.
2. Independently recompute every selected question's answer/key from its actual
   wording and assumptions. Verify option mappings after shuffling. A retrieved
   official key or prior validation flag alone does not satisfy this check.
3. Compare every selected question with the others: no question may depend on
   another selected question or reveal its answer. Check shared setups, references,
   option text and solution cues, beyond family or lexical duplicate filters.
4. Render and inspect every student PDF page. No original source question numbering
   may appear in the paper, including citations and cross-references. Use local
   exam numbering and retain exact source numbering privately. Instructions and
   duration must be printed; derive them from the blueprint/source or an explicitly
   recorded assumption. Check formulas, diagrams, options and absence of keys.
5. Save the seed, blueprint, relevant bank/history snapshot and generator revision.
   Restore a backup into a fresh verification clone under repository `.tmp/` and
   rerun assembly with the saved seed and the same pre-assembly state. Compare
   selected revisions, order, option mappings and student paper. Record rendering
   version differences if byte-identical PDFs cannot be obtained. Snapshot re-export
   is a separate check; it does not prove seeded assembly reproduction.
6. From the same restored pre-assembly state, try three other recorded seeds.
   Compare selection and order/mappings separately. If they give the same exam,
   report that and explain the actual cause, such as forced blueprint slots or
   insufficient eligible families. Do not claim variety from the existence of a
   seed parameter. Reusing a request ID/result or changing reservations is not a
   valid seed probe. Do not record these probes as learner exposure.
7. Compare original uploaded file hashes with the before-run inventory; every
   original must be unchanged. Record the inventory and comparison result.
8. Remove owned leftovers from cancelled runs and every verification clone on
   success, failure or cancellation. Use `tempfile.TemporaryDirectory(dir='.tmp')`
   or `try/finally` cleanup. Never create verification clones in `.lumen/` or
   `work/`. Use public cancellation/recovery operations for publication jobs and
   reservations; do not delete arbitrary live learner state. Preserve intended
   deliverables, private verification evidence and usage records.

The general development completion check also covers the task brief, final diff,
relevant tests and documentation checks. For non-exam tasks record exam-only checks
as not applicable; do not fabricate a paper, seed probe or original-file review.
