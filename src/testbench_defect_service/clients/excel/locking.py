"""Exclusive access to a defect file for the span of a read-modify-rewrite.

Creating, updating and deleting a defect all read the whole file, change one row and write
the whole file back. Two writers that read the same frame derive the same next defect id and
the later write wins, so a defect goes missing while both callers are told they succeeded.

The lock therefore has to hold across processes, not just across threads: Sanic starts one
worker process per core unless ``server.single_process`` is set, and the same file may be
served by a second instance or mounted from a share. Only the operating system can arbitrate
that, so exclusion rests on a byte-range lock on a sidecar file. The kernel drops such a lock
when the handle closes or the process dies, which means a crash cannot leave the file locked.

The sidecar keeps its own suffix and is never removed: deleting it would race with the next
writer that already holds a handle to it, and ``_get_file_path`` only ever matches files whose
suffix equals the configured ``file_type``.
"""

import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from testbench_defect_service.log import logger

LOCK_SUFFIX = ".lock"
DEFAULT_TIMEOUT_SECONDS = 30.0
_POLL_INTERVAL_SECONDS = 0.05
_LOCKED_BYTES = 1

if sys.platform == "win32":
    import msvcrt

    def _try_lock(handle: IO[bytes]) -> bool:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCKED_BYTES)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCKED_BYTES)

else:
    import fcntl

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()


def _thread_lock_for(defect_path: Path) -> threading.Lock:
    key = defect_path.as_posix().casefold()
    with _thread_locks_guard:
        return _thread_locks.setdefault(key, threading.Lock())


def _lock_file_path(defect_path: Path) -> Path:
    return defect_path.with_name(defect_path.name + LOCK_SUFFIX)


def _open_lock_file(lock_path: Path) -> IO[bytes]:
    # Append mode creates the sidecar without truncating a file another writer holds open.
    return lock_path.open("a+b")


def _release(handle: IO[bytes], defect_path: Path) -> None:
    try:
        _unlock(handle)
    except OSError as exc:
        # Closing the handle drops the lock anyway; losing the file would be the real problem.
        logger.debug("Could not release the lock on '%s': %s", defect_path.name, exc)


def _timeout_error(defect_path: Path) -> TimeoutError:
    return TimeoutError(
        f"Timed out waiting for exclusive access to '{defect_path.name}': another "
        "synchronization is writing to it. Please run the synchronization again."
    )


def _acquire_thread_lock(thread_lock: threading.Lock, timeout: float) -> bool:
    if timeout <= 0:
        return thread_lock.acquire(blocking=False)
    return thread_lock.acquire(timeout=timeout)


@contextmanager
def _os_lock(defect_path: Path, timeout: float) -> Iterator[None]:
    try:
        handle = _open_lock_file(_lock_file_path(defect_path))
    except OSError as exc:
        logger.warning(
            "Could not create the lock file next to '%s' (%s); writing without a lock. "
            "A concurrent writer could overwrite this change.",
            defect_path.name,
            exc,
        )
        yield
        return

    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise _timeout_error(defect_path)
            time.sleep(_POLL_INTERVAL_SECONDS)
        try:
            yield
        finally:
            _release(handle, defect_path)
    finally:
        handle.close()


@contextmanager
def lock_defect_file(
    defect_path: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Hold exclusive access to ``defect_path`` for the duration of the block.

    Raises ``TimeoutError`` - an ``OSError``, so the client's existing write-error handling
    reports it - when another writer holds the file longer than ``timeout`` seconds.
    """
    thread_lock = _thread_lock_for(defect_path)
    if not _acquire_thread_lock(thread_lock, timeout):
        raise _timeout_error(defect_path)
    try:
        with _os_lock(defect_path, timeout):
            yield
    finally:
        thread_lock.release()
