"""Explicit, read-checked usage roots; never restrict them to a project folder."""
import os
from pathlib import Path


def log_files(locations=None):
    """Return None for default discovery, otherwise validate every configured root."""
    if locations is None:
        value = os.environ.get('LUMEN_USAGE_LOG_LOCATIONS')
        locations = value.split(os.pathsep) if value else None
    if locations is None:
        return None
    if not isinstance(locations, list) or not locations or any(not isinstance(p, (str, Path)) or not str(p).strip() for p in locations):
        raise ValueError('log_locations must be a nonempty list of file or directory paths.')
    files = set()
    for value in locations:
        path = Path(value).expanduser().resolve()
        if not path.exists() or not os.access(path, os.R_OK) or (path.is_dir() and not os.access(path, os.X_OK)):
            raise ValueError(f'Configured usage log location is unreadable: {path}')
        if path.is_file():
            with path.open('rb') as stream:
                stream.read(1)
            files.add(path)
        elif path.is_dir():
            def fail(error):
                raise ValueError(f'Configured usage log location is unreadable: {error.filename}') from error
            for root, dirs, names in os.walk(path, onerror=fail):
                for name in names:
                    if name.endswith('.jsonl'):
                        file = Path(root)/name
                        if not os.access(file, os.R_OK):
                            raise ValueError(f'Configured usage log file is unreadable: {file}')
                        files.add(file)
        else:
            raise ValueError(f'Configured usage log location is not a file or directory: {path}')
    return sorted(files)
