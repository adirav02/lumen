"""Immutable content-addressed file store with staging, hashing, and verification."""

import hashlib
import mimetypes
from pathlib import Path
import re
import shutil
from typing import NamedTuple, Optional, Union
import uuid

from ..errors import SourceCorruptedError, WorkspaceError


class StoredFile(NamedTuple):
    file_hash: str
    byte_size: int
    mime_type: str
    storage_relpath: str
    original_filename: str


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe cross-platform filesystem storage."""
    base = Path(filename).name
    # Keep alphanumeric, dot, dash, underscore
    clean = re.sub(r"[^\w\.\-]", "_", base)
    return clean or "unnamed_source"


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class FileStore:
    """Manages immutable original files and derived assets within a workspace."""

    def __init__(self, workspace_root: Union[str, Path]):
        self.workspace_root = Path(workspace_root).resolve()
        self.originals_dir = self.workspace_root / "originals"
        self.staging_dir = self.workspace_root / "staging"

        try:
            self.originals_dir.mkdir(parents=True, exist_ok=True)
            self.staging_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise WorkspaceError(str(self.workspace_root), f"Cannot create storage directories: {e}")

    def get_absolute_path(self, storage_relpath: str) -> Path:
        """Resolve a relative storage path to an absolute path within workspace."""
        full_path = (self.workspace_root / storage_relpath).resolve()
        # Verify path stays within workspace
        try:
            full_path.relative_to(self.workspace_root)
        except ValueError:
            raise WorkspaceError(str(self.workspace_root), f"Access violation: path '{storage_relpath}' escapes workspace.")
        return full_path

    def verify_file_hash(self, storage_relpath: str, expected_hash: str) -> bool:
        """Verify that an existing stored file matches its expected SHA-256 hash."""
        abs_path = self.get_absolute_path(storage_relpath)
        if not abs_path.is_file():
            return False
        actual_hash = compute_sha256(abs_path)
        if actual_hash != expected_hash:
            raise SourceCorruptedError(str(storage_relpath), expected_hash, actual_hash)
        return True

    def store_file(self, src_path: Union[str, Path], original_filename: Optional[str] = None) -> StoredFile:
        """Copy a file through staging into immutable content-addressed storage.

        Preserves original bytes byte-for-byte with SHA-256 verification.
        """
        source = Path(src_path).resolve()
        if not source.is_file():
            raise WorkspaceError(str(source), f"Source file does not exist: {source}")

        orig_name = original_filename or source.name
        sanitized = sanitize_filename(orig_name)

        # Stage file first
        temp_staged = self.staging_dir / f"stage_{uuid.uuid4().hex}_{sanitized}"
        shutil.copy2(source, temp_staged)

        try:
            file_hash = compute_sha256(temp_staged)
            byte_size = temp_staged.stat().st_size
            mime_type, _ = mimetypes.guess_type(orig_name)
            mime_type = mime_type or "application/octet-stream"

            # Destination filename combines hash prefix to ensure immutable content identity
            dest_name = f"{file_hash[:16]}_{sanitized}"
            dest_relpath = f"originals/{dest_name}"
            dest_path = self.originals_dir / dest_name

            # If identical bytes already exist in store, reuse them (content identity)
            if not dest_path.exists():
                shutil.move(temp_staged, dest_path)
            else:
                if compute_sha256(dest_path) != file_hash:
                    raise SourceCorruptedError(dest_relpath, file_hash, compute_sha256(dest_path))
                # Remove temporary staged copy
                temp_staged.unlink(missing_ok=True)

            return StoredFile(
                file_hash=file_hash,
                byte_size=byte_size,
                mime_type=mime_type,
                storage_relpath=dest_relpath,
                original_filename=orig_name,
            )
        finally:
            if temp_staged.exists():
                temp_staged.unlink(missing_ok=True)

    def stage_file(
        self, src_path: Union[str, Path], original_filename: Optional[str] = None
    ) -> tuple[Path, str, int, str]:
        """Stage a source file into isolated quarantine copy and compute its sha256 hash."""
        source = Path(src_path).resolve()
        if not source.is_file():
            raise WorkspaceError(str(source), f"Source file does not exist: {source}")

        orig_name = original_filename or source.name
        sanitized = sanitize_filename(orig_name)
        stage_token = uuid.uuid4().hex
        staged_path = self.staging_dir / f"stage_{stage_token}_{sanitized}"
        shutil.copy2(source, staged_path)

        file_hash = compute_sha256(staged_path)
        byte_size = staged_path.stat().st_size
        mime_type, _ = mimetypes.guess_type(orig_name)
        mime_type = mime_type or "application/octet-stream"
        return staged_path, file_hash, byte_size, mime_type

    def publish_staged(
        self, staged_path: Path, file_hash: str, original_filename: str
    ) -> StoredFile:
        """Publish an already staged and verified file into immutable storage."""
        actual_hash = compute_sha256(staged_path)
        if actual_hash != file_hash:
            raise SourceCorruptedError(str(staged_path), file_hash, actual_hash)
        sanitized = sanitize_filename(original_filename)
        dest_name = f"{file_hash[:16]}_{sanitized}"
        dest_relpath = f"originals/{dest_name}"
        dest_path = self.originals_dir / dest_name

        byte_size = staged_path.stat().st_size
        mime_type, _ = mimetypes.guess_type(original_filename)
        mime_type = mime_type or "application/octet-stream"

        if not dest_path.exists():
            shutil.move(staged_path, dest_path)
        else:
            actual_hash = compute_sha256(dest_path)
            if actual_hash != file_hash:
                raise SourceCorruptedError(dest_relpath, file_hash, actual_hash)
            staged_path.unlink(missing_ok=True)

        return StoredFile(
            file_hash=file_hash,
            byte_size=byte_size,
            mime_type=mime_type,
            storage_relpath=dest_relpath,
            original_filename=original_filename,
        )

    def store_bytes(self, content: bytes, original_filename: str) -> StoredFile:
        """Store raw bytes into immutable store via staging."""
        sanitized = sanitize_filename(original_filename)
        temp_staged = self.staging_dir / f"stage_{uuid.uuid4().hex}_{sanitized}"
        with open(temp_staged, "wb") as f:
            f.write(content)

        try:
            file_hash = compute_sha256(temp_staged)
            byte_size = len(content)
            mime_type, _ = mimetypes.guess_type(original_filename)
            mime_type = mime_type or "application/octet-stream"

            dest_name = f"{file_hash[:16]}_{sanitized}"
            dest_relpath = f"originals/{dest_name}"
            dest_path = self.originals_dir / dest_name

            if not dest_path.exists():
                shutil.move(temp_staged, dest_path)
            else:
                actual_hash = compute_sha256(dest_path)
                if actual_hash != file_hash:
                    raise SourceCorruptedError(dest_relpath, file_hash, actual_hash)
                temp_staged.unlink(missing_ok=True)

            return StoredFile(
                file_hash=file_hash,
                byte_size=byte_size,
                mime_type=mime_type,
                storage_relpath=dest_relpath,
                original_filename=original_filename,
            )
        finally:
            if temp_staged.exists():
                temp_staged.unlink(missing_ok=True)

    def cleanup_staging(self) -> int:
        """Remove orphaned files from staging without touching referenced originals."""
        count = 0
        for f in self.staging_dir.iterdir():
            if f.is_file():
                f.unlink(missing_ok=True)
                count += 1
        return count
