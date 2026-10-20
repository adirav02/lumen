TL;DR: Preserve tied optima, distinguish filename hints from dates, and treat lexical matches as advisory.
Status: active; date: 2026-10-20.

# Question correctness

Store every equally optimal value in the private reference. An optional private
rubric `answer_sets` maps skill keys to `{"values":[20,21,22,23,24,25,26,27,28,29,30]}`.
An evidence evaluation with `answer_set_key` checks the actual committed numeric
submission against that full set. It retains the normal identity, work, assistance
and duplicate-evaluation guards. It does not award points or grade other subparts.
Worked solutions still need tutor judgment. Caller correctness conflicting with
the checked set is rejected. No answer sets appear in student output. For the
synthetic stock example all integers 20–30 minimize penalty at 27; the smallest
quantile formula chooses one optimum and must be accompanied by a tie caveat.

A filename year is `filename_years` provenance, with `year:null`. Explicit filename
annotations are normalized to that representation. Date-constrained selection
requires `year_provenance:"verified_exam_date"` plus nonempty `year_evidence`
identifying the reviewed source/date location. An unexplained legacy `year` or a
filename alone never establishes a verified exam date. Reviewer-supplied evidence
is an attestation; the application does not independently authenticate exam dates.

`lexical-question-overlap` is a tutor-only, read-only advisory using case-folded,
Unicode-normalized token-set Jaccard, default threshold 0.45. It compares current
course questions and returns scores/IDs for review, not equivalence assertions or
selection exclusions. Existing exact/numeric-template relation guards remain.
Shared instructions may inflate lexical overlap; paraphrases may evade it.
**No candidates found does not prove novelty.** A large bank may require an index;
this cheap pass is intentionally linear in the current course size.

`source_assumption_notes` remains visible in tutor question metadata. Preserve
resource mappings and conditional independence assumptions when revising questions.
Necessary student premises belong in reviewed stems/shared context, not private
rubrics. The Harbor Final Q6a crane/clerk mapping, Final Q5b and Quiz2 Q3 controller
independence notes remain recorded; none is evidence of learner understanding.
