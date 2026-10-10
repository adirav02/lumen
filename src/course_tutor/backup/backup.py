"""Workspace snapshot backup with consistent database snapshot and source asset integrity."""

import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Dict, Optional, Union
import zipfile

from ..errors import SourceNotFoundError, WorkspaceError
from ..models import utc_now_iso
from ..storage.db import get_connection, snapshot_backup
from ..storage.file_store import FileStore, compute_sha256


def backup_workspace(
    workspace_root: Union[str, Path],
    output_path: Union[str, Path],
    con: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Create a self-contained, consistent backup archive of the workspace.

    Includes SQLite database snapshot, all referenced immutable files,
    and an integrity manifest with SHA-256 checksums.
    """
    ws = Path(workspace_root).resolve()
    db_file = ws / "lumen.db"
    if not db_file.exists():
        raise WorkspaceError(str(ws), "No lumen.db database found in workspace.")

    out_dest = Path(output_path).resolve()
    out_dest.parent.mkdir(parents=True, exist_ok=True)

    file_store = FileStore(ws)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        temp_db = temp_path / "lumen.db"

        # 1. Consistent online SQLite backup from active or new connection
        close_src = False
        if con is not None:
            source_con = con
        else:
            source_con = get_connection(db_file)
            close_src = True

        try:
            snapshot_backup(source_con, temp_db)
            db_hash = compute_sha256(temp_db)

            # 2. Query all referenced source versions from the snapshot
            snap_con = get_connection(temp_db)
            try:
                rows = snap_con.execute(
                    "SELECT id, file_hash, original_filename, byte_size, storage_relpath FROM source_versions"
                ).fetchall()
            finally:
                snap_con.close()
        finally:
            if close_src:
                source_con.close()

        # 3. Copy each referenced original file into backup structure
        sources_manifest = []
        for r in rows:
            relpath = r["storage_relpath"]
            expected_hash = r["file_hash"]
            abs_source = file_store.get_absolute_path(relpath)

            if not abs_source.is_file():
                raise SourceNotFoundError(
                    r["id"],
                    details={"storage_relpath": relpath, "message": "Source file referenced by database is missing on disk."}
                )

            actual_hash = compute_sha256(abs_source)
            if actual_hash != expected_hash:
                raise WorkspaceError(str(abs_source), f"Hash mismatch during backup for '{relpath}'.")

            temp_target = temp_path / relpath
            temp_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_source, temp_target)

            sources_manifest.append({
                "id": r["id"],
                "file_hash": expected_hash,
                "original_filename": r["original_filename"],
                "byte_size": r["byte_size"],
                "storage_relpath": relpath,
            })

        # 4. Generate manifest.json
        manifest = {
            "schema_version": 1,
            "contract_version": "1.0.0",
            "created_at": utc_now_iso(),
            "database": {
                "filename": "lumen.db",
                "sha256": db_hash,
                "byte_size": temp_db.stat().st_size,
            },
            "sources": sources_manifest,
        }

        with open(temp_path / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # 5. Package into zip archive or directory
        if str(out_dest).endswith(".zip"):
            with zipfile.ZipFile(out_dest, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path in temp_path.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(temp_path)
                        zipf.write(file_path, arcname)
        else:
            if out_dest.exists():
                shutil.rmtree(out_dest)
            shutil.copytree(temp_path, out_dest)

    return {
        "backup_path": str(out_dest),
        "source_count": len(sources_manifest),
        "manifest": manifest,
    }
