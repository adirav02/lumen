"""Database connection, transaction management, and SQLite snapshot utilities."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator, Union
import uuid


def get_connection(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a SQLite connection configured for Lumen.

    Enforces foreign keys, enables WAL journal mode where supported,
    sets a 30s busy timeout, enables autocommit mode to control transactions explicitly,
    and uses sqlite3.Row for dict-like access.
    """
    path_str = str(db_path)
    try:
        con = sqlite3.connect(path_str, timeout=30.0, autocommit=True)
    except TypeError:
        con = sqlite3.connect(path_str, timeout=30.0, isolation_level=None)

    con.row_factory = sqlite3.Row

    # Enforce foreign key constraints on every connection
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute("PRAGMA busy_timeout = 30000;")

    # Enable WAL mode for disk databases (in-memory stays memory)
    if path_str != ":memory:" and not path_str.startswith("file:"):
        try:
            con.execute("PRAGMA journal_mode = WAL;")
        except sqlite3.OperationalError:
            pass

    return con


@contextmanager
def atomic_transaction(con: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Execute within an immediate transaction or nested savepoint.

    Commits upon normal exit; rolls back upon exception.
    Supports nested calls safely via SQLite savepoints.
    """
    if con.in_transaction:
        sp_name = f"sp_{uuid.uuid4().hex[:8]}"
        con.execute(f"SAVEPOINT {sp_name};")
        try:
            yield con
            con.execute(f"RELEASE SAVEPOINT {sp_name};")
        except Exception:
            con.execute(f"ROLLBACK TO SAVEPOINT {sp_name};")
            raise
    else:
        con.execute("BEGIN IMMEDIATE;")
        try:
            yield con
            con.execute("COMMIT;")
        except Exception:
            con.execute("ROLLBACK;")
            raise


def snapshot_backup(source_con: sqlite3.Connection, target_db_path: Union[str, Path]) -> None:
    """Create a consistent online SQLite snapshot using the backup API."""
    target_path = Path(target_db_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    dest_con = sqlite3.connect(str(target_path))
    try:
        source_con.backup(dest_con)
    finally:
        dest_con.close()
