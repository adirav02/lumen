"""End-to-end catalog, provenance, repetition and learner history regressions."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import LumenError
from course_tutor.storage.db import get_connection
from course_tutor.storage.migrations import MIGRATIONS, _execute_sql_script, run_migrations


@pytest.fixture
def core(tmp_path):
    with LumenCore(tmp_path / "workspace") as c:
        c.create_course("Algorithms", course_id="alg")
        c.create_course("Other", course_id="other")
        yield c


def exam(c, tmp_path, text, name="Exam A", course="alg"):
    path = tmp_path / "exam.txt"
    path.write_text(text)
    return c.ingest_source(course, path, logical_name=name, role="exam")["data"]


def checked(c, text="Compute the number of leaves in a full binary tree.", family="trees", subparts=None):
    version = c.create_exercise("alg", family, text, subparts=subparts, reference_solution="Checked fixture reference", rubric={"max_points": 4})["exercise_version_id"]
    c.validate_exercise_version(version, expected_revision=1, checks={"review": True})
    return version


def work(c, version, correct=False, learner="alice", hint=False, partial=False):
    topic = c.topic_repo.get_topic_by_slug("alg", "trees")
    if not topic:
        topic = c.topic_repo.get_topic(c.create_topic("alg", "Trees", slug="trees")["id"])
    attempt = c.start_attempt("alg", version, learner_id=learner)["data"]
    revision = 1
    if hint:
        c.record_attempt_event(attempt["id"], revision, "hint_given", content="Inspect the children.")
        revision += 1
    submission = c.record_attempt_event(attempt["id"], revision, "work_submission", content="My submitted answer")
    evidence = c.commit_evidence(attempt["id"], [{"topic_id": topic.id, "skill_id": "count", "correct": correct, "partial": partial,
        "rationale": "Checked the observed counting argument."}], submission_event_id=submission["data"]["event"]["id"])["data"]["evidence_created"][0]
    return attempt, evidence


def test_ingestion_catalogs_all_numbered_questions_with_immutable_source_versions(core, tmp_path):
    text = "Exam header\nQuestion 1: Find a minimum spanning tree.\n(a) Explain.\nQuestion 2: Prove the runtime bound.\n"
    data = exam(core, tmp_path, text)
    first = core.list_questions("alg", data["source_version_id"])["questions"]
    assert len(first) == 2
    assert {q["question_key"] for q in first} == {"1", "2"}
    assert all(q["review_status"] == "pending_review" and q["validation_state"] == "pending_review" for q in first)
    assert data["question_catalog"]["coverage_verified"] is False
    sections = core.get_extracted_sections(data["source_version_id"])
    for q in first:
        span = q["source_spans"][0]
        raw = core.con.execute("SELECT text FROM source_sections WHERE id=?", (span["section_id"],)).fetchone()[0]
        assert q["extracted_text"] in raw[span["start_offset"]:span["end_offset"]]
    second_data = exam(core, tmp_path, text.replace("runtime", "space"))
    second = core.list_questions("alg", second_data["source_version_id"])["questions"]
    assert second_data["version_num"] == 2
    assert first[0]["file_hash"] != second[0]["file_hash"]
    assert {q["exercise_version_id"] for q in first}.isdisjoint(q["exercise_version_id"] for q in second)
    assert core.list_questions("alg", data["source_version_id"])["questions"] == first
    again = core.catalog_exam_questions("alg", data["source_version_id"])
    assert sum(again["data"]["question_counts"].values()) == 2


def test_question_and_whole_exam_review_require_explicit_count_and_checks(core, tmp_path):
    data = exam(core, tmp_path, "שאלה 1: מצאו עץ מינימלי.\nשאלה 2: הוכיחו חסם.")
    sid = data["source_version_id"]
    questions = core.list_questions("alg", sid)["questions"]
    checks = {"all_pages_reviewed": True, "question_count_verified": True}
    with pytest.raises(LumenError):
        core.review_exam_catalog("alg", sid, 2, 2, "Reviewed", checks)
    for q in questions:
        core.review_question_occurrence("alg", q["id"], 1, "accepted", "Compared with original page")
    state = core.exam_catalog_status("alg", sid)
    with pytest.raises(LumenError):
        core.review_exam_catalog("alg", sid, state["revision"], 3, "Reviewed", checks)
    result = core.review_exam_catalog("alg", sid, state["revision"], 2, "Count and all pages verified", checks, request_id="review-exam")
    assert result["data"]["coverage_verified"]
    assert core.review_exam_catalog("alg", sid, state["revision"], 2, "Count and all pages verified", checks, request_id="review-exam")["idempotent_replay"]
    with pytest.raises(LumenError):
        core.review_question_occurrence("alg", questions[0]["id"], 1, "rejected", "stale review")
    with pytest.raises(LumenError):
        core.list_questions("other", sid)


def test_uncertain_boundaries_missing_headers_and_manual_visual_transcription(core, tmp_path):
    data = exam(core, tmp_path, "1. Compute a recurrence.\n2. Prove termination.")
    assert all("ambiguous_numbered_boundary" in q["quality_flags"] for q in core.list_questions("alg", data["source_version_id"])["questions"])
    no_headers = exam(core, tmp_path, "A scanned or nonstandard question needs visual inspection.", "Scan")
    sid = no_headers["source_version_id"]
    assert core.exam_catalog_status("alg", sid)["coverage_verified"] is False
    assert core.list_questions("alg", sid)["questions"] == []
    result = core.catalog_exam_questions("alg", sid, questions=[{"question_key": "diagram", "question_text": "Host-inspected question about the diagram.",
        "source_spans": [{"section_index": 0}]}], request_id="manual-catalog")
    assert result["data"]["question_counts"] == {"pending_review": 1}
    assert core.catalog_exam_questions("alg", sid, questions=[{"question_key": "diagram", "question_text": "Host-inspected question about the diagram.",
        "source_spans": [{"section_index": 0}]}], request_id="manual-catalog")["idempotent_replay"]
    before = core.con.total_changes
    with pytest.raises(LumenError):
        core.catalog_exam_questions("alg", sid, questions=[{"question_key": "bad", "question_text": "text", "source_spans": [{"section_index": 9}]}])
    assert core.con.total_changes == before


def test_exact_and_similar_questions_across_exams_keep_separate_occurrences(core, tmp_path):
    first = exam(core, tmp_path, "Question 1: A full binary tree has 12 leaves. Find its number of internal nodes.", "A")
    second = exam(core, tmp_path, "Question 7: A full binary tree has 12 leaves. Find its number of internal nodes.", "B")
    third = exam(core, tmp_path, "Question 2: A full binary tree has 24 leaves. Find its number of internal nodes.", "C")
    relations = core.list_question_relations("alg")["relations"]
    assert any(r["kind"] == "exact" and r["status"] == "confirmed" for r in relations)
    assert any(r["method"] == "numeric_template" and r["status"] == "pending_review" for r in relations)
    questions = core.list_questions("alg")["questions"]
    for q in questions:
        core.review_question_occurrence("alg", q["id"], 1, "accepted", "Compared with original")
        core.validate_exercise_version(q["exercise_version_id"], expected_revision=1, reference_solution="A full binary tree has one fewer internal node than leaves.", rubric={"max_points": 4}, checks={"review": True})
    assert core.propose_practice("alg", learner_id="alice", count=3)["shortfall"] == 2
    a = core.list_questions("alg", first["source_version_id"])["questions"][0]["exercise_version_id"]
    core.start_attempt("alg", a, learner_id="alice")
    assert core.propose_practice("alg", learner_id="alice")["candidates"] == []
    assert len(core.propose_practice("alg", learner_id="bob")["candidates"]) == 1
    assert core.propose_practice("alg", exclude_exercise_version_ids=[a])["candidates"] == []


def test_rejected_similarity_and_changed_content_stop_blocking(core):
    a = checked(core, "A tree has 12 leaves. Count its internal nodes.", "a")
    b = checked(core, "A tree has 24 leaves. Count its internal nodes.", "b")
    relation = core.list_question_relations("alg")["relations"][0]
    core.start_attempt("alg", a, learner_id="alice")
    assert core.propose_practice("alg", learner_id="alice")["candidates"] == []
    core.review_question_relation("alg", relation["id"], 1, "rejected", "Intentional distinct objectives")
    assert core.propose_practice("alg", learner_id="alice")["candidates"][0]["exercise_version_id"] == b
    core.update_exercise_version(b, question_text="Find a shortest path in this graph.", expected_revision=1)
    core.validate_exercise_version(b, expected_revision=2, checks={"review": True})
    assert core.list_question_relations("alg")["relations"] == []
    assert core.propose_practice("alg", learner_id="alice")["candidates"][0]["exercise_version_id"] == b


def test_shown_answered_graded_and_correct_are_independent(core):
    version = checked(core)
    att = core.start_attempt("alg", version, learner_id="alice")["data"]
    def summary():
        return core.question_history("alg", "alice", version)["attempts"][0]
    assert not any(summary()[k] for k in ("shown", "answered", "graded", "answered_correctly"))
    core.record_attempt_event(att["id"], 1, "question_presented", content="Presented the exact checked version")
    assert summary()["shown"] and not summary()["answered"]
    core.record_attempt_event(att["id"], 2, "hint_given", content="Use the full binary tree invariant")
    core.record_attempt_event(att["id"], 3, "work_submission", content="n-1")
    assert summary()["answered"] and not summary()["graded"]
    topic = core.create_topic("alg", "Trees")["id"]
    core.commit_evidence(att["id"], [{"topic_id": topic, "skill_id": "count", "correct": True, "rationale": "Valid invariant"}])
    assert summary()["graded"] and summary()["answered_correctly"]
    assert summary()["hint_count"] == 1
    assert core.question_history("alg", "bob", version)["attempts"] == []
    with pytest.raises(LumenError):
        core.attempt_history("alg", "bob", att["id"])
    assert core.attempt_history("alg", "alice", att["id"])["evidence"][0]["demonstrated_level"] == "assisted_success"


def test_practice_scores_feedback_and_grading_corrections_preserve_every_revision(core):
    version = checked(core)
    att, ev = work(core, version)
    grade = core.grade_attempt("alg", "alice", att["id"], 0, 0, 4, "The leaf count is incorrect.", [ev["id"]], request_id="grade-1")
    assert grade["data"]["correctness"] == "incorrect"
    assert core.grade_attempt("alg", "alice", att["id"], 0, 0, 4, "The leaf count is incorrect.", [ev["id"]], request_id="grade-1")["idempotent_replay"]
    correction = core.correct_evidence(ev["id"], "Tutor misread handwriting", {"demonstrated_level": "independent_mastery", "rationale": "Learner's count was correct"})
    history = core.attempt_history("alg", "alice", att["id"])
    assert history["grades"][0]["effective_status"] == "pending_review"
    assert {e["status"] for e in history["evidence"]} == {"active", "superseded"}
    new_id = correction["data"]["resulting_evidence"]["id"]
    core.grade_attempt("alg", "alice", att["id"], 1, 4, 4, "Corrected: valid answer.", [new_id], correction_reason="Tutor correction")
    history = core.attempt_history("alg", "alice", att["id"])
    assert [g["points_awarded"] for g in history["grades"]] == [0, 4]
    assert history["grades"][0]["feedback"] == "The leaf count is incorrect."
    assert history["summary"]["answered_correctly"]
    assert history["summary"]["latest_practice_grade"]["effective_status"] == "scored"
    assert core.propose_practice("alg", "alice", allow_repeats=True, focus="mistakes")["candidates"] == []


def test_partial_work_does_not_mean_answered_correctly_and_new_attempts_are_kept(core):
    version = checked(core)
    first, ev = work(core, version, partial=True)
    s = core.question_history("alg", "alice", version)["attempts"][0]
    assert s["graded"] and not s["answered_correctly"] and s["correctness"] == "partial"
    assert len(core.propose_practice("alg", "alice", allow_repeats=True, focus="mistakes")["candidates"]) == 1
    work(core, version, correct=True)
    assert len(core.question_history("alg", "alice", version)["attempts"]) == 2
    assert core.propose_practice("alg", "alice", allow_repeats=True, focus="mistakes")["candidates"] == []
    assert core.propose_practice("alg", "bob", allow_repeats=True, focus="mistakes")["candidates"] == []


@pytest.mark.parametrize("override", [{"points_awarded": True}, {"points_awarded": 5}, {"max_points": 5}, {"feedback": ""},
    {"evidence_ids": []}, {"expected_grade_revision": True}, {"allow_partial": "false"}, {"learner_id": "bob"}])
def test_invalid_grades_rollback(core, override):
    version = checked(core)
    att, ev = work(core, version, correct=True)
    args = dict(course_id="alg", learner_id="alice", attempt_id=att["id"], expected_grade_revision=0,
        points_awarded=4, max_points=4, feedback="Checked", evidence_ids=[ev["id"]])
    args.update(override)
    before = core.con.total_changes
    with pytest.raises(LumenError):
        core.grade_attempt(**args)
    assert core.con.total_changes == before


def test_history_pagination_and_cli(core):
    version = checked(core)
    for _ in range(3):
        work(core, version)
    first = core.question_history("alg", "alice", version, limit=2)
    second = core.question_history("alg", "alice", version, limit=2, after_id=first["next_after_id"])
    assert len(first["attempts"]) == 2 and len(second["attempts"]) == 1
    assert {a["id"] for a in first["attempts"]}.isdisjoint(a["id"] for a in second["attempts"])
    proc = subprocess.run([sys.executable, "-m", "course_tutor.cli", "question-history", "-w", str(core.workspace_root),
        "-c", "alg", "-j", json.dumps({"learner_id": "alice", "exercise_version_id": version, "limit": 1})], text=True, capture_output=True, check=True)
    assert len(json.loads(proc.stdout)["data"]["attempts"]) == 1


def test_migration_backfills_existing_questions_and_preserves_legacy_attempts(tmp_path):
    path = tmp_path / "old.db"
    con = get_connection(path)
    try:
        for version, description, sql in MIGRATIONS[:8]:
            _execute_sql_script(con, sql)
            con.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'),?)", (version, description))
        con.execute("INSERT INTO courses(id,name,created_at,updated_at) VALUES ('alg','A','now','now')")
        con.execute("INSERT INTO exercises VALUES ('e','alg','old','','now')")
        con.execute("INSERT INTO exercise_versions(id,exercise_id,course_id,version_num,question_text,created_at) VALUES ('v','e','alg',1,'Historical question','now')")
        con.execute("INSERT INTO attempts(id,course_id,exercise_version_id,learner_id,started_at,updated_at) VALUES ('a','alg','v','alice','now','now')")
        con.execute("INSERT INTO sources VALUES ('s','alg','Legacy exam','exam','now')")
        con.execute("""INSERT INTO source_versions (id,source_id,course_id,version_num,file_hash,original_filename,mime_type,byte_size,storage_relpath,created_at)
            VALUES ('sv','s','alg',1,'hash','exam.txt','text/plain',23,'originals/exam.txt','now')""")
        con.execute("""INSERT INTO source_sections (id,source_version_id,course_id,section_index,label,text,quality_flag,created_at)
            VALUES ('sec','sv','alg',0,'Page 1','Question 1: Count leaves.','clean','now')""")
        con.commit()
        run_migrations(con)
        assert con.execute("SELECT COUNT(*) FROM question_fingerprints").fetchone()[0] == 2
        assert con.execute("SELECT source_version_id FROM question_occurrences").fetchone()[0] == "sv"
        assert con.execute("SELECT learner_id FROM attempts WHERE id='a'").fetchone()[0] == "alice"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        con.close()


def test_latest_ungraded_answer_does_not_inherit_earlier_correctness(core):
    version = checked(core)
    att, evidence = work(core, version, correct=True)
    core.record_attempt_event(att["id"], 2, "work_submission", content="A newer answer that has not been checked")
    summary = core.attempt_history("alg", "alice", att["id"])["summary"]
    assert summary["graded"]  # An earlier answer was graded; that fact is retained.
    assert not summary["currently_graded"]
    assert not summary["answered_correctly"]
    with pytest.raises(LumenError):
        core.grade_attempt("alg", "alice", att["id"], 0, 4, 4, "Stale answer", [evidence["id"]])


def test_grade_requires_complete_subparts_and_rejects_stale_content(core):
    version = checked(core, subparts=[{"key": "a"}, {"key": "b"}])
    topic = core.create_topic("alg", "Trees")["id"]
    att = core.start_attempt("alg", version, learner_id="alice")["data"]
    core.record_attempt_event(att["id"], 1, "work_submission", subpart_key="a", content="Work on a")
    ev = core.commit_evidence(att["id"], [{"topic_id": topic, "skill_id": "count", "subpart_key": "a", "correct": True}])["data"]["evidence_created"][0]
    with pytest.raises(LumenError):
        core.grade_attempt("alg", "alice", att["id"], 0, 2, 4, "Only a checked", [ev["id"]])
    partial = core.grade_attempt("alg", "alice", att["id"], 0, 2, 4, "Only a checked", [ev["id"]], allow_partial=True)
    assert partial["data"]["score_status"] == "partially_scored"
    assert not core.attempt_history("alg", "alice", att["id"])["summary"]["answered_correctly"]
    core.update_exercise_version(version, question_text="Corrected question", expected_revision=1)
    assert core.attempt_history("alg", "alice", att["id"])["grades"][0]["effective_status"] == "pending_review"
    with pytest.raises(LumenError):
        core.grade_attempt("alg", "alice", att["id"], 1, 2, 4, "Stale", [ev["id"]], correction_reason="retry", allow_partial=True)


def test_cross_attempt_and_observation_evidence_cannot_support_a_grade(core):
    version = checked(core)
    first, evidence = work(core, version, correct=True)
    second = core.start_attempt("alg", version, learner_id="alice")["data"]
    with pytest.raises(LumenError):
        core.grade_attempt("alg", "alice", second["id"], 0, 4, 4, "No submitted work", [evidence["id"]])
    corrected = core.correct_evidence(evidence["id"], "Illegible", {"demonstrated_level": "unreadable"})["data"]["resulting_evidence"]
    with pytest.raises(LumenError):
        core.grade_attempt("alg", "alice", first["id"], 0, 0, 4, "Not legible", [corrected["id"]])


def test_pages_continue_questions_without_inventing_boundaries_and_scan_stays_pending(core, tmp_path):
    from course_tutor.models import SourceSection
    import uuid
    data = exam(core, tmp_path, "Cover only", "Multi page")
    sid = data["source_version_id"]
    from course_tutor.storage.repositories import SourceRepository
    repo = SourceRepository(core.con)
    for index, text in [(1, "Question 1: Count paths.\n(a) Start here."), (2, "Continue part (a) with this diagram.\nQuestion 2: Prove correctness.")]:
        repo.add_source_section(SourceSection(id=str(uuid.uuid4()), source_version_id=sid, course_id="alg", section_index=index,
            label=f"Page {index}", text=text, quality_flag="has_images" if index == 2 else "good", metadata={"page_index": index}))
    # Explicit host candidates can add missing source-derived questions after a
    # conservative initial catalog. Automatic extraction remains idempotent.
    core.catalog_exam_questions("alg", sid, questions=[{"question_key": "1", "question_text": "Count paths.\n(a) Start here.\nContinue part (a) with this diagram.",
        "source_spans": [{"section_index": 1}, {"section_index": 2, "end_offset": 38}]}])
    question = core.list_questions("alg", sid)["questions"][0]
    assert len(question["source_spans"]) == 2
    assert "has_images" in question["quality_flags"]
    assert not core.exam_catalog_status("alg", sid)["coverage_verified"]


def test_all_lifecycle_history_survives_backup_restore(core, tmp_path):
    data = exam(core, tmp_path, "Question 1: Count the leaves.")
    version = checked(core)
    att, ev = work(core, version, correct=True, hint=True)
    core.grade_attempt("alg", "alice", att["id"], 0, 4, 4, "Valid after a hint", [ev["id"]])
    before = core.attempt_history("alg", "alice", att["id"])
    backup_path = tmp_path / "backup.zip"
    core.backup(backup_path)
    restored_path = tmp_path / "restored"
    LumenCore.restore(backup_path, restored_path)
    with LumenCore(restored_path) as restored:
        assert restored.attempt_history("alg", "alice", att["id"]) == before
        assert len(restored.list_questions("alg", data["source_version_id"])["questions"]) == 1
        assert restored.con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_metadata_enrichment_keeps_revision_history_and_topic_isolation(core, tmp_path):
    sid = exam(core, tmp_path, "Question 1: A two-part tree question.")["source_version_id"]
    q = core.list_questions("alg", sid)["questions"][0]
    topic = core.create_topic("alg", "Trees")["id"]
    updated = core.update_exercise_version(q["exercise_version_id"], expected_revision=1,
        subparts=[{"key": "a"}, {"key": "b"}], topic_mappings=[topic], skill_mappings=["count"])
    assert updated["revision_history"][0]["subparts"] == []
    assert updated["subparts"] == [{"key": "a"}, {"key": "b"}]
    foreign = core.create_topic("other", "Foreign")["id"]
    with pytest.raises(LumenError):
        core.update_exercise_version(q["exercise_version_id"], expected_revision=2, topic_mappings=[foreign])
    core.review_question_occurrence("alg", q["id"], 1, "accepted", "Verified both parts")
    core.update_exercise_version(q["exercise_version_id"], expected_revision=2, question_text="Corrected transcription")
    current = core.list_questions("alg", sid)["questions"][0]
    assert current["extracted_text"] == "A two-part tree question."
    assert current["review_status"] == "pending_review"
    assert core.course_brief("alg")["exam_catalogs"]["pending_review"] == 1


def test_numeric_template_exposure_beyond_bounded_similarity_edges(core):
    # Relation discovery stores bounded candidates; hash groups still protect
    # against repeating a previously seen member of a very large variant group.
    versions = [checked(core, f"A full binary tree has {i} leaves. Count internal nodes.", f"pattern-{i}") for i in range(105)]
    core.start_attempt("alg", versions[-1], learner_id="alice")
    assert core.propose_practice("alg", "alice", count=3)["candidates"] == []
    assert core.propose_practice("alg", "bob", count=3)["shortfall"] == 2


def test_actual_pdf_extraction_continues_question_across_pages(core, tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")}))
    for line in ("Question 1: Count leaves.", "Continue the argument.\nQuestion 2: Prove correctness."):
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(("BT /F1 12 Tf 40 750 Td 18 TL\n" + "\n".join(f"({part}) Tj T*" for part in line.splitlines()) + "\nET").encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "exam.pdf"
    writer.write(path)
    sid = core.ingest_source("alg", path, role="exam")["data"]["source_version_id"]
    questions = {q["question_key"]: q for q in core.list_questions("alg", sid)["questions"]}
    assert set(questions) == {"1", "2"}
    assert "Continue the argument." in questions["1"]["extracted_text"]
    assert len(questions["1"]["source_spans"]) == 2
    assert {s["locator"]["page_index"] for s in questions["1"]["source_spans"]} == {0, 1}


def test_concurrent_grade_revision_conflict_preserves_first_result(core):
    version = checked(core)
    att, ev = work(core, version, correct=True)
    with LumenCore(core.workspace_root) as other:
        core.grade_attempt("alg", "alice", att["id"], 0, 4, 4, "Checked once", [ev["id"]])
        with pytest.raises(LumenError):
            other.grade_attempt("alg", "alice", att["id"], 0, 4, 4, "Stale competing grade", [ev["id"]])
    assert len(core.attempt_history("alg", "alice", att["id"])["grades"]) == 1


def test_cli_catalog_review_grade_and_correction_workflow(core, tmp_path):
    def cli(operation, params, request=None):
        args = [sys.executable, "-m", "course_tutor.cli", operation, "-w", str(core.workspace_root), "-c", "alg", "-j", json.dumps(params)]
        if request:
            args += ["-r", request]
        result = subprocess.run(args, text=True, capture_output=True, check=True)
        return json.loads(result.stdout)["data"]
    path = tmp_path / "exam.txt"
    path.write_text("Question 1: Count leaves in this full binary tree.")
    upload = cli("ingest-source", {"file_path": str(path), "role": "exam"}, "cli-upload")
    sid = upload["source_version_id"]
    cli("catalog-exam-questions", {"source_version_id": sid}, "cli-catalog")
    q = cli("list-questions", {"source_version_id": sid})["questions"][0]
    cli("review-question-occurrence", {"occurrence_id": q["id"], "expected_revision": 1, "status": "accepted", "notes": "Compared original question"}, "cli-review")
    cli("update-exercise-version", {"version_id": q["exercise_version_id"], "expected_revision": 1,
        "subparts": ["default"], "reference_solution": "Count the leaves explicitly.", "rubric": {"max_points": 4}}, "cli-enrich")
    cli("validate-exercise-version", {"version_id": q["exercise_version_id"], "expected_revision": 2, "checks": {"review": True}}, "cli-validate")
    state = cli("exam-catalog-status", {"source_version_id": sid})
    cli("review-exam-catalog", {"source_version_id": sid, "expected_revision": state["revision"], "expected_question_count": 1,
        "notes": "All original pages and question count checked", "checks": {"all_pages_reviewed": True, "question_count_verified": True}}, "cli-review-exam")
    att, evidence = work(core, q["exercise_version_id"], correct=True)
    grade = cli("grade-attempt", {"learner_id": "alice", "attempt_id": att["id"], "expected_grade_revision": 0,
        "points_awarded": 4, "max_points": 4, "feedback": "Correct leaf count", "evidence_ids": [evidence["id"]]}, "cli-grade")
    assert grade["correctness"] == "correct"
    history = cli("attempt-history", {"learner_id": "alice", "attempt_id": att["id"]})
    assert history["grades"][0]["feedback"] == "Correct leaf count"
    assert not history["summary"]["shown"]  # No presentation was fabricated.
    cli("grade-attempt", {"learner_id": "alice", "attempt_id": att["id"], "expected_grade_revision": 1,
        "points_awarded": 4, "max_points": 4, "feedback": "Correct count and clear explanation", "evidence_ids": [evidence["id"]],
        "correction_reason": "Clarify feedback"}, "cli-feedback-correction")
    assert len(cli("attempt-history", {"learner_id": "alice", "attempt_id": att["id"]})["grades"]) == 2
    assert cli("list-question-relations", {})["relations"] == []


def test_unreviewed_catalog_question_cannot_bypass_validation(core, tmp_path):
    sid = exam(core, tmp_path, "Question 1: Count leaves.")["source_version_id"]
    q = core.list_questions("alg", sid)["questions"][0]
    with pytest.raises(LumenError):
        core.validate_exercise_version(q["exercise_version_id"], expected_revision=1,
            reference_solution="Checked answer", rubric={"max_points": 4}, checks={"review": True})


def test_grade_cannot_hide_incorrect_skill_from_the_same_submitted_part(core):
    version = checked(core)
    att, positive = work(core, version, correct=True)
    negative = core.commit_evidence(att["id"], [{"topic_id": positive["topic_id"], "skill_id": "explanation", "correct": False,
        "rationale": "Counting result correct, justification incorrect."}])["data"]["evidence_created"][0]
    with pytest.raises(LumenError):
        core.grade_attempt("alg", "alice", att["id"], 0, 4, 4, "Omitted the incorrect justification", [positive["id"]])
    result = core.grade_attempt("alg", "alice", att["id"], 0, 2, 4, "Counting correct; justification incorrect", [positive["id"], negative["id"]])
    assert result["data"]["correctness"] == "partial"
    assert not core.attempt_history("alg", "alice", att["id"])["summary"]["answered_correctly"]


def test_exact_fingerprints_preserve_code_indentation_case_and_operators(core):
    texts = ["if x:\n    y = 1\nz = 2", "if x:\n    y = 1\n    z = 2", "if X:\n    y = 1\nz = 2", "if x:\n    y != 1\nz = 2"]
    versions = [checked(core, text, f"syntax-{i}") for i, text in enumerate(texts)]
    hashes = {r[0] for r in core.con.execute("SELECT exact_hash FROM question_fingerprints")}
    assert len(hashes) == 4
    assert not any(r["kind"] == "exact" for r in core.list_question_relations("alg")["relations"])
