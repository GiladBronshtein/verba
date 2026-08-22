"""Writing shared state without two writers destroying each other's work.

Every store in this system is a JSON file that is read whole, changed in
memory, and written whole: decisions, knowledge, notes, incidents, the asset
registry, the release log. That is the right shape for files a person is meant
to be able to open and read, and it has exactly one failure, which is two
writers at once. The second one to finish wins and the first one's work is
gone, with nothing anywhere saying it happened.

That used to be theoretical, because there was one console serving one project
and you had to go out of your way to run a second. It stopped being theoretical
when the console learned to switch documents and the command line grew a `fix`
that writes while you are looking at the same document in a browser.

Two things here:

* `locked(path)` takes an exclusive lock on a sidecar next to the file. The
  lock is advisory and only holds between processes that use it, which is all
  of them, because everything writes through `write_json`.
* `write_json` writes to a temporary file in the same directory and renames it
  over the target. Rename is atomic on POSIX, so a reader never sees half a
  file, and a process killed mid-write leaves the previous version intact
  rather than a truncated one.

The lock is not held while a caller thinks. It is taken for the read-change-
write of one store, which is short, so a person clicking in the console never
waits on a crawl.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

# Long enough that a slow disk or a big registry never trips it, short enough
# that a stale lock from a killed process is not a hang somebody has to debug.
TIMEOUT = 10.0


class LockTimeout(RuntimeError):
    pass


@contextmanager
def locked(path: Path | str, timeout: float = TIMEOUT):
    """Hold an exclusive lock for the file at `path` while the block runs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + timeout
    fh = open(lock_path, "w")
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(
                        f"another process has been writing {path.name} for more "
                        f"than {timeout:g}s. If nothing else is running, delete "
                        f"{lock_path}.")
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def write_json(path: Path | str, data, indent: int = 2, sort_keys: bool = False):
    """Write one JSON store, atomically, under a lock."""
    path = Path(path)
    with locked(path):
        _write_atomic(path, json.dumps(data, indent=indent, sort_keys=sort_keys,
                                       ensure_ascii=False) + "\n")


def write_text(path: Path | str, text: str):
    """The same guarantee for a file that is not JSON."""
    path = Path(path)
    with locked(path):
        _write_atomic(path, text)


def _write_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def update_json(path: Path | str, default=None):
    """Read, change, write, with the lock held across all three.

    The pattern every store here needs. Locking only the write is not enough:
    two processes can both read the old copy, both change it, and the second
    write still loses the first one's change.
    """
    path = Path(path)
    with locked(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {} if default is None else default
        box = [data]
        yield box
        _write_atomic(path, json.dumps(box[0], indent=2, sort_keys=False,
                                       ensure_ascii=False) + "\n")
