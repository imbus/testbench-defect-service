import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from testbench_defect_service.clients.excel.locking import lock_defect_file


@pytest.fixture
def defect_path(tmp_path: Path) -> Path:
    path = tmp_path / "defects.csv"
    path.write_text("id,title\nD-0001,Demo\n", encoding="utf-8")
    return path


@pytest.mark.unit
def test_lock_excludes_another_thread_while_it_is_held(defect_path: Path):
    held = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with lock_defect_file(defect_path):
            held.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert held.wait(timeout=5)
        with pytest.raises(TimeoutError), lock_defect_file(defect_path, timeout=0.05):
            pass
    finally:
        release.set()
        holder.join(timeout=5)


@pytest.mark.unit
def test_lock_excludes_another_process_while_it_is_held(defect_path: Path):
    """Sanic runs one worker process per core unless single_process is set, so the lock has to
    be enforced by the operating system rather than by a lock object in this interpreter."""
    ready_path = defect_path.with_suffix(".ready")
    holder_source = textwrap.dedent(
        f"""
        from pathlib import Path
        import time
        from testbench_defect_service.clients.excel.locking import lock_defect_file

        with lock_defect_file(Path({str(defect_path)!r})):
            Path({str(ready_path)!r}).write_text("held", encoding="utf-8")
            time.sleep(3)
        """
    )
    holder = subprocess.Popen([sys.executable, "-c", holder_source])
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready_path.exists(), "the holder process never acquired the lock"

        with pytest.raises(TimeoutError), lock_defect_file(defect_path, timeout=0.05):
            pass
    finally:
        holder.kill()
        holder.wait(timeout=10)


@pytest.mark.unit
def test_lock_can_be_acquired_again_after_it_is_released(defect_path: Path):
    with lock_defect_file(defect_path):
        pass

    with lock_defect_file(defect_path, timeout=0.05):
        pass


@pytest.mark.unit
def test_timeout_names_the_file_so_the_protocol_entry_is_actionable(defect_path: Path):
    held = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with lock_defect_file(defect_path):
            held.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert held.wait(timeout=5)
        with pytest.raises(TimeoutError) as excinfo, lock_defect_file(defect_path, timeout=0.05):
            pass
        assert "defects.csv" in str(excinfo.value)
    finally:
        release.set()
        holder.join(timeout=5)


@pytest.mark.unit
def test_lock_proceeds_unlocked_when_the_lock_file_cannot_be_created(
    defect_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """A read-only directory must not turn a working deployment into a failing one: the write
    itself only needs the file to be writable."""
    monkeypatch.setattr(
        "testbench_defect_service.clients.excel.locking._open_lock_file",
        lambda _path: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
    )

    with lock_defect_file(defect_path):
        pass

    assert "without a lock" in caplog.text
