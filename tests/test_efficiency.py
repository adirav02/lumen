"""Efficiency and recurring context payload measurements.

Benchmarks multi-turn tutoring workflows (brief, search, expansion, reading, attempt, receipt)
against naive full-course material injection baselines using declared token estimation heuristics.
"""

import json
from pathlib import Path
import tempfile
from typing import Any, Dict
import pytest

from course_tutor.api import LumenCore


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def estimate_tokens_chars4(text: str) -> int:
    """Declared token estimator: ~4 UTF-8 characters per token heuristic.
    
    This matches typical BPE tokenization (cl100k_base / Llama / Claude) for technical English.
    """
    return max(1, len(text) // 4)


def test_recurring_context_payload_measurement(temp_workspace):
    """Measure payload size of course_brief and targeted retrieval vs naive full-source injection."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-eff")
        mat_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "synthetic_probability" / "materials"

        # Ingest both materials
        core.ingest_source("prob-eff", mat_dir / "lecture_bayes.txt", logical_name="bayes")
        core.ingest_source("prob-eff", mat_dir / "slides_random_variables.txt", logical_name="slides")

        # Baseline: naive approach injects full source files into every prompt
        raw_bayes = (mat_dir / "lecture_bayes.txt").read_text(encoding="utf-8")
        raw_slides = (mat_dir / "slides_random_variables.txt").read_text(encoding="utf-8")
        full_sources_text = raw_bayes + "\n" + raw_slides
        full_sources_bytes = len(full_sources_text.encode("utf-8"))
        full_sources_est_tokens = estimate_tokens_chars4(full_sources_text)

        # Lumen startup: only loads course brief
        brief = core.course_brief("prob-eff")
        brief_json = json.dumps(brief, ensure_ascii=False)
        brief_bytes = len(brief_json.encode("utf-8"))
        brief_est_tokens = estimate_tokens_chars4(brief_json)

        # Lumen retrieval: compact search hits
        search_res = core.search("prob-eff", "Bayes Rule")
        search_json = json.dumps(search_res, ensure_ascii=False)
        search_bytes = len(search_json.encode("utf-8"))

        # Targeted unit reading
        unit_id = search_res["results"][0]["unit_id"]
        unit_res = core.read_units("prob-eff", [unit_id], expand_dependencies=False)
        unit_json = json.dumps(unit_res, ensure_ascii=False)
        unit_bytes = len(unit_json.encode("utf-8"))

        # Assertions and measurements
        assert brief_bytes > 0
        assert search_bytes > 0
        assert unit_bytes > 0

        # Targeted reading is significantly smaller than loading all raw materials
        assert unit_bytes < full_sources_bytes

        print(f"\n--- Measured Single-Operation Payload Sizes ---")
        print(f"Naive All-Source Injection: {full_sources_bytes} bytes (~{full_sources_est_tokens} tokens)")
        print(f"Lumen Session Startup (Brief): {brief_bytes} bytes (~{brief_est_tokens} tokens)")
        print(f"Lumen Search Results: {search_bytes} bytes (~{estimate_tokens_chars4(search_json)} tokens)")
        print(f"Lumen Targeted Unit Read: {unit_bytes} bytes (~{estimate_tokens_chars4(unit_json)} tokens)")
    finally:
        core.close()


def test_complete_multiturn_workflow_efficiency_benchmark(temp_workspace):
    """Benchmark a complete multi-turn interaction cycle against a naive full-materials baseline.

    Simulated Multi-Turn Interaction:
      Turn 1: Session Open -> Read brief
      Turn 2: Question Prompt -> Search for relevant concepts
      Turn 3: Pre-reading -> Expand dependencies and retrieve exact unit definitions
      Turn 4: Exercise Attempt -> Start attempt with receipt
      Turn 5: Submission -> Record learner work event
      Turn 6: Evaluation & Mastery -> Commit evidence and recompute topic state with receipt

    Baseline:
      The naive LLM agent pattern re-injects the complete set of raw source materials into the prompt
      on EVERY turn of the conversation.
    """
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-bench")
        mat_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "synthetic_probability" / "materials"

        # Ingest course materials
        core.ingest_source("prob-bench", mat_dir / "lecture_bayes.txt", logical_name="bayes")
        core.ingest_source("prob-bench", mat_dir / "slides_random_variables.txt", logical_name="slides")

        raw_bayes = (mat_dir / "lecture_bayes.txt").read_text(encoding="utf-8")
        raw_slides = (mat_dir / "slides_random_variables.txt").read_text(encoding="utf-8")
        full_materials_text = raw_bayes + "\n" + raw_slides
        full_materials_bytes_per_turn = len(full_materials_text.encode("utf-8"))

        NUM_TURNS = 6
        naive_total_bytes = full_materials_bytes_per_turn * NUM_TURNS
        naive_total_est_tokens = estimate_tokens_chars4(full_materials_text) * NUM_TURNS

        lumen_turn_payloads: Dict[str, int] = {}

        # Turn 1: Startup brief
        brief = core.course_brief("prob-bench")
        t1_json = json.dumps(brief, ensure_ascii=False)
        lumen_turn_payloads["Turn 1 (Brief)"] = len(t1_json.encode("utf-8"))

        # Turn 2: Concept Search
        search_hits = core.search("prob-bench", "Bayes Rule")
        t2_json = json.dumps(search_hits, ensure_ascii=False)
        lumen_turn_payloads["Turn 2 (Search)"] = len(t2_json.encode("utf-8"))

        # Turn 3: Dependency expansion and targeted reading
        unit_id = search_hits["results"][0]["unit_id"]
        read_units_res = core.read_units("prob-bench", [unit_id], expand_dependencies=True)
        t3_json = json.dumps(read_units_res, ensure_ascii=False)
        lumen_turn_payloads["Turn 3 (Expansion & Read)"] = len(t3_json.encode("utf-8"))

        # Create topic and validated exercise for attempt
        t = core.create_topic("prob-bench", name="Bayes Theorem", slug="bayes")
        ex = core.create_exercise("prob-bench", "bayes_test", "Calculate P(A|B)")
        core.validate_exercise_version(
            ex["exercise_version_id"],
            reference_solution="P(A|B) = 0.4",
            rubric={"criteria": "correct posterior probability", "max_points": 10},
            checks=["mathematical_consistency_verified"],
            expected_revision=1,
        )

        # Turn 4: Start attempt with idempotency receipt
        start_res = core.start_attempt("prob-bench", ex["exercise_version_id"], request_id="req-turn-4")
        t4_json = json.dumps(start_res, ensure_ascii=False)
        lumen_turn_payloads["Turn 4 (Start Attempt)"] = len(t4_json.encode("utf-8"))
        att_id = start_res["data"]["id"]

        # Turn 5: Record learner submission event
        ev_res = core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="P(A|B) = 0.4")
        t5_json = json.dumps(ev_res, ensure_ascii=False)
        lumen_turn_payloads["Turn 5 (Submission Event)"] = len(t5_json.encode("utf-8"))

        # Turn 6: Commit evaluation with idempotency receipt
        eval_res = core.commit_evidence(
            att_id,
            evaluations=[{"topic_id": t["id"], "skill_id": "bayes_calc", "correct": True}],
            request_id="req-turn-6",
        )
        t6_json = json.dumps(eval_res, ensure_ascii=False)
        lumen_turn_payloads["Turn 6 (Evidence & Receipt)"] = len(t6_json.encode("utf-8"))

        lumen_total_bytes = sum(lumen_turn_payloads.values())
        lumen_total_est_tokens = sum(estimate_tokens_chars4(v * "x") for v in lumen_turn_payloads.values())

        payload_reduction_ratio = (naive_total_bytes - lumen_total_bytes) / naive_total_bytes

        print(f"\n=======================================================")
        print(f" SYNTHETIC MULTI-TURN TASK BENCHMARK (6 Turns)")
        print(f" Token Estimator: ~4 characters per token (heuristic)")
        print(f" Note: Heuristic payload reduction on synthetic task;")
        print(f"       does not measure provider-billed total monetary cost.")
        print(f"=======================================================")
        print(f" Naive Baseline (Full Materials Re-injected Every Turn):")
        print(f"   Total Bytes:          {naive_total_bytes:,} bytes")
        print(f"   Estimated Tokens:     {naive_total_est_tokens:,} tokens")
        print(f" Lumen Structured Operations:")
        for turn_name, byte_count in lumen_turn_payloads.items():
            print(f"   {turn_name:28s}: {byte_count:5,d} bytes (~{byte_count//4:4,d} tokens)")
        print(f"   ----------------------------------------------------")
        print(f"   Lumen Total Bytes:    {lumen_total_bytes:,} bytes")
        print(f"   Lumen Est Tokens:     {lumen_total_est_tokens:,} tokens")
        print(f"   Payload Reduction:    {payload_reduction_ratio * 100:.1f}%")
        print(f"=======================================================\n")

        # Assert substantial context payload reduction across synthetic multi-turn task (>50%)
        assert payload_reduction_ratio > 0.50, f"Expected >50% heuristic payload reduction, got {payload_reduction_ratio*100:.1f}%"
    finally:
        core.close()
