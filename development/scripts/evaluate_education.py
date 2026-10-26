"""Compare captured judgments to checked fixtures and exercise core policy.

This runner does not call a model and cannot measure unseen-model accuracy.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from course_tutor.api import LumenCore


DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures/educational_evaluation"


def _indexed(rows):
    indexed = {row["id"]: row for row in rows}
    if len(rows) != len(indexed):
        raise ValueError("Duplicate educational case IDs.")
    return indexed


def evaluate(reviews, fixtures=DEFAULT_FIXTURES):
    reviews_hash = hashlib.sha256(json.dumps(reviews, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    cases = _indexed(json.loads((fixtures / "cases.json").read_text()))
    refs = _indexed(json.loads((fixtures / "checked-references.json").read_text()))
    reviews = _indexed(reviews)
    if cases.keys() != refs.keys() or cases.keys() != reviews.keys():
        raise ValueError("Reviews and references must cover every case exactly; retain failures rather than omitting them.")
    results = []
    with tempfile.TemporaryDirectory() as directory:
        core = LumenCore(Path(directory) / "workspace")
        try:
            core.create_course("Generated educational policy evaluation", course_id="eval")
            topic = core.create_topic("eval", "Reviewed skills", slug="reviewed")
            for cid, case in cases.items():
                reference, review = refs[cid], reviews[cid]
                issues = []
                expected_parts = {e["subpart_key"]: e for e in reference["evaluations"]}
                submitted_evaluations = review.get("evaluations")
                critical = review.get("decision") == "grade" and (
                    reference["decision"] != "grade" or (
                        isinstance(submitted_evaluations, list) and any(
                            isinstance(e, dict) and e.get("correct") is True
                            and not expected_parts.get(e.get("subpart_key"), {}).get("correct", False)
                            for e in submitted_evaluations)))
                for field in ("decision", "evaluations"):
                    if review.get(field) != reference[field]:
                        issues.append(f"{field} differs from checked reference")
                if not isinstance(review.get("feedback"), str) or not review["feedback"].strip():
                    issues.append("missing feedback for human review")
                levels = []
                # Only checked decisions are persisted into this disposable workspace.
                # A mismatched review stays a failed result, never a corrected pass.
                if not issues and review["decision"] == "grade":
                    try:
                        ex = core.create_exercise("eval", cid, "GENERATED: " + case["question"],
                                                  subparts=[{"key": s} for s in case["subparts"]],
                                                  reference_solution=reference["derivation"])
                        attempt = core.start_attempt("eval", ex["exercise_version_id"])["data"]
                        aid, revision = attempt["id"], 1
                        for timing in ("before", "submission", "after"):
                            if timing == "submission":
                                core.record_attempt_event(aid, revision, "work_submission", subpart_key="a", content=case["submission"])
                                revision += 1
                            for event in case["assistance"]:
                                if event["timing"] == timing:
                                    core.record_attempt_event(aid, revision, event["type"], subpart_key="a", content=event["content"])
                                    revision += 1
                        evidence = core.commit_evidence(aid, evaluations=[{
                            **evaluation, "topic_id": topic["id"], "skill_id": cid,
                            "rationale": f"{reference['locator']}: {review['feedback']}",
                        } for evaluation in review["evaluations"]])["data"]["evidence_created"]
                        levels = [e["demonstrated_level"] for e in evidence]
                        if levels != reference["levels"]:
                            issues.append("core assistance/partial-progress classification mismatch")
                            critical = "independent_mastery" in levels and levels != reference["levels"]
                        if {e["subpart_key"] for e in evidence} != {e["subpart_key"] for e in reference["evaluations"]}:
                            issues.append("unsubmitted subpart evaluated")
                    except Exception as exc:
                        issues.append(f"core policy error: {type(exc).__name__}: {exc}")
                results.append({"id": cid, "category": case["category"], "passed": not issues,
                                "critical_failure": critical, "issues": issues,
                                "core_levels": levels, "reference": reference["locator"]})
        finally:
            core.close()
    return {"scope": "Captured judgment comparison and deterministic core-policy evaluation; no model invoked. Feedback quality requires separate review.",
            "artifact_sha256": {**{name: hashlib.sha256((fixtures / name).read_bytes()).hexdigest()
                                    for name in ("cases.json", "checked-references.json", "graph.png", "graph-unknown.png")},
                                "normalized_reviews": reviews_hash},
            "cases": len(results), "passed": sum(r["passed"] for r in results),
            "failed": sum(not r["passed"] for r in results),
            "critical_failures": sum(r["critical_failure"] for r in results), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.reviews.resolve() or args.output.resolve().is_relative_to(DEFAULT_FIXTURES.resolve()):
        parser.error("output must not overwrite captured reviews or fixture files")
    report = evaluate(json.loads(args.reviews.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{report['passed']}/{report['cases']} captured judgments/policy cases passed; {report['failed']} failed")
    raise SystemExit(bool(report["failed"]))


if __name__ == "__main__":
    main()
