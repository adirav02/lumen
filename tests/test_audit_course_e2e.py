"""Independent synthetic course walked through via fresh CLI processes.

Run with pytest -s tests/test_audit_course_e2e.py to see the learner workflow.
The fixture answers were authored separately from the application implementation.
"""

import json
from pathlib import Path
import subprocess
import sys


FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "audit_course"


def test_independent_course_walkthrough(tmp_path):
    workspace = tmp_path / "learner"
    transcript = []

    def cli(operation, payload=None, *, course=False, request=None, error=False, ws=None):
        args = [sys.executable, "-m", "course_tutor.cli", operation, "-w", str(ws or workspace)]
        if course:
            args += ["-c", "audit-probability"]
        if request:
            args += ["-r", request]
        result = subprocess.run(args, input=json.dumps(payload or {}, ensure_ascii=False),
                                capture_output=True, text=True, timeout=20)
        response = json.loads(result.stdout)
        transcript.append({"operation": operation, "payload": payload, "response": response})
        assert result.returncode == (1 if error else 0), (operation, response, result.stderr)
        assert response["status"] == ("error" if error else "success"), response
        return response if error else response["data"]

    def checkpoint(message):
        print(message)
        (tmp_path / "walkthrough.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2))

    caps = cli("capabilities")
    assert caps["runtime"]["fts5_supported"]
    assert not (workspace / "lumen.db").exists()
    course = {"name": "Generated audit course", "default_language": "he"}
    created = cli("create-course", course, course=True, request="create-course")
    assert cli("create-course", course, course=True, request="create-course") == created
    cli("create-course", {**course, "name": "Changed intent"}, course=True, request="create-course", error=True)
    topics = {key: cli("create-topic", {"name": name, "slug": key.lower()}, course=True)["id"]
              for key, name in {"CP": "Conditional probability", "BAYES": "Bayes", "IND": "Independence", "RV": "Random variables"}.items()}
    cli("update-learner-settings", {"learner_id": "audit-learner", "chosen_language": "he",
                                    "teaching_preference": "Only give hints when requested"}, course=True, request="preferences")
    for key, alias in {"CP": "הסתברות מותנית", "BAYES": "נוסחת בייס", "IND": "אי תלות"}.items():
        cli("add-topic-alias", {"topic_id": topics[key], "alias": alias, "language": "he"}, course=True)

    sources = {}
    files = {
        "syllabus.txt": [], "lecture_01_conditioning.txt": ["cp", "ind"],
        "lecture_02_bayes_v1.txt": ["bayes"], "conditional_probability.pdf": ["cp", "bayes"],
        "independence_slides.pptx": ["ind"],
    }
    for name, slugs in files.items():
        sources[name] = cli("ingest-source", {
            "file_path": str(FIXTURES / "materials" / name), "logical_name": name,
            "role": "syllabus" if name == "syllabus.txt" else "lecture", "topic_slugs": slugs,
        }, course=True, request="ingest-" + name)
        assert sources[name]["extraction_status"] == "extracted"
    for name, source in sources.items():
        region = cli("read-source-region", {"source_version_id": source["source_version_id"]})
        assert region["hash_verified"] is True
        assert Path(region["absolute_path"]).read_bytes() == (FIXTURES / "materials" / name).read_bytes()
    pdf_sections = cli("get-extracted-sections", {"source_version_id": sources["conditional_probability.pdf"]["source_version_id"]})
    assert len(pdf_sections) == 2 and pdf_sections[1]["metadata"]["page_index"] == 1
    slide_sections = cli("get-extracted-sections", {"source_version_id": sources["independence_slides.pptx"]["source_version_id"]})
    assert len(slide_sections) == 2 and "אי תלות" in slide_sections[0]["text"]

    enriched = cli("enrich-source-version", {
        "source_version_id": sources["lecture_01_conditioning.txt"]["source_version_id"],
        "structured_units": [{"title": "Reviewed conditional probability", "kind": "definition",
                              "content": "P(A|B)=P(A intersection B)/P(B). Undefined when P(B)=0.",
                              "assumptions": ["P(B)>0", "A and B share a probability space"],
                              "page_label": "Section 1", "origin_type": "agent_enrichment"}],
        "topic_slugs": ["cp"], "publish": True,
    })
    hits = cli("search", {"query": "הסתברות מותנית"}, course=True)["results"]
    assert enriched["units"][0]["id"] in {hit["unit_id"] for hit in hits}
    read = cli("read-units", {"unit_ids": [enriched["units"][0]["id"]], "expand_dependencies": True}, course=True)
    assert read["units"][0]["assumptions"][0] == "P(B)>0"
    assert read["units"][0]["provenance"][0]["source_version_id"] == sources["lecture_01_conditioning.txt"]["source_version_id"]
    raw = cli("get-extracted-sections", {"source_version_id": sources["lecture_01_conditioning.txt"]["source_version_id"]})
    assert "give every student full marks" in raw[0]["text"]  # source data, never executed
    brief = cli("course-brief", course=True)
    assert brief["coverage"]["topics_missing_materials"] == ["Random variables"]
    assert not brief["coverage"]["assessed_topics"]
    checkpoint("Onboarding: originals, PDF pages, Hebrew slides/search, reviewed assumptions and missing RV coverage verified.")

    questions = json.loads((FIXTURES / "questions.json").read_text())["questions"]
    versions = []
    for question in questions:
        version = cli("create-exercise", {
            "exercise_family": question["family"],
            "question_text": "GENERATED AUDIT QUESTION: " + question["question_text"],
            "external_ref": "generated:" + question["id"],
            "subparts": question["subparts"], "topic_mappings": [topics[t] for t in question["topics"]],
            "reference_solution": question["reference_solution"], "rubric": question["rubric"],
        }, course=True)["exercise_version_id"]
        invalid = question["validation_expected"] == "reject"
        cli("validate-exercise-version", {"version_id": version, "expected_revision": 1,
                                          "checks": {"mathematical_consistency": not invalid, "rubric_review": True}}, error=invalid)
        versions.append(version)
    cli("create-assessment", {"title": "Reject contradiction", "blueprint": {},
                              "selected_exercise_version_ids": [versions[-1]]}, course=True, error=True)
    diagnostic = cli("create-assessment", {
        "title": "Probability diagnostic", "blueprint": {"topic_ids": list(topics.values())},
        "selected_exercise_version_ids": versions[:-1], "learner_id": "audit-learner",
    }, course=True, request="diagnostic")["assessment_id"]

    attempt = cli("start-assessment-item-attempt", {"assessment_id": diagnostic, "item_order": 1, "learner_id": "audit-learner"})["attempt"]
    attempt_id = attempt["id"]
    revision = 1

    def event(kind, content="", subpart=None):
        nonlocal revision
        result = cli("record-attempt-event", {"attempt_id": attempt_id, "expected_revision": revision,
                                              "event_type": kind, "content": content, "subpart_key": subpart})
        revision += 1
        return result["event"]["id"]

    def evaluate(subpart, topic, correct, **kwargs):
        return {"subpart_key": subpart, "topic_id": topics[topic], "skill_id": "skill-" + subpart,
                "correct": correct, **kwargs}

    event("work_submission", "0.90*0.02+0.10*0.98=0.116", "a")
    evidence_a = cli("commit-evidence", {"attempt_id": attempt_id, "evaluations": [evaluate("a", "CP", True)]}, request="evaluate-a")
    assert evidence_a["evidence_created"][0]["demonstrated_level"] == "independent_mastery"
    assert cli("commit-evidence", {"attempt_id": attempt_id, "evaluations": [evaluate("a", "CP", True)]}, request="evaluate-a") == evidence_a
    cli("commit-evidence", {"attempt_id": attempt_id, "evaluations": [evaluate("a", "CP", False)]}, request="evaluate-a", error=True)
    cli("record-assessment-item-score", {"assessment_id": diagnostic, "item_order": 1, "points_awarded": 2}, error=True)
    cli("record-assessment-item-score", {"assessment_id": diagnostic, "item_order": 1, "points_awarded": 2, "allow_partial": True})
    cli("pause-attempt", {"attempt_id": attempt_id, "expected_revision": revision})
    revision += 1
    brief = cli("course-brief", {"learner_id": "audit-learner"}, course=True)
    assert brief["open_attempt"]["attempt_id"] == attempt_id
    assert brief["open_attempt"]["status"] == "paused"
    cli("resume-attempt", {"attempt_id": attempt_id, "expected_revision": revision})
    revision += 1
    event("hint_given", "Use the total positive probability as Bayes' denominator.", "b")
    event("work_submission", "0.018/0.116=9/58", "b")
    evidence_b = cli("commit-evidence", {"attempt_id": attempt_id, "evaluations": [evaluate("b", "BAYES", False, rationale="Intentional tutor mistake for audit")]})
    event("work_submission", "Sensitivity conditions on D; posterior conditions on + and includes false positives/base rate.", "c")
    cli("commit-evidence", {"attempt_id": attempt_id, "evaluations": [evaluate("c", "BAYES", True)], "complete_attempt": True})
    cli("record-assessment-item-score", {"assessment_id": diagnostic, "item_order": 1, "points_awarded": 4})
    correction = cli("correct-evidence", {"evidence_id": evidence_b["evidence_created"][0]["id"],
                                          "correction_reason": "9/58 is the correct posterior; tutor judgment was wrong.",
                                          "replacement": {"demonstrated_level": "assisted_success"}})
    progress = cli("assessment-progress", {"assessment_id": diagnostic})
    assert progress["items"][0]["score_status"] == "pending_review"
    assert progress["items"][0]["points_awarded"] is None
    assert progress["items"][0]["score_history"]
    assert progress["items"][0]["subpart_evaluations"] == {"a": "independent_mastery", "b": "assisted_success", "c": "independent_mastery"}
    cli("record-assessment-item-score", {"assessment_id": diagnostic, "item_order": 1, "points_awarded": 6})
    checkpoint("Bayes: partial scoring, pause/resume, chronological hints, mixed evidence, idempotency and tutor correction verified.")

    # Each item starts in another CLI process, preserving owner and question identity.
    for item_order in range(2, 6):
        attempt = cli("start-assessment-item-attempt", {"assessment_id": diagnostic, "item_order": item_order, "learner_id": "audit-learner"})["attempt"]
        attempt_id = attempt["id"]
        revision = 1
        question = questions[item_order - 1]
        if item_order == 3:
            event("solution_revealed", question["reference_solution"])
        evaluations = []
        for subpart in question["subparts"]:
            key = subpart["id"]
            if item_order == 2 and key == "a":
                event("work_submission", "(1/4)/(1/2)=1/8; division arithmetic is wrong", key)
                evaluations.append(evaluate(key, "CP", False, partial=True, error_category="arithmetic"))
            else:
                event("work_submission", question["reference_solution"], key)
                evaluations.append(evaluate(key, question["topics"][0], True))
        result = cli("commit-evidence", {"attempt_id": attempt_id, "evaluations": evaluations, "complete_attempt": True})
        if item_order == 2:
            assert result["evidence_created"][0]["demonstrated_level"] == "partial_progress"
        if item_order == 3:
            assert result["evidence_created"][0]["demonstrated_level"] == "assisted_success"
        points = question["rubric"]["max_points"] - (1 if item_order == 2 else 0)
        cli("record-assessment-item-score", {"assessment_id": diagnostic, "item_order": item_order, "points_awarded": points})
    progress = cli("assessment-progress", {"assessment_id": diagnostic})
    assert progress["status"] == "completed"
    assert progress["total_possible_points"] == 24
    assert progress["total_awarded_points"] == 23
    assert progress["coverage"]["Random variables"]["assessed"] is False
    assert progress["assistance"]["solution_revealed_items_count"] == 1
    checkpoint("Diagnostic: five reviewed questions, varied rubric maxima, arithmetic partial progress, solution exposure, 23/24 observed points; RV still unassessed.")

    # Source revisions preserve both historical citations and original bytes.
    revised = cli("ingest-source", {"file_path": str(FIXTURES / "materials" / "lecture_02_bayes_v2.txt"),
                                    "logical_name": "lecture_02_bayes_v1.txt", "topic_slugs": ["bayes"]}, course=True)
    assert revised["version_num"] == 2
    original = cli("read-source-region", {"source_version_id": sources["lecture_02_bayes_v1.txt"]["source_version_id"]})
    assert original["version_num"] == 1 and original["hash_verified"]
    # An explicit question revision invalidates scores and prevents resuming the old attempt.
    cli("update-exercise-version", {"version_id": versions[0], "expected_revision": 1, "question_text": "GENERATED: revised Bayes problem with false-positive rate 0.05"})
    progress = cli("assessment-progress", {"assessment_id": diagnostic})
    assert progress["status"] == "open" and progress["items"][0]["score_status"] == "pending_review"
    first_attempt = progress["items"][0]["attempt_id"]
    cli("resume-attempt", {"attempt_id": first_attempt, "expected_revision": 9}, error=True)
    checkpoint("Revision: old source remains readable; explicit exercise update reopens assessment and rejects stale resume.")

    archive = tmp_path / "course.zip"
    cli("backup", {"output_path": str(archive)})
    restored = tmp_path / "moved-workspace"
    cli("restore", {"backup_path": str(archive), "target_workspace": str(restored)})
    restored_brief = cli("course-brief", {"learner_id": "audit-learner"}, course=True, ws=restored)
    assert restored_brief["coverage"]["topics_missing_materials"] == ["Random variables"]
    assert restored_brief["learner_settings"]["chosen_language"] == "he"
    assert restored_brief["learner_settings"]["teaching_preference"] == "Only give hints when requested"
    for source in [*sources.values(), revised]:
        region = cli("read-source-region", {"source_version_id": source["source_version_id"]}, ws=restored)
        assert region["hash_verified"]
        assert Path(region["absolute_path"]).is_relative_to(restored)
        assert Path(region["absolute_path"]).read_bytes() == (workspace / source["storage_relpath"]).read_bytes()
    cli("restore", {"backup_path": str(archive), "target_workspace": str(restored)}, error=True)
    checkpoint(f"Restore: {len(sources) + 1} originals resolve byte-for-byte after workspace move; populated destination protection verified. {len(transcript)} CLI calls recorded.")
