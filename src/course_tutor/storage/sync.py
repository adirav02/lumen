try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

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
        if fcntl is None or not hasattr(fcntl, "flock"):
            raise NotImplementedError(
                "Platform does not support fcntl.flock; cross-process workspace exclusion is unsupported on this platform."
            )
        self.workspace_path = Path(workspace_path).resolve()
        self.lock_path = self.workspace_path.parent / f".{self.workspace_path.name}.sync"
        self._fd: Optional[int] = None

    def acquire_shared(self) -> None:
        """Acquire shared lock for active LumenCore sessions."""
        if self._fd is not None:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            self._fd = fd
        except (BlockingIOError, OSError):
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    def acquire_exclusive(self) -> None:
        """Acquire exclusive lock for restore operations."""
        if self._fd is not None:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd = fd
        except (BlockingIOError, OSError) as exc:
            try:
                os.close(fd)
            except OSError:
                pass
            raise RestoreIntegrityError(
                f"Target workspace '{self.workspace_path}' is actively in use by an active session. Cannot restore while active sessions exist."
            ) from exc

    def release(self) -> None:
        fd = self._fd
        self._fd = None
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
