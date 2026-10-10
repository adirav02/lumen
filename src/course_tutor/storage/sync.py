"""Workspace-level file-based synchronization locking."""

import fcntl
import os
from pathlib import Path
from typing import Optional

from ..errors import RestoreIntegrityError


class WorkspaceSync:
    """Manages workspace-level file-based synchronization lock using flock.

    The lock file is placed in the parent directory: parent / f".{name}.sync"
    to ensure it is outside the workspace directory and will not be swapped during
    directory move or restore operations.
    """

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path).resolve()
        self.lock_path = self.workspace_path.parent / f".{self.workspace_path.name}.sync"
        self._fd: Optional[int] = None

    def acquire_shared(self) -> None:
        """Acquire shared lock for active LumenCore sessions."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(self._fd)
            self._fd = None
            raise

    def acquire_exclusive(self) -> None:
        """Acquire exclusive lock for restore operations."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            os.close(self._fd)
            self._fd = None
            raise RestoreIntegrityError(
                f"Target workspace '{self.workspace_path}' is actively in use by an active session. Cannot restore while active sessions exist."
            ) from exc

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
