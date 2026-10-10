"""Efficiency and recurring context payload measurements."""

import json
from pathlib import Path
import tempfile
import pytest

from course_tutor.api import LumenCore


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_recurring_context_payload_measurement(temp_workspace):
    """Measure payload size of course_brief and targeted retrieval vs naive full-source injection."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-eff")
        mat_dir = Path(__file__).parent.parent / "examples" / "synthetic_probability" / "materials"

        # Ingest both materials
        core.ingest_source("prob-eff", mat_dir / "lecture_bayes.txt", logical_name="bayes")
        core.ingest_source("prob-eff", mat_dir / "slides_random_variables.txt", logical_name="slides")

        # Baseline: naive approach injects full source files into every prompt
        raw_bayes = (mat_dir / "lecture_bayes.txt").read_text()
        raw_slides = (mat_dir / "slides_random_variables.txt").read_text()
        full_sources_bytes = len(raw_bayes.encode("utf-8")) + len(raw_slides.encode("utf-8"))

        # Lumen startup: only loads course brief
        brief = core.course_brief("prob-eff")
        brief_json = json.dumps(brief, ensure_ascii=False)
        brief_bytes = len(brief_json.encode("utf-8"))

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

        print(f"\n--- Measured Payload Sizes ---")
        print(f"Naive All-Source Injection: {full_sources_bytes} bytes (~{full_sources_bytes // 4} tokens)")
        print(f"Lumen Session Startup (Brief): {brief_bytes} bytes (~{brief_bytes // 4} tokens)")
        print(f"Lumen Search Results: {search_bytes} bytes (~{search_bytes // 4} tokens)")
        print(f"Lumen Targeted Unit Read: {unit_bytes} bytes (~{unit_bytes // 4} tokens)")
    finally:
        core.close()
