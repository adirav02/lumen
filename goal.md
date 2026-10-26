# Course Tutor — Goal

Status: approved product direction; core locally audited, with live Antigravity integration/fresh-session resume and a real-course Codex image-review workflow verified. Release validation remains open for live Claude Code integration, cross-host handover, broader educational evaluation, and measured model usage/cost. See [release checklist](docs/release-readiness.md), [2026-10-18 audit](docs/audit-2026-10-18.md), [Antigravity evidence](docs/antigravity-integration-report.md), and [real-course evidence](docs/real-course-integration-report.md).
Updated: 2026-10-19.
Audience: product owner, implementers, and agents working on this project.

## Completed / remaining / evidence

| State | Work | Evidence / next gate |
|---|---|---|
| Completed locally | Core, CI/package checks, native Claude files, course workflow | [CI review](docs/ci-review.md); historical full validation: 205 tests; current local suite: 298 tests; [release checklist](docs/release-readiness.md) |
| Completed live, bounded scope | Antigravity discovery/resume; Codex real-course image review | [Antigravity report](docs/antigravity-integration-report.md), [Codex report](docs/real-course-integration-report.md) |
| Prepared; awaiting Claude access | Native discovery, CLI execution, images, fresh session | [Friend-ready smoke test](docs/claude-handoff.md) |
| Remaining | Real cross-host attempt/work/assistance handover | [Two-host protocol](docs/claude-handoff.md#cross-host-handover) |
| Partial | Broader educational evaluation | [16 generated reviewed cases](examples/educational_evaluation/README.md); unseen real-host submissions still required |
| All three adapters implemented; Claude runtime pending | Codex counters and Antigravity CLI capture verified; scoped Claude callbacks/transcripts fixture-tested; full measurement remains incomplete | [Usage log and commands](docs/usage-measurement.md); unavailable telemetry remains unknown |
| Planned | Efficient scripted test assembly using the existing question bank | Reusable exam blueprints, seeded selection, compact orchestration, and a quality/usage comparison against the current workflow |
| Enforced in workflow | CI success creates a draft release | [Release checklist](docs/release-readiness.md); publication awaits integration/evaluation evidence |

## Purpose

Build a portable course workspace that turns an existing AI agent into a persistent tutor. A learner supplies course materials, works through exercises, and can request a comprehensive diagnostic. The system retains course knowledge and evidence of the learner's performance across sessions and supported agent environments.

The objective is better understanding and independent problem solving. The assessment must reflect the evidence honestly; it is not a number that must rise after every conversation.

## Required environments

Support OpenAI Codex, Anthropic Claude Code, and Google Antigravity through one shared instruction contract and one storage/tool implementation. Additional environments can implement the same contract. "Universal" means a portable core with explicit environment adapters, not a promise that every chat application can access local files or execute tools.

Instruction discovery, tool execution, source-image access, and durable storage must be checked separately in each environment. Host permissions and instruction precedence remain in force. Provider-specific session memory must not become the authoritative course or learner database.

## Learner experience

1. Create a course and request the syllabus and available learning materials. Past exams and official solutions are optional. Materials can be added later.
2. Preserve the uploaded originals, process their contents, and build a course map. Show missing material and extraction uncertainty before claiming coverage.
3. Offer a diagnostic when requested. Evaluate topics and skills using a coverage plan and checked questions, with no requirement to finish in one session.
4. Inspect the learner's attempted solution and teach according to their preference. Default to focused guidance; reveal a full solution when requested.
5. Persist observed work and assistance during the exercise. On completion or a pause, retain the evidence without grading unseen parts as failures.
6. Show topic-level performance, material coverage, and assistance separately. Offer a next exercise that addresses a documented difficulty, checks an untested area, or revisits a skill.
7. Resume the same attempt and assessment after a new session or a supported environment switch.
8. A request to create a test, exam or practice paper produces a student-facing PDF by default, with rendered mathematics, original-language questions, source citations, private answers excluded and actual visual/print review. Store it under the course directory's `tests/<assessment_id>/` folder. Deliver its file link and question count with at most one known-usage line; do not narrate bank inventories or verification steps unless asked. A database assessment and chat-only questions do not satisfy this requirement; only the learner's explicit format override changes it.

The tutor supports three complementary workflows: natural guidance that builds on
the learner's attempt, fair review of submitted work against its actual version,
and varied practice drawn from checked material and recorded question families.
Explicit requests for a full solution are honored. Feedback follows the chosen
language; reproduced questions retain their source language unless translation is
requested. Exam composition, date limits and repetition preferences are course/user
constraints, not fixed defaults inherited from one subject.

## Agent workflow and completion

One agent completes discovery, planning, implementation, testing and self-check by
default. Delegate only when the user explicitly asks for delegation, including in
tutoring and exam tasks. Development profiles are preserved in
[archive/delegated-agents](archive/delegated-agents/README.md) and are not deployed.

Before delivering an exam, complete [the exam self-check](docs/exam-self-check.md):
match blueprint and source papers, recompute all keys, check question independence,
print instructions/duration without source numbering, verify restore and seeds,
compare original hashes, and remove cancelled-run leftovers and temporary clones.

## Non-negotiable decisions

- SQLite is authoritative for processed course knowledge, attempts, evidence, assessments, and preferences. Original uploaded files remain immutable files with versioned metadata and content hashes.
- Every source-derived knowledge unit links to the exact source version and page, slide, or other location. Generated explanations and questions are labeled as generated.
- Retain full extracted content and source files. A summary is a navigation aid, not the sole basis for a mathematical answer.
- Preserve formula assumptions, symbol definitions, exceptions, and necessary diagrams. Retrieval may expand when correctness requires it.
- Evaluate observed skills and subparts. Distinguish independent work, work after hints, and work after an exposed solution.
- Evidence can be corrected or retracted. Source, rubric, or tutor errors must be able to repair affected topic states without erasing the audit trail.
- Writes are validated, course-scoped, idempotent, and transactional. The agent does not own the SQL schema or write the database directly during tutoring.
- A positive save acknowledgment means the database commit succeeded. Unavailable persistence is stated plainly.
- Use ordinary code for search, filtering, counts, and state updates. Use the model for interpretation, teaching, and judgments that require reasoning.
- Measure total tokens and cost per correct task, including retries and image use. Do not claim a savings percentage without measurements.

## Meaning of assessment

The system reports observed performance and the strength, diversity, and recency of evidence. Unknown topics remain unknown. A score on a diagnostic is a score on that diagnostic; it is not automatically a calibrated probability of passing an exam.

Do not add arbitrary mastery points for each correct answer. Repeated attempts at the same question or near-identical variants do not count as fresh independent evidence. A break caused by fatigue is not evidence of a conceptual weakness.

## Initial scope

One learner per workspace, multiple courses, one local SQLite database, immutable source/attachment files, local tool execution, and thin adapters for the three required environments. Use a Python core with SQLite support; document and feature-check the runtime. Extraction dependencies are selected from representative files rather than assumed to handle every format.

PDFs, slides, images, and supplied text are target inputs. Their actual extraction capability must be reported. Unsupported or ambiguous pages remain available as originals and are marked for review.

## Deferred scope

Live multi-device synchronization, a custom chat client, a hosted multi-user service, automatic fine-tuning, agent fleets, and statistically calibrated pass predictions are outside the initial release. Semantic search, reranking, and provider-specific caching require measured benefit before adoption.

## Explicit product guarantees

- Confirmed grades require a linked attempt owned by the learner and evaluated,
  submitted work from the exact current question version. Full grades require
  every required subpart; partial grading remains visibly incomplete. Unknown or
  unreadable work cannot support a confirmed grade or assessed coverage.
- Validated writes and their receipts commit together. Failed operations preserve
  authoritative state; identical retries do not duplicate work, while conflicting
  or stale writes are rejected. Reaffirming an unchanged attempt link preserves
  its grades and history.
- Assistance is chronological: later explanations preserve earlier independent
  work, while prior hints and solution exposure qualify later performance.
- Corrections preserve audit history and update affected grades, coverage and
  topic states. Obsolete or unresolved evidence cannot revive as current mastery;
  outdated attempts cannot resume against changed questions.
- Question validation attests the exact revision reviewed. Source references and
  educational identities remain traceable across retrieval, attempts and evidence.
- Verification data and numeric values are validated consistently across the core
  and CLI. Ambiguous checks, malformed requests and non-finite values are rejected.
- Upgrades preserve recovery data and quarantine ambiguous legacy records for
  review. Restore protects the workspace from unsafe archive paths. Initialization
  failures release acquired resources so recovery can proceed.
- Runtime and host support claims reflect recorded execution evidence and expose
  unsupported capabilities. The CLI follows the shared core contract.

Detailed migration names, verification schemas, API parameters, and error behavior
live in the [technical core contract](docs/core-contract.md).

## Question tracking

Question tracking must retain each question's exact exam/source version and
location, review uncertain extraction, and keep learner/course presentation,
submission, assistance, grading, correctness, scores and feedback distinct.
Preserve every attempt and correction. Detect textual duplicates and likely
variants without deleting their separate source occurrences; use recorded history
to prevent accidental repeats and support intentional practice on mistakes.
Whole-exam coverage and semantic equivalence require explicit review. See the
[implemented question-tracking contract](docs/question-tracking.md).

Course imports follow the [shared folder layout](docs/course-layout.md): unchanged
originals → raw extraction → reviewed questions → rendered presentations → saved
assessment versions → learner history. Extraction, source visual review and
mathematical validation have independent status/history. A student artifact needs
its own actual rendering/print checks; reviewed source text alone does not prove
a correct presentation. Unknown metadata remains unknown. Keep source solutions,
highlighted originals and private answer mappings outside student output. DOCX
math XML supports reconstruction/search, not automatic mathematical approval.

## Efficient test generation

Reduce turns, tool calls and repeated context loading without weakening question
correctness, coverage or PDF quality. Build on the existing SQLite bank, learner
evidence, checked selection and PDF exporter. The following improvements are
planned; implement and validate them in small slices against registered courses.

A read-only check on 2026-10-19 found three eligible Algorithms source questions
with repeats allowed, all already reserved, and zero fresh candidates with repeats
excluded. This verifies reservation filtering in that workspace, not general
semantic duplicate detection. Active saved selections and pending publication jobs
reserve families until explicitly released or expired; age alone does not release them.

**First slice: a read-only readiness report.** Compare a supplied blueprint with
reviewed, eligible questions by section/topic/type. Report needed, available and
shortfall, pending review, unknown required metadata, and exclusion reasons.
Count distinct usable families after exposure and similarity filters. Check the
whole blueprint jointly when slots overlap. Report remaining capacity for complete
tests without family reuse across tests, under the stated constraints and current
bank/history snapshot; label bounds or estimates rather than claiming an exact
maximum when it has not been computed. Show topic bottlenecks and capacity blocked
only by reservations separately. This establishes whether review work, bank growth
or assembly code is the next bottleneck, without changing learner state.

Subsequent requirements:

1. **Blueprint-driven assembly.** A single public operation accepts course,
   learner, blueprint and seed plus a stable request ID. Blueprints define sections,
   types, counts, points, optional duration, topic allocations and applicable
   source/date/difficulty constraints. Derived exam structures need reviewed
   sources; otherwise label assumptions. Keep topic/type counts hard. Apply mastery
   and novelty weights within those constraints and retain private weight components
   and selection reasons. Return task/assessment IDs, paths, counts and review status;
   retrieve question text only for focused review. SQLite remains authoritative.
2. **Explicit shortages and fallback.** Fail with a structured gap report containing
   slot/section, topic, type, needed, eligible, shortfall and exclusion reasons.
   Relax constraints only under an explicitly authorized, ordered policy, preserving
   topic/type counts and review/provenance gates. When repeats are allowed, prioritize
   prior mistakes using eligible evaluated evidence. Never silently generate or
   substitute questions; generated alternatives in source-based practice require
   the learner's choice. Keep targeted practice distinct from exam coverage.
3. **Saved snapshots define re-export.** Persist the exact question revision/content
   snapshots, order, option permutation and private answer mapping with the saved
   blueprint. Re-export this assessment without re-running selection or consulting
   current learner weights. The seed is generation metadata, not the regeneration
   contract. Selection-policy metadata supports audit, not a dependency on old
   selection code. Preserve original PDF artifacts and hashes when exact bytes
   matter; rendering again may differ with renderer versions or settings.
4. **Recoverable publication.** Use staging and a small publication lifecycle,
   separate from learner progress or grading. Only published, visually checked
   artifacts count as delivered tests. Database and filesystem writes need crash
   recovery rather than one cross-resource transaction; never hold a database write
   transaction during rendering. Resume or clean up stale pending jobs and owned
   orphan staging files on startup/retry without disturbing live jobs. Failures
   cannot expose a ready test or strand active reservations; stable request IDs
   prevent duplicate assessments. File publication alone does not prove visual review.
5. **Reservation lifecycle (implemented locally).** Reservations remain separate
   from presentation, assistance and attempts. Explicit release/cancellation and
   on-demand seven-day UTC expiry retire unused drafts while preserving assessment,
   audit and saved re-export history. Live or recovery-required publication jobs are
   protected. Releasing never erases exposure or makes an attempted family fresh.
   Readiness reports safe-release relief separately. No background expiry runs;
   broader release and live-host validation remain subject to the release checklist.
6. **Grow and review the bank safely.** Reuse extraction/indexing by source and
   processor version, compact course indexes and configured tool paths. Invalidate
   affected derived artifacts on source changes. The first local slice now reuses
   completed ingestion by exact source bytes and known processor/dependency/configuration
   identity; changes create fresh derived versions without inheriting old reviews.
   Historical provenance and learner evidence remain attached to their original
   versions. Compact indexes, tool-path configuration and broader bank review remain.
   Models may pre-review solutions
   and flag ambiguity; executable checks and risk-based human sampling can reduce
   effort but do not automatically validate unchecked questions. Preserve exact-version
   extraction, source visual review, mathematical validation and presentation gates.
   Parameterized templates need valid domains and checked solution/key logic;
   variants within a family add practice variety, not fresh independent evidence
   or new-family test capacity. Unknown validation stays pending.
7. **Measure quality and efficiency together.** Compare fixed full-test jobs using
   the same host/agent and model, recording versions/settings, cold/warm starts,
   shortages and failures. Emit task IDs and attribute observed sessions or bounded
   segments without assigning unrelated work to the task. Record turns, tool calls,
   input/output/cache usage, retries, review effort and latency where available;
   unknown counts and billing stay unknown. Pair results with blueprint match,
   duplicates, answer/key correctness, privacy, PDF readability and reviewer outcomes.
   Use cheaper models only where evaluated quality holds. Keep existing linked
   attempts/evaluated work as the feedback loop; checklists alone do not establish
   independent mastery. Tune weights or add templates after the first slices provide
   evidence. Claim savings only from comparable measurements with quality gates met.

## Release evidence

A release is ready only when:

- Originals can be restored byte-for-byte, and source references resolve after a workspace move.
- Representative course questions retain all required assumptions and provenance during retrieval.
- Assistance, partial progress, repeated submissions, tutor corrections, and interrupted writes pass their specified checks.
- Diagnostics expose missing coverage and unresolved grading uncertainty.
- Codex, Claude Code, and Antigravity each pass a recorded integration smoke test against the same core contract, including a real cross-host handover preserving submitted work and assistance. Documentation checks alone do not establish runtime compatibility.
- Reported costs distinguish observed usage, estimated token counts, and unavailable billing data. Accuracy failures remain in the evaluation results.

Tagged CI builds create draft releases while any readiness gate remains open.
Publishing a stable release requires the evidence review in the
[release checklist](docs/release-readiness.md).

## Document ownership

This file defines the product outcome and fixed requirements. `plan.md` defines the implementation sequence and acceptance tests. `docs/agents.md` defines agent behavior. Root loader files only route hosts to those shared instructions. If scope changes, update these documents together and record the change; provider wrappers must not quietly redefine the product.
