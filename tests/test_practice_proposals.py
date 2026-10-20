"""Practice proposals generalize the original algorithms skills' novelty rules."""

import json
import subprocess
import sys

import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import LumenError


@pytest.fixture
def bank(tmp_path):
    with LumenCore(tmp_path / "workspace") as core:
        core.create_course("Probability", course_id="prob")
        core.create_course("Other", course_id="other")
        topic = core.create_topic("prob", "Conditioning", slug="conditional")
        yield core, topic


def question(core, topic, family, *, checked=True, course_id="prob", mapping=None):
    version = core.create_exercise(
        course_id, family, f"Generated: {family}", topic_mappings=mapping or [topic["id"]],
        reference_solution="PRIVATE REFERENCE SOLUTION", rubric={"max_points": 4, "private_key": "PRIVATE KEY"},
    )["exercise_version_id"]
    if checked:
        core.validate_exercise_version(version, checks={"reviewed": True}, expected_revision=1)
    return version


def test_proposals_are_read_only_distinct_and_do_not_expose_solutions(bank):
    core, topic = bank
    first = question(core, topic, "same-pattern")
    variant = question(core, topic, "same-pattern")
    second = question(core, topic, "different-pattern")
    question(core, topic, "unreviewed", checked=False)
    before = core.con.total_changes
    proposal = core.propose_practice("prob", count=3)
    assert core.con.total_changes == before
    assert proposal["recorded"] is False
    assert proposal["shortfall"] == 1
    ids = {q["exercise_version_id"] for q in proposal["candidates"]}
    assert ids == {first, second}
    assert variant not in ids
    assert "PRIVATE" not in json.dumps(proposal)
    assert core.con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert core.con.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 0
    assert core.propose_practice("prob", count=3) == proposal


def test_attempts_exclude_the_entire_family_for_only_that_learner(bank):
    core, topic = bank
    first = question(core, topic, "seen")
    question(core, topic, "seen")
    unseen = question(core, topic, "unseen")
    core.start_attempt("prob", first, learner_id="alice")
    assert [q["exercise_version_id"] for q in core.propose_practice("prob", learner_id="alice", count=2)["candidates"]] == [unseen]
    assert core.propose_practice("prob", learner_id="bob", count=2)["shortfall"] == 0
    repeated = core.propose_practice("prob", learner_id="alice", count=2, allow_repeats=True)["candidates"]
    assert [q["exercise_version_id"] for q in repeated] == [unseen, first]
    assert repeated[1]["is_repeat_or_reserved"]
    assert repeated[1]["prior_attempts_in_family"] == 1


def test_assessment_reservations_and_current_batch_exclusions(bank):
    core, topic = bank
    reserved = question(core, topic, "reserved")
    question(core, topic, "reserved")
    selected = question(core, topic, "selected-in-this-batch")
    question(core, topic, "selected-in-this-batch")
    fresh = question(core, topic, "fresh")
    core.create_assessment("prob", "Draft", {}, [reserved], learner_id="alice")
    result = core.propose_practice("prob", learner_id="alice", count=3, exclude_exercise_version_ids=[selected])
    assert [q["exercise_version_id"] for q in result["candidates"]] == [fresh]
    assert result["shortfall"] == 2
    assert len(core.propose_practice("prob", learner_id="bob", count=3)["candidates"]) == 3
    core.create_assessment("prob", "Unowned draft", {}, [fresh])
    assert all(q["exercise_version_id"] != fresh for q in core.propose_practice("prob", learner_id="bob", count=3)["candidates"])


def test_topic_slug_mappings_current_validation_and_course_boundaries(bank):
    core, topic = bank
    matched = question(core, topic, "matches", mapping=[topic["slug"]])
    other = core.create_topic("prob", "Other topic")
    question(core, other, "does-not-match")
    foreign = core.create_topic("other", "Foreign topic")
    foreign_version = question(core, foreign, "matches", course_id="other")
    assert [q["exercise_version_id"] for q in core.propose_practice("prob", topic_ids=[topic["id"]], count=3)["candidates"]] == [matched]
    with pytest.raises(LumenError):
        core.propose_practice("prob", topic_ids=[foreign["id"]])
    with pytest.raises(LumenError):
        core.propose_practice("prob", exclude_exercise_version_ids=[foreign_version])
    core.update_exercise_version(matched, question_text="Changed: requires a fresh review", expected_revision=1)
    assert core.propose_practice("prob", topic_ids=[topic["id"]])["candidates"] == []


@pytest.mark.parametrize("parameters", [{"count": True}, {"count": 0}, {"count": 1.5}, {"allow_repeats": "false"},
                                       {"topic_ids": "all"}, {"exclude_exercise_version_ids": [None]}, {"learner_id": ""}])
def test_invalid_proposals_do_not_mutate(bank, parameters):
    core, _ = bank
    before = core.con.total_changes
    with pytest.raises(LumenError):
        core.propose_practice("prob", **parameters)
    assert core.con.total_changes == before


def test_propose_practice_cli(bank):
    core, topic = bank
    version = question(core, topic, "cli-family")
    args = [sys.executable, "-m", "course_tutor.cli", "propose-practice", "-w", str(core.workspace_root), "-c", "prob"]
    result = subprocess.run(args, input=json.dumps({"count": 2}), text=True, capture_output=True, check=True)
    data = json.loads(result.stdout)["data"]
    assert data["candidates"][0]["exercise_version_id"] == version
    assert data["shortfall"] == 1
    assert not data["recorded"]


def test_source_only_excludes_generated_questions_and_returns_exact_provenance(bank, tmp_path):
    core, topic = bank
    question(core, topic, 'generated-family')
    assert core.propose_practice('prob', source_only=True)['candidates'] == []
    source = tmp_path/'course-exercises.txt'
    source.write_text('Question 1: Compute P(A given B) from the supplied joint table.\n')
    sid = core.ingest_source('prob', source, role='exam')['data']['source_version_id']
    occurrence = core.list_questions('prob', sid)['questions'][0]
    core.review_question_occurrence('prob', occurrence['id'], 1, 'accepted', 'Compared with supplied text')
    core.validate_exercise_version(occurrence['exercise_version_id'], expected_revision=1,
        reference_solution='P(A intersection B)/P(B), for P(B)>0.',
        rubric={'max_points': 1}, checks={'review': True})
    proposal = core.propose_practice('prob', source_only=True, count=3)
    assert len(proposal['candidates']) == 1
    candidate = proposal['candidates'][0]
    assert candidate['exercise_version_id'] == occurrence['exercise_version_id']
    assert candidate['source_reference']['source_version_id'] == sid
    assert candidate['source_reference']['original_filename'] == source.name
    assert candidate['source_reference']['source_spans'] == occurrence['source_spans']
    assert proposal['shortfall'] == 2
    with pytest.raises(LumenError):
        core.propose_practice('prob', source_only='true')


def test_released_draft_is_fresh_with_historical_selection_count(bank):
    from course_tutor.storage.db import atomic_transaction
    from course_tutor.storage.repositories import ReservationRepository
    core, topic = bank
    vid = question(core, topic, "released")
    aid = core.create_assessment("prob", "Draft", {}, [vid], learner_id="alice")["data"]["assessment_id"]
    assert core.propose_practice("prob", learner_id="alice")["candidates"] == []
    with atomic_transaction(core.con):
        ReservationRepository(core.con).release(course_id="prob", learner_id="alice", assessment_id=aid)
    before = core.con.total_changes
    candidate = core.propose_practice("prob", learner_id="alice")["candidates"][0]
    assert core.con.total_changes == before
    assert candidate["exercise_version_id"] == vid
    assert candidate["assessment_selections_in_family"] == 1
    core.start_attempt("prob", vid, learner_id="alice")
    assert core.propose_practice("prob", learner_id="alice")["candidates"] == []
    assert core.propose_practice("prob", learner_id="bob")["candidates"][0]["exercise_version_id"] == vid


def test_pending_publication_reserves_practice_until_terminal_release(bank):
    from course_tutor.storage.db import atomic_transaction
    from course_tutor.storage.repositories import AssemblyRepository, ReservationRepository
    core, topic = bank
    vid = question(core, topic, "pending")
    with atomic_transaction(core.con):
        AssemblyRepository(core.con).create(request_id="pending", input_hash="hash", assessment_id="pending-exam",
            course_id="prob", learner_id="alice", owner_token="owner", staging_path="/stage", final_path="/final",
            generation={}, items=[dict(item_id="pending-item", exercise_version_id=vid, item_order=1,
                slot_id="s", max_points=1, exercise_revision=1, exercise_content_hash="hash", snapshot={})])
    assert core.propose_practice("prob", learner_id="alice")["candidates"] == []
    assert len(core.propose_practice("prob", learner_id="bob")["candidates"]) == 1
    with atomic_transaction(core.con):
        ReservationRepository(core.con).release(course_id="prob", learner_id="alice", assessment_id="pending-exam")
    assert len(core.propose_practice("prob", learner_id="alice")["candidates"]) == 1
