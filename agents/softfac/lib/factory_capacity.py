"""Shared capacity controller and file-based concurrency locks."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator


from factory_security import FactoryError

class CapacityError(FactoryError):
    """Capacity acquisition or exhaustion error."""
    def __init__(self, message: str, category: str = "capacity") -> None:
        super().__init__(message, category=category)


def is_pid_alive(pid: int | Any) -> bool:
    """Check if process with PID is currently alive."""
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    pid = pid_int
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return exit_code.value == STILL_ACTIVE
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    if sys.platform.startswith("linux"):
        try:
            status_text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
            for line in status_text.splitlines():
                if line.startswith("State:"):
                    if "Z" in line:  # Zombie / defunct process
                        return False
                    break
        except (ProcessLookupError, FileNotFoundError):
            return False
        except Exception:
            pass

    return True


@dataclass
class SlotLock:
    slot_dir: Path
    owner_info: dict
    _released: bool = False

    def __enter__(self) -> SlotLock:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if not self.slot_dir.exists():
            return
        owner_file = self.slot_dir / "owner.json"
        try:
            if owner_file.is_file():
                data = json.loads(owner_file.read_text(encoding="utf-8"))
                if (
                    data.get("pid") != self.owner_info.get("pid")
                    or data.get("created_at") != self.owner_info.get("created_at")
                ):
                    # Slot was reclaimed by another owner; do not delete active slot
                    return
            stale_target = self.slot_dir.with_name(f".release_{self.slot_dir.name}_{os.getpid()}_{time.time()}")
            self.slot_dir.rename(stale_target)
            shutil.rmtree(stale_target, ignore_errors=True)
        except Exception:
            pass


def acquire_slot(
    lock_root: Path,
    name: str,
    limit: int,
    timeout_seconds: float = 30.0,
    stale_seconds: float = 1200.0,
    run_id: str | None = None,
) -> SlotLock:
    """Acquire an atomic filesystem directory slot."""
    if limit <= 0:
        raise CapacityError(f"Capacity limit must be positive, got {limit}", "capacity")
    if timeout_seconds < 0:
        raise CapacityError(f"Timeout must be non-negative, got {timeout_seconds}", "capacity")
    if stale_seconds <= 0:
        raise CapacityError(f"stale_seconds must be positive, got {stale_seconds}", "capacity")
    slot_group = lock_root / name
    slot_group.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.time() + timeout_seconds

    while True:
        for index in range(limit):
            slot_dir = slot_group / str(index)
            try:
                slot_dir.mkdir(mode=0o700)
                try:
                    owner_file = slot_dir / "owner.json"
                    temp_owner = slot_dir / f"owner.json.{os.getpid()}.tmp"
                    owner_info = {
                        "pid": os.getpid(),
                        "run_id": run_id,
                        "created_at": time.time(),
                    }
                    temp_owner.write_text(json.dumps(owner_info), encoding="utf-8")
                    temp_owner.replace(owner_file)
                    return SlotLock(slot_dir=slot_dir, owner_info=owner_info)
                except BaseException:
                    shutil.rmtree(slot_dir, ignore_errors=True)
                    raise
            except FileExistsError:
                # Check for stale slot
                owner_file = slot_dir / "owner.json"
                is_stale = False
                now = time.time()
                owner_pid = None
                created_at = None
                if owner_file.is_file():
                    try:
                        data = json.loads(owner_file.read_text(encoding="utf-8"))
                        owner_pid = data.get("pid")
                        created_at = data.get("created_at", 0)
                        if owner_pid and not is_pid_alive(owner_pid):
                            is_stale = True
                        elif now - created_at > stale_seconds:
                            is_stale = True
                    except Exception:
                        try:
                            mtime = owner_file.stat().st_mtime
                            if now - mtime > 5.0:
                                is_stale = True
                        except Exception:
                            is_stale = True
                else:
                    # Missing owner file; if dir is older than 5 seconds without owner, process crashed
                    try:
                        mtime = slot_dir.stat().st_mtime
                        if now - mtime > 5.0:
                            is_stale = True
                    except Exception:
                        pass

                if is_stale:
                    # Double-check owner before rename so we don't clobber a newly acquired slot
                    if owner_file.is_file() and owner_pid is not None:
                        try:
                            check_data = json.loads(owner_file.read_text(encoding="utf-8"))
                            if check_data.get("pid") != owner_pid or check_data.get("created_at") != created_at:
                                continue
                        except Exception:
                            pass
                    stale_target = slot_group / f".stale_{index}_{os.getpid()}_{time.time()}"
                    try:
                        slot_dir.rename(stale_target)
                        shutil.rmtree(stale_target, ignore_errors=True)
                    except (FileNotFoundError, OSError):
                        pass

        if time.time() >= deadline:
            break
        time.sleep(0.1)

    raise CapacityError(f"Timed out waiting for shared {name} capacity (limit={limit})", "capacity")


@contextlib.contextmanager
def acquire_capacity(
    lock_root: Path,
    tier: str = "builder",
    tier_limit: int = 2,
    global_limit: int = 4,
    timeout_seconds: float = 30.0,
    run_id: str | None = None,
) -> Generator[None, None, None]:
    """Acquire both global and tier capacity slots within a context."""
    start_time = time.time()
    global_lock = acquire_slot(
        lock_root=lock_root,
        name="global",
        limit=global_limit,
        timeout_seconds=timeout_seconds,
        run_id=run_id,
    )
    elapsed = time.time() - start_time
    remaining_timeout = max(0.0, timeout_seconds - elapsed)
    try:
        tier_lock = acquire_slot(
            lock_root=lock_root,
            name=f"tier_{tier}",
            limit=tier_limit,
            timeout_seconds=remaining_timeout,
            run_id=run_id,
        )
        try:
            yield
        finally:
            tier_lock.release()
    finally:
        global_lock.release()
