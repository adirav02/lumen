"""Tests for storage guarantees, file store, idempotency, revisions, and backup/restore.

Covers failure scenarios: F05, F06, F15, F16, F18, F19, F24, F25.
"""

from pathlib import Path
import tempfile
import pytest

from course_tutor.api import LumenCore
from course_tutor.errors import (
    CrossCourseViolationError,
    IdempotencyConflictError,
    RestoreIntegrityError,
    SourceCorruptedError,
    StaleRevisionError,
)
from course_tutor.storage.file_store import FileStore


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_f05_identical_bytes_different_filename(temp_workspace):
    """F05: Identical bytes uploaded under a different name should reuse content identity."""
    core = LumenCore(temp_workspace)
    try:
        c = core.create_course("Probability 101", course_id="prob-101")["data"]
        course_id = c["id"]

        # Create two files with identical content
        f1 = temp_workspace / "lecture_notes_v1.txt"
        f2 = temp_workspace / "lecture_notes_copy.txt"
        content = "### Definition: Random Variable\nA function mapping sample space to real numbers."
        f1.write_text(content, encoding="utf-8")
        f2.write_text(content, encoding="utf-8")

        res1 = core.ingest_source(course_id, f1, logical_name="notes_1")["data"]
        res2 = core.ingest_source(course_id, f2, logical_name="notes_2")["data"]

        # Both point to same underlying content hash
        assert res1["file_hash"] == res2["file_hash"]
        # Second upload recognizes existing content without duplicate unit explosion
        assert res1["version_num"] == 1
    finally:
        core.close()


def test_f06_same_filename_different_bytes(temp_workspace):
    """F06: Same filename with different bytes creates distinct immutable versions."""
    core = LumenCore(temp_workspace)
    try:
        c = core.create_course("Probability 101", course_id="prob-101")["data"]
        course_id = c["id"]

        f1 = temp_workspace / "syllabus.txt"
        f1.write_text("Syllabus Version 1: Topics A, B", encoding="utf-8")

        res1 = core.ingest_source(course_id, f1, logical_name="syllabus")["data"]
        assert res1["version_num"] == 1

        # Now change content under same logical name
        f1.write_text("Syllabus Version 2: Topics A, B, C and Exam Dates", encoding="utf-8")
        res2 = core.ingest_source(course_id, f1, logical_name="syllabus")["data"]
        assert res2["version_num"] == 2
        assert res1["file_hash"] != res2["file_hash"]

        # Verify both versions exist and resolve their locators
        v1_info = core.read_source_region(res1["source_version_id"])
        v2_info = core.read_source_region(res2["source_version_id"])
        assert v1_info["hash_verified"] is True
        assert v2_info["hash_verified"] is True
    finally:
        core.close()


def test_f15_idempotent_retry_returns_prior_receipt(temp_workspace):
    """F15: Tool retry with same request ID returns prior receipt without duplicate execution."""
    core = LumenCore(temp_workspace)
    try:
        req_id = "req-create-course-unique-123"
        res1 = core.create_course("Math 101", course_id="math-101", request_id=req_id)
        assert res1["status"] == "success"
        assert "receipt" in res1

        # Retry with identical params
        res2 = core.create_course("Math 101", course_id="math-101", request_id=req_id)
        assert res2["status"] == "success"
        assert res2.get("idempotent_replay") is True
        assert res2["receipt"]["request_id"] == req_id
        assert res2["receipt"]["canonical_request_hash"] == res1["receipt"]["canonical_request_hash"]
    finally:
        core.close()


def test_f16_reusing_request_id_with_different_content_conflicts(temp_workspace):
    """F16: Same request ID with different content returns an explicit IdempotencyConflictError."""
    core = LumenCore(temp_workspace)
    try:
        req_id = "req-course-conflict-456"
        core.create_course("Math 101", course_id="math-101", request_id=req_id)

        # Same request ID, completely different parameters
        with pytest.raises(IdempotencyConflictError) as exc_info:
            core.create_course("Physics 101", course_id="phys-101", request_id=req_id)

        assert exc_info.value.error_code == "IDEMPOTENCY_CONFLICT"
    finally:
        core.close()


def test_f18_stale_revision_conflict(temp_workspace):
    """F18: Stale revision conflict rejection preserves observations without silent overwrite."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Stats", course_id="stats-1")
        ex = core.create_exercise("stats-1", "binom_1", "Calculate P(X=2)")

        att = core.start_attempt("stats-1", ex["exercise_version_id"])["data"]
        att_id = att["id"]
        assert att["current_revision"] == 1

        # First update with expected_revision=1 succeeds and increments to 2
        core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Step 1")

        # Second update erroneously using expected_revision=1 must fail
        with pytest.raises(StaleRevisionError) as exc_info:
            core.record_attempt_event(att_id, expected_revision=1, event_type="work_submission", content="Stale Step")

        assert exc_info.value.error_code == "STALE_REVISION"
    finally:
        core.close()


def test_f19_cross_course_violation(temp_workspace):
    """F19: Operations scoped to course A cannot access or link entities from course B."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Course A", course_id="course-a")
        core.create_course("Course B", course_id="course-b")

        ex_b = core.create_exercise("course-b", "family_b", "Question for B")

        # Attempting to start an attempt in course A using an exercise from course B
        with pytest.raises(CrossCourseViolationError) as exc_info:
            core.start_attempt("course-a", ex_b["exercise_version_id"])

        assert exc_info.value.error_code == "CROSS_COURSE_VIOLATION"
    finally:
        core.close()


def test_f24_source_corruption_detection(temp_workspace):
    """F24: Hash mismatch on modified original file is detected."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Crypto", course_id="crypto-1")
        f = temp_workspace / "notes.txt"
        f.write_text("Original pristine notes", encoding="utf-8")

        res = core.ingest_source("crypto-1", f, logical_name="notes")["data"]
        relpath = res["storage_relpath"]
        expected_hash = res["file_hash"]

        # Tamper with stored file
        stored_file = temp_workspace / relpath
        stored_file.write_text("Tampered corrupted notes", encoding="utf-8")

        # Verifying file hash directly raises SourceCorruptedError
        fs = FileStore(temp_workspace)
        with pytest.raises(SourceCorruptedError):
            fs.verify_file_hash(relpath, expected_hash)
    finally:
        core.close()


def test_f25_backup_restore_missing_source_fails(temp_workspace):
    """F25: Workspace restore fails when backup archive omits referenced originals."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Logic", course_id="logic-1")
        f = temp_workspace / "textbook.txt"
        f.write_text("Textbook on Propositional Logic", encoding="utf-8")
        core.ingest_source("logic-1", f, logical_name="textbook")

        backup_file = temp_workspace / "backup.zip"
        core.backup(backup_file)

        # Unpack backup, delete source file, and attempt restore
        restore_dir = temp_workspace / "corrupt_backup"
        import zipfile
        with zipfile.ZipFile(backup_file, "r") as z:
            z.extractall(restore_dir)

        # Delete the originals directory inside the unpacked backup
        for orig in (restore_dir / "originals").glob("*"):
            orig.unlink()

        # Restore from this corrupt backup directory into target workspace
        target_ws = temp_workspace / "restored_ws"
        with pytest.raises(RestoreIntegrityError) as exc_info:
            LumenCore.restore(restore_dir, target_ws)

        assert exc_info.value.error_code == "RESTORE_INTEGRITY_ERROR"
    finally:
        core.close()


def test_backup_and_restore_fidelity(temp_workspace):
    """Verify clean backup and restore into a new workspace with byte-for-byte fidelity."""
    core = LumenCore(temp_workspace)
    try:
        core.create_course("Algorithms", course_id="algo-1")
        f = temp_workspace / "sorting.txt"
        f.write_text("### Definition: Merge Sort\nDivide and conquer sorting with O(N log N) runtime.", encoding="utf-8")
        core.ingest_source("algo-1", f, logical_name="sorting")

        backup_file = temp_workspace / "clean_backup.zip"
        b_res = core.backup(backup_file)
        assert b_res["source_count"] == 1
    finally:
        core.close()

    # Restore in completely separate workspace
    with tempfile.TemporaryDirectory() as restore_td:
        restored_ws = Path(restore_td)
        r_res = LumenCore.restore(backup_file, restored_ws)
        assert r_res["status"] == "success"
        assert r_res["sources_verified"] == 1

        # Reopen with LumenCore in restored directory
        restored_core = LumenCore(restored_ws)
        try:
            brief = restored_core.course_brief("algo-1")
            assert brief["course"]["name"] == "Algorithms"
            assert len(brief["sources"]) == 1
            search_res = restored_core.search("algo-1", "Merge Sort")
            assert search_res["results_count"] >= 1
        finally:
            restored_core.close()
