"""Readiness regressions: metadata gates, pair conflicts, assignment and no writes."""

import itertools
import json
import subprocess
import sys
import uuid

import pytest

from course_tutor.api import CourseTutor
from course_tutor.assessment import readiness
from course_tutor.errors import LumenError


@pytest.fixture
def core(tmp_path):
    with CourseTutor(tmp_path / "workspace") as c:
        c.create_course("Algorithms", course_id="alg")
        c.create_course("Other", course_id="other")
        yield c


def question(c, name, topics=None, family=None):
    vid = c.create_exercise("alg", family or name, "Secret question " + name,
                            topic_mappings=topics, reference_solution="Secret solution", rubric={"secret": 7})["exercise_version_id"]
    c.validate_exercise_version(vid, expected_revision=1, checks={"review": True})
    # Keep fixtures independent of automatic lexical candidate discovery.
    c.con.execute("UPDATE question_fingerprints SET exact_hash=?,structure_hash=? WHERE exercise_version_id=?", (vid, vid, vid))
    return vid


def edge(c, a, b, status="pending_review", stale=False):
    a, b = sorted((a, b))
    c.con.execute("""INSERT INTO question_relations
        (id,course_id,left_version_id,right_version_id,left_hash,right_hash,kind,method,similarity,status,created_at)
        VALUES (?,'alg',?,?,?,?,'similar','manual',0.9,?,'now')""",
        (str(uuid.uuid4()), a, b, "old" if stale else a, b, status))


def report(c, *slots, learner="alice"):
    return c.blueprint_readiness("alg", {"slots": list(slots) or [{"id": "s", "count": 1}]}, learner)


def slot(name="s", count=1, **kwargs):
    return dict(id=name, count=count, **kwargs)


@pytest.mark.parametrize("blueprint", [None, {}, [], {"slots": []}, {"slots": [], "x": 1},
    {"slots": [None]}, {"slots": [slot(count=True)]}, {"slots": [slot(count=0)]},
    {"slots": [slot(count=101)]}, {"slots": [slot("")]}, {"slots": [slot(), slot()]},
    {"slots": [slot(topic_ids=[])]}, {"slots": [slot(topic_ids="x")]},
    {"slots": [slot(section=None)]}, {"slots": [slot(question_type=" ")]},
    {"slots": [slot(unsupported="x")]}, {"slots": [slot(str(i)) for i in range(101)]}])
def test_invalid_blueprints(core, blueprint):
    with pytest.raises(LumenError):
        core.blueprint_readiness("alg", blueprint)


def test_scope_and_learner_validation(core):
    foreign = core.create_topic("other", "Foreign")["id"]
    for cid, bp, learner in [("absent", {"slots": [slot()]}, "a"),
                             ("alg", {"slots": [slot(topic_ids=[foreign])]}, "a"),
                             ("alg", {"slots": [slot(topic_ids=["missing"])]}, "a"),
                             ("alg", {"slots": [slot()]}, None)]:
        with pytest.raises(LumenError):
            core.blueprint_readiness(cid, bp, learner)


def test_counts_family_variants_and_non_greedy_matching(core):
    ta = core.create_topic("alg", "A", slug="a")["id"]
    tb = core.create_topic("alg", "B", slug="b")["id"]
    a = question(core, "a", ["a"], "shared")
    b = question(core, "b", [tb], "shared")
    c = question(core, "c", [ta])
    r = report(core, slot("a", topic_ids=[ta]), slot("b", topic_ids=[tb]))
    assert [s["available"] for s in r["slots"]] == [2, 1]
    assert r["slots"][0]["eligible"]["version_ids"] == sorted([a, c])
    assert r["analysis"]["joint"]["status"] == "feasible"
    assert {v["version_id"] for v in r["analysis"]["joint"]["assignment"]} == {b, c}
    assert r["analysis"]["capacity"]["lower_bound"] == 1
    overlap = report(core, slot("a", count=2), slot("b"))
    assert all(s["shortfall"] == 0 for s in overlap["slots"])
    assert overlap["analysis"]["joint"]["status"] == "infeasible"
    assert overlap["analysis"]["joint"]["matched_upper_bound"] == 2
    assert overlap["analysis"]["joint"]["gaps"][0]["slot_ids"] == ["a", "b"]


def test_metadata_and_independent_review_gates(core, tmp_path):
    topic = core.create_topic("alg", "Graphs", slug="graphs")["id"]
    path = tmp_path / "exam.txt"
    path.write_text("\n".join(f"Question {i}: Unique item {i}." for i in range(1, 9)))
    sid = core.ingest_source("alg", path, role="exam")["data"]["source_version_id"]
    qs = core.list_questions("alg", sid)["questions"]
    for i, q in enumerate(qs):
        core.con.execute("UPDATE exercise_versions SET validation_state='validated',topic_mappings_json=? WHERE id=?", (json.dumps(["graphs"]), q["exercise_version_id"]))
        meta = {"section": "A", "question_type": "proof"}
        if i == 1:
            meta["section"] = "B"
        if i == 2:
            meta["section"] = None
        if i == 3:
            meta["question_type"] = []
        core.con.execute("UPDATE question_occurrences SET metadata_json=?,review_status='accepted',visual_review_status='verified' WHERE id=?", (json.dumps(meta), q["id"]))
    core.con.execute("UPDATE question_occurrences SET review_status='pending_review' WHERE id=?", (qs[4]["id"],))
    core.con.execute("UPDATE question_occurrences SET visual_review_status='pending_review' WHERE id=?", (qs[5]["id"],))
    core.con.execute("UPDATE exercise_versions SET validation_state='contradictory' WHERE id=?", (qs[6]["exercise_version_id"],))
    core.con.execute("UPDATE exercise_versions SET validation_state='pending_review' WHERE id=?", (qs[7]["exercise_version_id"],))
    free = question(core, "no source", [])
    s = report(core, slot(section="A", question_type="proof", topic_ids=[topic]))["slots"][0]
    assert s["available"] == 1
    assert s["eligible"]["occurrence_ids"] == [qs[0]["id"]]
    assert s["unknown_required_metadata"]["section"]["version_ids"] == sorted([free, qs[2]["exercise_version_id"]])
    assert s["unknown_required_metadata"]["question_type"]["count"] == 2
    assert s["unknown_required_metadata"]["topic_ids"]["version_ids"] == [free]
    assert s["pending_review"]["count"] == 3
    assert s["exclusions"]["math_contradictory"]["count"] == 1
    # A known mismatch prevents claiming that this is a potentially useful pending item.
    core.con.execute("UPDATE question_occurrences SET review_status='pending_review' WHERE id=?", (qs[1]["id"],))
    assert report(core, slot(section="A"))["slots"][0]["pending_review"]["count"] == 3
    core.con.execute("UPDATE question_occurrences SET review_status='rejected',visual_review_status='rejected' WHERE id=?", (qs[0]["id"],))
    excluded = report(core)["slots"][0]["exclusions"]
    assert excluded["extraction_rejected"]["count"] == excluded["visual_rejected"]["count"] == 1


@pytest.mark.parametrize("kind", ["family", "exact", "template", "pending", "rejected", "stale"])
def test_exposure_pair_semantics(core, kind):
    a = question(core, "a")
    b = question(core, "b", family="a" if kind == "family" else None)
    if kind in ("exact", "template"):
        field = "exact_hash" if kind == "exact" else "structure_hash"
        core.con.execute(f"UPDATE question_fingerprints SET {field}=? WHERE exercise_version_id=?", (a, b))
    if kind in ("pending", "rejected", "stale"):
        edge(core, a, b, "rejected" if kind == "rejected" else "pending_review", kind == "stale")
    core.start_attempt("alg", a, learner_id="alice")
    assert report(core)["slots"][0]["available"] == (1 if kind in ("rejected", "stale") else 0)
    assert report(core, learner="bob")["slots"][0]["eligible"]["count"] == 2


def test_template_rejection_is_pair_specific_and_nontransitive(core):
    a, b, c = [question(core, n) for n in "abc"]
    core.con.execute("UPDATE question_fingerprints SET structure_hash='same' WHERE exercise_version_id IN (?,?)", (a, b))
    edge(core, a, b, "rejected")
    edge(core, b, c)
    r = report(core, slot(count=2))
    assert r["analysis"]["joint"]["status"] == "feasible"
    assert r["analysis"]["joint"]["matched_lower_bound"] == 2
    assert r["analysis"]["capacity"]["exact"]
    core.start_attempt("alg", a, learner_id="alice")
    assert report(core)["slots"][0]["eligible"]["version_ids"] == sorted([b, c])


def test_nontransitive_similarity_capacity_and_conflict_aware_search(core):
    ids = sorted(question(core, n) for n in "abc")
    a, b, c = ids
    edge(core, a, b)
    edge(core, b, c)
    r = report(core, slot(count=2))
    assert r["analysis"]["joint"]["status"] == "feasible"
    assert {x["version_id"] for x in r["analysis"]["joint"]["assignment"]} == {a, c}
    assert r["analysis"]["capacity"]["lower_bound"] == r["analysis"]["capacity"]["upper_bound"] == 1
    single = report(core)["analysis"]["capacity"]
    assert single["lower_bound"] == single["upper_bound"] == 2


def test_budget_stop_is_unknown_and_bounds_are_honest(core, monkeypatch):
    ids = sorted(question(core, n) for n in "abcd")
    for a, b in itertools.combinations(ids, 2):
        edge(core, a, b)
    monkeypatch.setattr(readiness, "SEARCH_NODE_BUDGET", 0)
    r = report(core, slot(count=2))
    j = r["analysis"]["joint"]
    assert j["status"] == "unknown" and not j["exact"]
    assert j["matched_lower_bound"] == 1 and j["matched_upper_bound"] == 2
    cap = r["analysis"]["capacity"]
    assert (cap["lower_bound"], cap["upper_bound"], cap["exact"]) == (0, 2, False)
    monkeypatch.setattr(readiness, "SEARCH_NODE_BUDGET", 20000)
    assert report(core, slot(count=2))["analysis"]["joint"]["status"] == "infeasible"


def test_reservations_and_exposure_are_separate_and_learner_scoped(core):
    a, b, c, d = [question(core, n) for n in "abcd"]
    core.create_assessment("alg", "Alice", selected_exercise_version_ids=[a], learner_id="alice")
    core.create_assessment("alg", "Everyone", selected_exercise_version_ids=[b])
    core.create_assessment("alg", "Bob", selected_exercise_version_ids=[c], learner_id="bob")
    core.start_attempt("alg", a, learner_id="alice")
    r = report(core)
    assert r["slots"][0]["eligible"]["version_ids"] == sorted([c, d])
    assert r["reservation_only"]["version_ids"] == [b]
    assert r["slots"][0]["exclusions"]["assessment_reservation"]["count"] == 2
    assert r["slots"][0]["exclusions"]["learner_exposure"]["count"] == 1
    assert r["analysis"]["capacity"]["lower_bound"] == 2
    assert r["without_reservations"]["capacity"]["lower_bound"] == 3
    assert r["reservation_capacity_improvement"] == dict(lower_bound=1, upper_bound=1, exact=True, relief="proven")
    assert report(core, learner="bob")["slots"][0]["eligible"]["version_ids"] == sorted([a, d])
    core.con.execute("UPDATE assessments SET status='completed'")
    completed = report(core)
    assert completed["analysis"] == r["analysis"]
    assert completed["without_reservations"] == r["without_reservations"]
    assert completed["safely_releasable_assessment_ids"] == []
    assert completed["safe_release_capacity_improvement"]["relief"] == "none"


def test_multiple_tests_share_one_family_pool(core):
    ta = core.create_topic("alg", "A")["id"]
    tb = core.create_topic("alg", "B")["id"]
    for n in range(4):
        question(core, f"a{n}", [ta])
    for n in range(2):
        question(core, f"b{n}", [tb])
    r = report(core, slot("a", topic_ids=[ta]), slot("b", topic_ids=[tb]))
    assert r["analysis"]["capacity"]["lower_bound"] == r["analysis"]["capacity"]["upper_bound"] == 2


def test_read_snapshot_no_writes_no_content_and_determinism(core):
    question(core, "a")
    tables = ["exercise_versions", "exercises", "attempts", "assessment_items", "assessments", "question_relations", "question_occurrences", "operation_receipts"]
    # Snapshot every extant relevant table without depending on receipt-table naming.
    tables = [t for t in tables if core.con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone()]
    before = {t: [tuple(r) for r in core.con.execute(f"SELECT * FROM {t}")] for t in tables}
    changes = core.con.total_changes
    statements = []
    core.con.set_trace_callback(statements.append)
    r = report(core)
    assert not core.con.in_transaction
    core.con.execute("BEGIN")
    completed = report(core)
    assert completed["analysis"] == r["analysis"]
    assert completed["without_reservations"] == r["without_reservations"]
    assert completed["safely_releasable_assessment_ids"] == []
    assert completed["safe_release_capacity_improvement"]["relief"] == "none"
    assert core.con.in_transaction
    core.con.execute("ROLLBACK")
    core.con.set_trace_callback(None)
    assert core.con.total_changes == changes
    assert before == {t: [tuple(r) for r in core.con.execute(f"SELECT * FROM {t}")] for t in tables}
    assert "Secret" not in json.dumps(r)
    assert not any(any(key in q.lower() for key in ("question_text", "reference_solution", "rubric")) for q in statements)


def test_cli_success_and_validation_error(core, tmp_path):
    question(core, "a")
    workspace = str(core.workspace_root)
    core.close()
    base = [sys.executable, "-m", "course_tutor.cli", "blueprint-readiness", "-w", workspace, "-c", "alg", "-j"]
    proc = subprocess.run(base + [json.dumps({"blueprint": {"slots": [slot()]}})], text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["data"]["analysis"]["joint"]["status"] == "feasible"
    proc = subprocess.run(base + [json.dumps({"blueprint": {"slots": [slot(count=True)]}})], text=True, capture_output=True)
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["status"] == "error"


def test_small_conflict_graphs_match_exhaustive_capacity():
    # All 64 graphs on four vertices, with overlapping slot eligibility and a
    # family variant, independently verify the optimizer's exact bound claims.
    vids = list("abcd")
    pairs = list(itertools.combinations(vids, 2))
    rows = {v: {"exercise_family": v} for v in vids}
    cases = [([slot(count=1)], {"s": vids}),
             ([slot("x"), slot("y")], {"x": ["a", "b", "c"], "y": ["b", "c", "d"]})]
    for mask in range(64):
        conflicts = {v: set() for v in vids}
        for index, (a, b) in enumerate(pairs):
            if mask & (1 << index):
                conflicts[a].add(b)
                conflicts[b].add(a)
        for slots, candidates in cases:
            analysis = readiness._analysis(slots, candidates, rows, conflicts)
            need = sum(s["count"] for s in slots)
            expected = 0
            for copies in range(1, 4 // need + 1):
                units = [s["id"] for s in slots for _ in range(s["count"] * copies)]
                valid = any(len(set(assignment)) == len(assignment) and
                            all(b not in conflicts[a] for a, b in itertools.combinations(assignment, 2))
                            for assignment in itertools.product(*(candidates[s] for s in units)))
                if valid:
                    expected = copies
            cap = analysis["capacity"]
            assert cap["exact"]
            assert cap["lower_bound"] == cap["upper_bound"] == expected
            assert (analysis["joint"]["status"] == "feasible") == (expected >= 1)


def test_conflict_search_preserves_variant_fit():
    rows = {v: {"exercise_family": f} for v, f in [("a", "shared"), ("b", "shared"), ("c", "other")]}
    conflicts = {"a": {"c", "b"}, "b": {"a"}, "c": {"a"}}
    result = readiness._analysis([slot("x"), slot("y")], {"x": ["a", "b"], "y": ["c"]}, rows, conflicts)
    assert result["joint"]["status"] == "feasible"
    assert {a["version_id"] for a in result["joint"]["assignment"]} == {"b", "c"}


def test_uncertain_reservation_relief_stays_an_interval(core, monkeypatch):
    ids = sorted(question(core, n) for n in "abcd")
    for a, b in itertools.combinations(ids, 2):
        edge(core, a, b)
    # Reserve an unrelated candidate; all other conflicts remain unresolved at zero budget.
    reserved = question(core, "reserved")
    core.create_assessment("alg", "Reserved", selected_exercise_version_ids=[reserved], learner_id="alice")
    monkeypatch.setattr(readiness, "SEARCH_NODE_BUDGET", 0)
    result = report(core)
    improvement = result["reservation_capacity_improvement"]
    assert improvement["relief"] == "uncertain" and not improvement["exact"]
    assert improvement["lower_bound"] == 0 and improvement["upper_bound"] >= 1
    assert result["reservation_only"]["version_ids"] == [reserved]


def test_overlap_bottleneck_omits_unrelated_slot(core):
    ta = core.create_topic("alg", "A")["id"]
    tb = core.create_topic("alg", "B")["id"]
    question(core, "a", [ta])
    question(core, "b", [tb])
    r = report(core, slot("x", topic_ids=[ta]), slot("y", topic_ids=[ta]), slot("z", topic_ids=[tb]))
    bottleneck = r["analysis"]["joint"]["overlap_bottlenecks"][0]
    assert bottleneck == dict(reason="shared_family_pool_shortfall", slot_ids=["x", "y"],
                              topic_ids=[ta], needed=2, available_families=1, shortfall=1)
    assert len(r["topic_bottlenecks"]) == 2


def test_extended_schema_and_full_public_gap(core):
    result = core.blueprint_readiness('alg', {'duration_minutes': 30, 'slots': [
        {'id': 'z', 'count': 2, 'section': 'A', 'question_type': 'proof', 'max_points': 7.5}]}, 'alice')
    assert result['gaps'][0] == {
        'slot_id': 'z', 'section': 'A', 'topic_ids': [], 'question_type': 'proof',
        'needed': 2, 'eligible': 0, 'shortfall': 2, 'exclusion_reasons': {},
        'joint_reason': 'joint_conflict_or_shared_pool',
        'joint_shortfall_lower_bound': 2, 'joint_shortfall_upper_bound': 2}
    for points in (False, 0, float('nan'), float('inf'), 10 ** 1000):
        with pytest.raises(LumenError):
            core.blueprint_readiness('alg', {'slots': [{'id': 's', 'count': 1, 'max_points': points}]})


def draft(c, vid, owner="alice"):
    return c.create_assessment("alg", "Draft", selected_exercise_version_ids=[vid],
                               learner_id=owner)["data"]["assessment_id"]


def release_draft(c, aid, owner="alice"):
    from course_tutor.storage.db import atomic_transaction
    from course_tutor.storage.repositories import ReservationRepository
    with atomic_transaction(c.con):
        ReservationRepository(c.con).release(course_id="alg", learner_id=owner, assessment_id=aid)


def test_safe_release_retains_overlapping_unsafe_reservations_and_attempts(core):
    a, b, c = [question(core, n) for n in "abc"]
    safe = draft(core, a)
    unsafe = draft(core, a, None)
    core.con.execute("UPDATE assessments SET status='completed' WHERE id=?", (unsafe,))
    unused = draft(core, b)
    attempted = draft(core, c)
    core.start_attempt("alg", c, learner_id="alice")
    r = report(core)
    assert r["safely_releasable_assessment_ids"] == sorted([safe, unused, attempted])
    assert r["safe_release_relief"]["version_ids"] == [b]
    assert r["slots"][0]["safe_release_relief"]["family_ids"] == ["b"]
    assert r["safe_release_capacity_improvement"] == dict(lower_bound=1, upper_bound=1, exact=True, relief="proven")
    assert r["without_reservations"]["capacity"]["lower_bound"] == 2
    assert r["without_safe_releases"]["capacity"]["lower_bound"] == 1
    release_draft(core, safe)
    release_draft(core, unused)
    release_draft(core, attempted)
    assert report(core)["slots"][0]["eligible"]["version_ids"] == [b]
    assert report(core, learner="bob")["slots"][0]["eligible"]["version_ids"] == sorted([b, c])


def test_safe_release_unowned_scope_and_read_only_bounds(core, monkeypatch):
    ids = [question(core, n) for n in "abcd"]
    for a, b in itertools.combinations(ids[:3], 2):
        edge(core, a, b)
    aid = draft(core, ids[3], None)
    foreign = draft(core, ids[0], "bob")
    monkeypatch.setattr(readiness, "SEARCH_NODE_BUDGET", 0)
    before = core.con.total_changes
    r = report(core)
    assert core.con.total_changes == before
    assert r["safely_releasable_assessment_ids"] == [aid]
    assert foreign not in r["safely_releasable_assessment_ids"]
    assert r["safe_release_capacity_improvement"]["relief"] == "uncertain"
    assert not r["without_safe_releases"]["capacity"]["exact"]
    release_draft(core, aid, None)
    assert ids[3] in report(core)["slots"][0]["eligible"]["version_ids"]


def test_pending_publication_retained_in_safe_counterfactual(core):
    from course_tutor.storage.db import atomic_transaction
    from course_tutor.storage.repositories import AssemblyRepository
    a = question(core, "pending")
    draft(core, a)
    with atomic_transaction(core.con):
        AssemblyRepository(core.con).create(request_id="pending", input_hash="hash", assessment_id="pending-exam",
            course_id="alg", learner_id="alice", owner_token="owner", staging_path="/stage", final_path="/final",
            generation={}, items=[dict(item_id="pending-item", exercise_version_id=a, item_order=1,
                slot_id="s", max_points=1, exercise_revision=1, exercise_content_hash="hash", snapshot={})])
    r = report(core)
    assert r["safe_release_relief"]["count"] == 0
    assert r["without_safe_releases"]["joint"]["status"] == "infeasible"
    assert r["without_reservations"]["joint"]["status"] == "feasible"


@pytest.mark.parametrize("field,value", [("points_awarded", 0), ("score_status", "pending_review"),
    ("score_history_json", '[{"previous": "score"}]')])
def test_used_saved_assessment_has_no_safe_relief(core, field, value):
    a = question(core, "used")
    aid = draft(core, a)
    core.con.execute(f"UPDATE assessment_items SET {field}=? WHERE assessment_id=?", (value, aid))
    before = core.con.total_changes
    r = report(core)
    assert core.con.total_changes == before
    assert r["safely_releasable_assessment_ids"] == []
    assert r["without_safe_releases"]["capacity"]["upper_bound"] == 0
    assert r["without_reservations"]["capacity"]["lower_bound"] == 1
