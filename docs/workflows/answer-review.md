# Review submitted answers

Use for work actually submitted for checking. Follow `docs/agents.md`; checking an
answer is not permission to reveal later questions or unattempted subparts. For
help starting an unanswered question, use [tutoring mode](tutoring.md).

Course-provided solved exams and answer keys are reference material, even when
the learner uploaded them. They are not the learner's submitted answers. Establish
which work the learner actually submitted before grading; if authorship/purpose
is unclear, clarify it. Importing or privately checking a reference solution does
not record learner performance or establish that the learner saw the solution.

## Establish which question was answered

Resolve the actual question, source/exercise version, displayed option order, and
learner submission before looking up a key. A letter is meaningful only in that
presentation. An unambiguous verbal answer can be matched to the displayed text.
If identity/order cannot be established, check what is identifiable and ask for
only the missing question/version/image. Never guess the mapping from a source
bank's original letters. Earlier submitted work belongs to its attested exercise
revision and must not be evaluated against a replacement question.

Read the relevant source assumptions, diagrams and rubric caveats. A checked key
supports review but does not overrule a valid proof or counterexample. If the key,
question or extraction is wrong, explain the defect, preserve valid learner work,
and repair affected persisted evidence through `correct_evidence`. Unresolved
grading stays pending rather than becoming an invented numeric score.

## Judge the reasoning that is present

Accept equivalent expressions and valid alternative methods. Check only the
requirements that the problem actually asks for. Depending on the subject, that
may include assumptions, a model/state definition, initial conditions, a transition
or derivation, execution order, units, interpretation, correctness, or complexity.
Use a small example or edge case to resolve a genuine doubt.

Separate concept/model selection, method, counting, algebra, arithmetic, notation,
and unreadability when the work supports that distinction. A stylistic difference
or local notation slip is not automatically a wrong method. For a multiple-choice
answer, distinguish correctness of the selected option from correctness of the
written derivation. Preserve correct intermediate steps even if the final choice
is wrong; do not invent an official partial-credit policy.

Begin with the outcome: what is correct and what needs correction. Locate each
significant error and explain why. For ordinary tutoring review, offer a focused
next step. For an explicitly requested final check/full solution, explain the
necessary correction directly. Keep feedback natural and proportional to the work.

## Points and evidence

Use an official rubric when available; clearly label a generated practice rubric.
Report earned points out of the points actually checked, not out of an entire
unsubmitted exam or an arbitrary 100. If no defensible numerical rubric exists,
give qualitative feedback and retain observed evidence without fabricating a grade.

Tie each evaluation to its committed submission and exact subpart. Record actual
assistance chronologically, including prior same-family exposure. Unknown earlier
help does not establish independence. Do not mark a whole question solved because
it was discussed, printed, generated, or partly attempted.

For diagnostics, use the linked item attempt and the complete shared scoring
contract: applicable evaluated evidence, required-subpart checks, explicit partial
scoring when needed, and pending review for uncertainty. See [the CLI workflow](../lumen-workflow.md).

For ordinary practice, `grade-attempt` records rubric points and feedback only
after applicable evaluated evidence exists. Use revision guards and correction
reasons; old scores and feedback remain in history. See [question tracking](../question-tracking.md)
for the distinct shown/answered/graded/correct fields and paginated attempt history.

## Multiple-choice presentation identity

For an uploaded exam, preserve its actual order and option labels in the reviewed
transcription. For a newly built version, use stable option IDs and persist the
checked display-label mapping with the version's teacher-only rubric metadata,
as described in [practice building](practice-building.md). Read that exact mapping
when checking a label. Re-rendering or reprinting a version must not reshuffle it.
Do not put keys in the student artifact or maintain a second authoritative tracker.
