"""Tests for course ingestion, format extractors, quality flags, and retrieval with provenance.

Covers failure scenarios: F01, F02, F03, F04, F23, F26.
"""

from pathlib import Path
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.ingestion.extractors import PDFExtractor


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_f01_scanned_pdf_page_flagged_with_limitation(temp_workspace):
    """F01: Scanned PDF page without text layer produces an actionable limitation, not silent success."""
    # Create a synthetic PDF with an image or zero extractable text using pypdf
    from pypdf import PdfWriter
    writer = PdfWriter()
    # Add a blank page
    writer.add_blank_page(width=612, height=792)

    pdf_path = temp_workspace / "scanned_handout.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)

    core = LumenCore(temp_workspace)
    try:
        core.create_course("Prob & Stats", course_id="prob-f01")
        res = core.ingest_source("prob-f01", pdf_path, logical_name="scanned_handout", role="lecture")["data"]

        # Extraction status must explicitly reflect empty/uncertain text
        assert res["extraction_status"] in ("empty", "uncertain")
        assert len(res["limitations"]) > 0
        assert "no extractable text" in res["limitations"][0].lower() or "scanned" in res["limitations"][0].lower()

        # Check course brief reflects the limitation
        brief = core.course_brief("prob-f01")
        assert len(brief["extraction_limitations"]) > 0
    finally:
        core.close()


def test_f02_f26_retrieval_preserves_full_mathematical_assumptions(temp_workspace):
    """F02 & F26: Retrieval preserves complete required assumptions, dependencies, and formulas without truncation."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f02")

        # Ingest theorem with critical assumptions
        text_content = """
### Theorem: Bayes Theorem
Content: P(A|B) = P(B|A) * P(A) / P(B)
Assumptions: P(B) > 0; Events A and B belong to the same probability space
Symbols: P(A|B) = conditional probability of A given B; P(B) = marginal probability of B
Exceptions: Undefined when P(B) = 0
Dependencies: conditional-probability-def
"""
        f = temp_workspace / "bayes.txt"
        f.write_text(text_content, encoding="utf-8")
        ingest_res = core.ingest_source("prob-f02", f, logical_name="bayes_doc")["data"]

        unit_id = ingest_res["units"][0]["id"]

        # Search returns compact hit first
        search_hits = core.search("prob-f02", "Bayes Theorem")
        assert search_hits["results_count"] >= 1
        hit = search_hits["results"][0]
        assert hit["assumptions_count"] == 2
        assert hit["has_formulas_or_symbols"] is True

        # Read units on demand returns full assumptions and symbol definitions
        read_res = core.read_units("prob-f02", [unit_id])
        unit = read_res["units"][0]
        assert "P(B) > 0" in unit["assumptions"]
        assert "Events A and B belong to the same probability space" in unit["assumptions"]
        assert "P(A|B)" in unit["symbol_definitions"]
        assert "Undefined when P(B) = 0" in unit["exceptions"]
        assert unit["provenance"][0]["original_filename"] == "bayes.txt"
    finally:
        core.close()


def test_f03_multilingual_topic_alias_retrieval(temp_workspace):
    """F03: Hebrew and English aliases retrieve the intended topic and associated units."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f03")

        # Create topic with English name and Hebrew / notation aliases
        t = core.create_topic("prob-f03", name="Conditional Probability", slug="cond-prob")
        topic_id = t["id"]
        core.add_topic_alias("prob-f03", topic_id, alias="הסתברות מותנית", language="he")
        core.add_topic_alias("prob-f03", topic_id, alias="P(A|B)", language="notation")

        # Ingest notes linked to this topic
        doc = """
### Definition: Conditional Probability
Content: The probability of event A given that event B has occurred is P(A|B) = P(A ∩ B) / P(B).
Assumptions: P(B) > 0
"""
        f = temp_workspace / "cond_prob.txt"
        f.write_text(doc, encoding="utf-8")
        core.ingest_source("prob-f03", f, logical_name="cond_prob", topic_slugs=["cond-prob"])

        # Search in Hebrew matches via topic alias
        he_results = core.search("prob-f03", "הסתברות מותנית")
        assert he_results["results_count"] >= 1
        assert he_results["results"][0]["title"] == "Conditional Probability"

        # Search in English also matches
        en_results = core.search("prob-f03", "Conditional Probability")
        assert en_results["results_count"] >= 1
        assert en_results["results"][0]["title"] == "Conditional Probability"
    finally:
        core.close()


def test_f04_source_versioning_and_provenance(temp_workspace):
    """F04: Multiple source versions preserve historical provenance and locators."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Analysis", course_id="analysis-1")

        f = temp_workspace / "lecture1.txt"
        f.write_text("### Definition: Limit\nVersion 1 text on limits.", encoding="utf-8")
        res1 = core.ingest_source("analysis-1", f, logical_name="lecture1")["data"]
        v1_id = res1["source_version_id"]

        f.write_text("### Definition: Limit\nVersion 2 updated epsilon-delta definition.", encoding="utf-8")
        res2 = core.ingest_source("analysis-1", f, logical_name="lecture1")["data"]
        v2_id = res2["source_version_id"]

        assert v1_id != v2_id

        # Verify old provenance remains accessible
        region1 = core.read_source_region(v1_id)
        region2 = core.read_source_region(v2_id)
        assert region1["version_num"] == 1
        assert region2["version_num"] == 2
        assert region1["hash_verified"] is True
        assert region2["hash_verified"] is True
    finally:
        core.close()


def test_f23_course_brief_exposes_missing_syllabus_content(temp_workspace):
    """F23: Syllabus topic with no uploaded content is reported as missing, not inferred as covered."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Probability", course_id="prob-f23")

        # Create 3 topics from syllabus
        core.create_topic("prob-f23", name="Combinatorics", slug="combinatorics")
        core.create_topic("prob-f23", name="Poisson Distribution", slug="poisson")
        core.create_topic("prob-f23", name="Markov Chains", slug="markov-chains")

        # Ingest material only for Combinatorics
        f = temp_workspace / "comb.txt"
        f.write_text("### Definition: Permutations\nn! arrangements of n distinct elements.", encoding="utf-8")
        core.ingest_source("prob-f23", f, logical_name="comb_notes", topic_slugs=["combinatorics"])

        # Check course brief
        brief = core.course_brief("prob-f23")
        missing = brief["coverage"]["topics_missing_materials"]

        # Poisson Distribution and Markov Chains must be explicitly reported as missing
        assert "Poisson Distribution" in missing
        assert "Markov Chains" in missing
        assert "Combinatorics" not in missing
    finally:
        core.close()
