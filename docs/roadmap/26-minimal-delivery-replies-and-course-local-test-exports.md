TL;DR: Verbatim legacy roadmap: 26. Minimal delivery replies and course-local test exports.
Status: historical snapshot; date: 2026-10-19.

<!-- ROADMAP:ORIGINAL -->
## 26. Minimal delivery replies and course-local test exports

Test-creation replies default to two short lines: PDF link/question count and
associated session token counters when known. Add only a short real shortage or
blocker. Source citations and review details stay in the PDF/manifest; verbose
bank inventories, IDs, provenance tables and verification narratives are omitted
unless requested. Required visual inspection is unchanged.

The default export location is now `<course_directory>/tests/<assessment_id>`.
The course directory comes from registered catalog import provenance, verified
against course.json; workspace-only courses get `<workspace>/courses/<course_id>`.
Explicit output_directory remains supported. Directory keys cannot escape their
course path, and ambiguous/unavailable imported directories produce an explicit
location error. Course discovery exposes this location. The course brief now
includes learner-scoped saved assessments and PDF paths, avoiding routine SQL
schema/source-code exploration when fresh proposals exclude reserved questions.
Browser discovery also checks known Playwright caches for hosts with limited PATH.
Course-directory details are included in the brief only when saved tests need
them, preserving compact ordinary tutoring startup payloads.

Actual AGY PDF printing and three page-image inspections were observed in the next
native app run. Its 3-page PDF and manifest hashes matched. The existing artifact
folder was moved intact to the example algorithms course's tests directory; no
PDF was regenerated or restyled in this change. That native session's numeric
ledger matches the transcript: 172,438 input / 7,961 output / 2,508,142 cache-read.
Cache inclusion remains unverified, and these are session rather than per-task
billing counters. Fresh native use of the revised folder/discovery defaults still
requires its next AGY run; local path/browser/discovery regressions cover the code.
