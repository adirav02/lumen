"""Checked mathematics and policy probes, not a model-accuracy benchmark."""

from fractions import Fraction as F
import importlib.util
from itertools import combinations
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("evaluate_education", ROOT / "scripts/evaluate_education.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)
FIXTURES = evaluation.DEFAULT_FIXTURES


def test_reviewed_cases_and_core_policy():
    reviews = json.loads((FIXTURES / "review-2026-10-19.json").read_text())
    report = evaluation.evaluate(reviews)
    assert report["cases"] == 16
    assert report["failed"] == 0, report
    cases = {row["id"]: row for row in report["results"]}
    assert cases["prior-hint"]["core_levels"] == ["assisted_success"]
    assert cases["later-solution"]["core_levels"] == ["independent_mastery"]
    assert cases["ambiguous-diagram"]["core_levels"] == []


def test_failed_judgments_remain_in_result_set():
    reviews = json.loads((FIXTURES / "review-2026-10-19.json").read_text())
    reviews[0]["evaluations"][0]["correct"] = False
    report = evaluation.evaluate(reviews)
    assert report["cases"] == 16 and report["failed"] == 1
    assert report["results"][0]["id"] == "bayes-exact"
    assert not report["results"][0]["passed"]
    with pytest.raises(ValueError, match="cover every case"):
        evaluation.evaluate(reviews[:-1])
    with pytest.raises(ValueError, match="Duplicate"):
        evaluation.evaluate(reviews + [reviews[0]])


def test_core_failure_retained_without_dropping_later_cases(monkeypatch):
    reviews = json.loads((FIXTURES / "review-2026-10-19.json").read_text())
    original = evaluation.LumenCore.commit_evidence
    count = 0

    def interrupted(core, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise RuntimeError("injected policy failure")
        return original(core, *args, **kwargs)

    monkeypatch.setattr(evaluation.LumenCore, "commit_evidence", interrupted)
    report = evaluation.evaluate(reviews)
    assert report["cases"] == 16 and report["failed"] == 1
    assert "injected policy failure" in report["results"][0]["issues"][0]
    assert report["results"][-1]["passed"]


def test_false_confirmation_on_ambiguous_work_is_critical():
    reviews = json.loads((FIXTURES / "review-2026-10-19.json").read_text())
    ambiguous = next(r for r in reviews if r["id"] == "ambiguous-diagram")
    ambiguous.update(decision="grade", evaluations=[{"subpart_key": "a", "correct": True}])
    report = evaluation.evaluate(reviews)
    assert report["failed"] == report["critical_failures"] == 1
    assert report["cases"] == 16


def test_exact_probability_and_algebra_references():
    # Arithmetic here is separate from the stored judgments and grading policy.
    prior, sensitivity, false_positive = F(1, 50), F(9, 10), F(1, 10)
    positive = prior*sensitivity + (1-prior)*false_positive
    assert positive == F(29, 250)
    assert prior*sensitivity/positive == F(9, 58)
    assert F(1, 4)/F(1, 2) == F(1, 2)
    with pytest.raises(ZeroDivisionError):
        F(0)/F(0)
    p = F(3, 10)
    assert p-p*p == F(21, 100)
    for x in (F(-3), F(-1), F(0), F(2), F(4)):
        assert (x*x-1)/(x-1) == x+1
    with pytest.raises(ZeroDivisionError):
        (F(1)**2-1)/(F(1)-1)
    # Squared-equation roots are candidates; the original RHS must be >=0.
    candidates = [x for x in range(-10, 11) if x*x == x+2]
    assert candidates == [-1, 2]
    assert [x for x in candidates if x >= 0] == [2]
    # A finite joint distribution constructs the covariance fixture exactly:
    # X=2U, Y=U+sqrt(8)V, independent symmetric U,V. Hence Var X=4,
    # Var Y=1+8=9, Cov=2, and Var(X+Y)=9+8=17.
    assert F(4)+F(9)+2*F(2) == 17


def test_diagram_paths_and_missing_label_change_answer():
    def paths(middle):
        edges = {"s": [("a", 2), ("b", 5)], "a": [("b", middle), ("t", 7)], "b": [("t", 2)]}
        def visit(node, seen, cost):
            if node == "t":
                yield (cost, seen)
            for nxt, weight in edges.get(node, []):
                if nxt not in seen:
                    yield from visit(nxt, seen+[nxt], cost+weight)
        return sorted(visit("s", ["s"], 0))
    assert paths(1)[0] == (5, ["s", "a", "b", "t"])
    assert paths(7)[0] == (7, ["s", "b", "t"])
    assert all((FIXTURES / name).read_bytes().startswith(b"\x89PNG") for name in ("graph.png", "graph-unknown.png"))


def test_graph_proofs_on_every_simple_four_vertex_graph():
    vertices = set(range(4))
    possible = list(combinations(vertices, 2))
    for mask in range(1 << len(possible)):
        edges = [edge for i, edge in enumerate(possible) if mask & (1 << i)]
        degrees = {v: sum(v in edge for edge in edges) for v in vertices}
        assert sum(degrees.values()) == 2*len(edges)
        assert sum(degree % 2 for degree in degrees.values()) % 2 == 0
        reached = {0}
        while True:
            expanded = reached | {v for a,b in edges if a in reached or b in reached for v in (a,b)}
            if expanded == reached:
                break
            reached = expanded
        if reached == vertices and len(edges) == 3:
            # Removing any edge disconnects these graphs, the tree property.
            for a,b in edges:
                remaining = [e for e in edges if e != (a,b)]
                visited = {a}
                for _ in vertices:
                    visited |= {v for x,y in remaining if x in visited or y in visited for v in (x,y)}
                assert b not in visited
