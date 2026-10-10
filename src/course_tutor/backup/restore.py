"""Workspace restore with integrity verification and foreign key checks."""

import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Dict, Union
import uuid
import zipfile

from ..errors import RestoreIntegrityError
from ..storage.db import get_connection
from ..storage.file_store import compute_sha256


def _check_db_not_locked(db_path: Path) -> None:
    """Ensure destination database is not actively locked by another process."""
    if not db_path.is_file():
        return
    try:
        con = sqlite3.connect(str(db_path), timeout=0.2)
        try:
            con.execute("BEGIN IMMEDIATE;")
            con.rollback()
        finally:
            con.close()
    except sqlite3.OperationalError as exc:
        raise RestoreIntegrityError(
            f"Target workspace database '{db_path}' is actively locked or in use: {exc}"
        ) from exc


def restore_workspace(
    backup_path: Union[str, Path],
    target_workspace: Union[str, Path],
    force: bool = False,
) -> Dict[str, Any]:
    """Restore a workspace snapshot with strict validation of database and source files.

    Verifies manifest presence, database hash, all referenced original source files,
    database foreign keys, SQLite integrity check, and audits database source_versions.
    Stages completely in a sandbox before activating target workspace.
    Refuses to overwrite an existing populated workspace unless force=True.
    """
    backup_src = Path(backup_path).resolve()
    target_ws = Path(target_workspace).resolve()

    if not backup_src.exists():
        raise RestoreIntegrityError(f"Backup source '{backup_src}' does not exist.")

    # Guard populated workspaces against accidental destruction
    if target_ws.exists() and any(target_ws.iterdir()) and not force:
        raise RestoreIntegrityError(
            f"Target workspace '{target_ws}' is already populated. Refusing to overwrite without force=True."
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # 1. Extract if zip, or copy if directory
        if backup_src.is_file() and zipfile.is_zipfile(backup_src):
            with zipfile.ZipFile(backup_src, "r") as zipf:
                zipf.extractall(temp_path)
        elif backup_src.is_dir():
            shutil.copytree(backup_src, temp_path, dirs_exist_ok=True)
        else:
            raise RestoreIntegrityError(f"Backup '{backup_src}' is neither a zip file nor a valid directory.")

        manifest_file = temp_path / "manifest.json"
        if not manifest_file.is_file():
            raise RestoreIntegrityError("Missing manifest.json in backup archive.")

        with open(manifest_file, "r", encoding="utf-8") as f:
            try:
                manifest = json.load(f)
            except json.JSONDecodeError as e:
                raise RestoreIntegrityError(f"Malformed manifest.json: {e}")

        # 2. Verify database file integrity
        db_info = manifest.get("database", {})
        db_filename = db_info.get("filename", "lumen.db")
        expected_db_hash = db_info.get("sha256")
        staged_db = temp_path / db_filename

        if not staged_db.is_file():
            raise RestoreIntegrityError(f"Backup manifest references database '{db_filename}', but file is missing.")

        actual_db_hash = compute_sha256(staged_db)
        if expected_db_hash and actual_db_hash != expected_db_hash:
            raise RestoreIntegrityError(
                f"Database integrity violation: expected hash {expected_db_hash}, got {actual_db_hash}."
            )

        # 3. Verify all manifest-referenced source files (F24 & F25)
        sources_list = manifest.get("sources", [])
        verified_sources_count = 0
        for src_meta in sources_list:
            relpath = src_meta.get("storage_relpath")
            expected_hash = src_meta.get("file_hash")
            staged_source = temp_path / relpath

            if not staged_source.is_file():
                # F25: Backup contains data but omits source files
                raise RestoreIntegrityError(
                    f"Backup integrity error: referenced original source file '{relpath}' is missing.",
                    details={"missing_file": relpath, "source_id": src_meta.get("id")},
                )

            actual_hash = compute_sha256(staged_source)
            if actual_hash != expected_hash:
                # F24: Hash mismatch
                raise RestoreIntegrityError(
                    f"Backup integrity error: hash mismatch for original source file '{relpath}'. Expected {expected_hash}, got {actual_hash}.",
                    details={"file_path": relpath, "expected_hash": expected_hash, "actual_hash": actual_hash},
                )
            verified_sources_count += 1

        # 4. Check database internal integrity, foreign keys, and audit source_versions
        db_con = get_connection(staged_db)
        try:
            # PRAGMA integrity_check
            integ = db_con.execute("PRAGMA integrity_check;").fetchall()
            if not integ or integ[0][0] != "ok":
                reasons = [r[0] for r in integ]
                raise RestoreIntegrityError(f"SQLite integrity check failed: {', '.join(reasons)}")

            # PRAGMA foreign_key_check
            fk_errors = db_con.execute("PRAGMA foreign_key_check;").fetchall()
            if fk_errors:
                raise RestoreIntegrityError(
                    f"Foreign key constraint violation in restored database: {len(fk_errors)} violations found."
                )

            # Audit actual database source_versions against restored disk assets
            db_sources = db_con.execute(
                "SELECT id, file_hash, storage_relpath, original_filename FROM source_versions"
            ).fetchall()
            for src_row in db_sources:
                relpath = src_row["storage_relpath"]
                expected_hash = src_row["file_hash"]
                staged_file = temp_path / relpath
                if not staged_file.is_file():
                    raise RestoreIntegrityError(
                        f"Database references source file '{relpath}' (ID: {src_row['id']}) which is missing from backup assets.",
                        details={"missing_file": relpath, "source_version_id": src_row["id"]},
                    )
                actual_hash = compute_sha256(staged_file)
                if actual_hash != expected_hash:
                    raise RestoreIntegrityError(
                        f"Database reference integrity error: hash mismatch for '{relpath}'. Expected {expected_hash}, got {actual_hash}.",
                        details={"file_path": relpath, "expected_hash": expected_hash, "actual_hash": actual_hash},
                    )

            # Query restored courses
            courses = [r["id"] for r in db_con.execute("SELECT id FROM courses").fetchall()]
        finally:
            db_con.close()

        # 5. Prepare complete candidate directory in temporary sandbox
        candidate_dir = temp_path / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_db, candidate_dir / "lumen.db")

        candidate_originals = candidate_dir / "originals"
        candidate_originals.mkdir(parents=True, exist_ok=True)
        staged_originals = temp_path / "originals"
        if staged_originals.exists():
            for f in staged_originals.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(staged_originals)
                    target_file = candidate_originals / rel
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target_file)

        shutil.copy2(manifest_file, candidate_dir / "backup_manifest.json")

        # 6. Check active database locks and perform atomic recoverable activation
        target_ws.parent.mkdir(parents=True, exist_ok=True)
        existing_db = target_ws / "lumen.db"
        if existing_db.exists():
            _check_db_not_locked(existing_db)

        rollback_dir = None
        target_populated = target_ws.exists() and any(target_ws.iterdir())
        if target_populated:
            rollback_dir = target_ws.parent / f".rollback_{target_ws.name}_{uuid.uuid4().hex[:8]}"
            shutil.move(str(target_ws), str(rollback_dir))
        elif target_ws.exists():
            target_ws.rmdir()

        try:
            shutil.move(str(candidate_dir), str(target_ws))
        except Exception as exc:
            if target_ws.exists():
                shutil.rmtree(target_ws, ignore_errors=True)
            if rollback_dir and rollback_dir.exists():
                shutil.move(str(rollback_dir), str(target_ws))
            raise RestoreIntegrityError(f"Restore activation failed: {exc}") from exc
        else:
            if rollback_dir and rollback_dir.exists():
                shutil.rmtree(rollback_dir, ignore_errors=True)

    return {
        "status": "success",
        "restored_workspace": str(target_ws),
        "courses": courses,
        "sources_verified": verified_sources_count,
    }
