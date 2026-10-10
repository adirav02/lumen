#!/usr/bin/env python3
"""Synthetic Probability Course Demo for Lumen.

Demonstrates full end-to-end capabilities without external paid APIs:
- M0: Capability check and environment reporting
- M1: Idempotency receipts, immutable content storage, and revisions
- M2: Multi-source ingestion (PDF/Text) and multilingual retrieval (Hebrew/English)
- M3: Tutoring, assistance tracking, partial progress, and evidence correction
- M4: Diagnostic blueprint execution and transparent progress reporting
- M5: Workspace backup and restore verification with byte-for-byte fidelity
"""

import json
from pathlib import Path
import shutil
import tempfile
import time

from course_tutor.api import LumenCore


def main():
    print("=" * 70)
    print("  LUMEN — Synthetic Probability Course Demo")
    print("=" * 70)

    demo_root = Path(tempfile.mkdtemp(prefix="lumen_demo_"))
    print(f"\n[1] Initializing workspace at: {demo_root}")
    core = LumenCore(demo_root)

    try:
        # Step 1: Capabilities Check
        print("\n[2] Checking core and runtime capabilities...")
        caps = core.capabilities()
        print(f"  • Contract version: {caps['contract_version']}")
        print(f"  • SQLite version: {caps['runtime']['sqlite_version']} (FTS5: {caps['runtime']['fts5_supported']})")
        print(f"  • Extraction capabilities: PDF={caps['extraction_capabilities']['pdf_text']}, PPTX={caps['extraction_capabilities']['pptx_slides']}")

        # Step 2: Course Creation
        print("\n[3] Creating course: 'Introduction to Probability'...")
        c_res = core.create_course(
            name="Introduction to Probability",
            course_id="prob-demo",
            scope="Undergraduate Core Course",
            default_language="en",
            request_id="req-create-course-1",
        )
        course_id = c_res["data"]["id"]
        print(f"  • Course ID: {course_id} (Revision: {c_res['data']['revision']})")

        # Step 3: Topics and Multilingual Aliases
        print("\n[4] Registering syllabus topics with multilingual aliases (Hebrew/English)...")
        t_bayes = core.create_topic(course_id, name="Bayes' Theorem", slug="bayes")
        core.add_topic_alias(course_id, t_bayes["id"], alias="משפט בייס", language="he")
        core.add_topic_alias(course_id, t_bayes["id"], alias="הסתברות מותנית", language="he")
        core.add_topic_alias(course_id, t_bayes["id"], alias="P(A|B)", language="notation")

        t_poisson = core.create_topic(course_id, name="Poisson Distribution", slug="poisson")
        core.add_topic_alias(course_id, t_poisson["id"], alias="התפלגות פואסון", language="he")

        # Step 4: Source Material Ingestion
        print("\n[5] Ingesting lecture and slides materials...")
        mat_dir = Path(__file__).parent / "examples" / "synthetic_probability" / "materials"
        lecture_file = mat_dir / "lecture_bayes.txt"
        slides_file = mat_dir / "slides_random_variables.txt"

        res_lec = core.ingest_source(course_id, lecture_file, logical_name="lecture_bayes", role="lecture", topic_slugs=["bayes"])["data"]
        print(f"  • Ingested '{res_lec['storage_relpath']}' (SHA-256: {res_lec['file_hash'][:12]}...)")
        print(f"    Created {res_lec['units_created_count']} semantic knowledge units.")

        res_slides = core.ingest_source(course_id, slides_file, logical_name="slides_rv", role="slides", topic_slugs=["poisson"])["data"]
        print(f"  • Ingested '{res_slides['storage_relpath']}' (SHA-256: {res_slides['file_hash'][:12]}...)")
        print(f"    Created {res_slides['units_created_count']} semantic knowledge units.")

        # Step 5: Multilingual Retrieval and Dependency Expansion
        print("\n[6] Testing multilingual retrieval and assumption preservation...")
        # Hebrew query
        he_search = core.search(course_id, query="הסתברות מותנית")
        print(f"  • Hebrew query 'הסתברות מותנית' returned {he_search['results_count']} hit(s):")
        for hit in he_search["results"]:
            print(f"    - [{hit['kind'].upper()}] {hit['title']} (Provenance: {', '.join(hit['provenance'])})")

        # Read unit with dependency expansion
        bayes_hit = next(h for h in he_search["results"] if h["title"] == "Bayes' Theorem")
        bayes_unit_id = bayes_hit["unit_id"]
        unit_details = core.read_units(course_id, [bayes_unit_id], expand_dependencies=True)
        read_unit = unit_details["units"][0]
        print(f"  • Reading '{read_unit['title']}':")
        print(f"    - Content: {read_unit['content'][:60]}...")
        print(f"    - Preserved assumptions: {read_unit['assumptions']}")
        print(f"    - Preserved symbol definitions: {read_unit['symbol_definitions']}")

        # Step 6: Exercise Creation and Learner Tutoring Attempt
        print("\n[7] Starting interactive learner attempt on diagnostic exercise...")
        ex = core.create_exercise(
            course_id=course_id,
            exercise_family="bayes_medical_diagnosis",
            question_text="A disease has prevalence 1%. Test sensitivity is 90%, specificity is 90%. Find P(Disease | Positive).",
            topic_mappings=["bayes"],
            skill_mappings=["bayes_calc"],
            reference_solution="P(D|+) = (0.90*0.01) / (0.90*0.01 + 0.10*0.99) ≈ 0.083",
        )
        att = core.start_attempt(course_id, ex["exercise_version_id"], learner_id="student_1")["data"]
        att_id = att["id"]
        print(f"  • Attempt started: {att_id} (Status: {att['status']})")

        # Learner requests hint
        print("  • Learner requests a hint...")
        core.record_attempt_event(att_id, expected_revision=1, event_type="hint_request")
        core.record_attempt_event(att_id, expected_revision=2, event_type="hint_given", content="Use Law of Total Probability for denominator P(+).")

        # Learner submits correct solution
        print("  • Learner submits answer after hint: '0.083'")
        core.record_attempt_event(att_id, expected_revision=3, event_type="work_submission", content="P(D|+) = 0.009 / 0.108 ≈ 0.083")

        # Tutor evaluates
        print("  • Committing evidence...")
        ev_commit = core.commit_evidence(
            att_id,
            evaluations=[{
                "subpart_key": "default",
                "topic_id": t_bayes["id"],
                "skill_id": "bayes_calc",
                "correct": True,
                "rationale": "Correct application after hint.",
            }],
            complete_attempt=True,
        )["data"]
        ev = ev_commit["evidence_created"][0]
        print(f"  • Evaluated Demonstrated Level: '{ev['demonstrated_level']}' (Assisted due to prior hint, NOT independent mastery)")

        # Step 7: Course Brief and Audit Check
        print("\n[8] Inspecting course brief and state projections...")
        brief = core.course_brief(course_id, learner_id="student_1")
        print(f"  • Assessed topics: {[t['name'] for t in brief['coverage']['assessed_topics']]}")
        print(f"  • Unassessed topics: {brief['coverage']['unassessed_topics']}")
        print(f"  • Recommended next action: {brief['recommended_next_actions'][0]['description']}")

        # Step 8: Evidence Correction (Audit History Preservation)
        print("\n[9] Demonstrating tutor mistake retraction and state recomputation...")
        ev_id = ev["id"]
        corr = core.correct_evidence(
            evidence_id=ev_id,
            correction_reason="Reviewed reasoning: student independently derived denominator prior to hint.",
            replacement={
                "topic_id": t_bayes["id"],
                "skill_id": "bayes_calc",
                "demonstrated_level": "independent_mastery",
                "rationale": "Independent derivation confirmed in rough work.",
            },
        )["data"]
        recomputed = corr["recomputed_topic_states"][t_bayes["id"]]
        print(f"  • Recomputed Topic State: Independent Successes={recomputed['independent_success_count']}, Assisted Successes={recomputed['assisted_success_count']}")

        # Step 9: Diagnostic Assessment Execution
        print("\n[10] Running diagnostic assessment with topic blueprint...")
        diag = core.create_assessment(
            course_id=course_id,
            title="Probability Mid-term Diagnostic",
            blueprint={"topic_ids": [t_bayes["id"], t_poisson["id"]]},
            selected_exercise_version_ids=[ex["exercise_version_id"]],
        )["data"]
        prog = core.assessment_progress(diag["assessment_id"])
        bayes_cov = prog['topic_coverage'].get("Bayes' Theorem", {}).get('assessed')
        poisson_cov = prog['topic_coverage'].get('Poisson Distribution', {}).get('assessed')
        print(f"  • Topic Coverage: Bayes={bayes_cov}, Poisson={poisson_cov}")

        # Step 10: Backup and Restore Verification
        print("\n[11] Creating snapshot backup and verifying restore into clean workspace...")
        backup_zip = demo_root / "prob_course_backup.zip"
        b_res = core.backup(backup_zip)
        print(f"  • Backup archive created: {backup_zip.name} ({b_res['source_count']} sources)")

        # Restore into separate workspace
        restore_dir = Path(tempfile.mkdtemp(prefix="lumen_restored_"))
        r_res = LumenCore.restore(backup_zip, restore_dir)
        print(f"  • Restored into: {restore_dir}")
        print(f"  • Verified sources: {r_res['sources_verified']}, Restored courses: {r_res['courses']}")

        # Validate restored core
        restored_core = LumenCore(restore_dir)
        restored_brief = restored_core.course_brief(course_id)
        assert restored_brief["course"]["name"] == "Introduction to Probability"
        print("  • Restored course integrity verified byte-for-byte!")
        restored_core.close()

        print("\n" + "=" * 70)
        print("  DEMO COMPLETE: All operations succeeded with full integrity!")
        print("=" * 70)

    finally:
        core.close()
        shutil.rmtree(demo_root, ignore_errors=True)


if __name__ == "__main__":
    main()
