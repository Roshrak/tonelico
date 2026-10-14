"""Cross-platform process management, output limits, and process-tree termination."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Mapping


from factory_security import FactoryError

class ProcessError(FactoryError):
    """Process execution error."""
    def __init__(self, message: str, category: str = "process") -> None:
        super().__init__(message, category=category)


class ProcessTimeoutError(ProcessError):
    def __init__(self, message: str, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message, category="timeout")
        self.stdout = stdout
        self.stderr = stderr


class ProcessOutputLimitError(ProcessError):
    def __init__(self, message: str, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message, category="output_limit")
        self.stdout = stdout
        self.stderr = stderr


def resolve_executable(command: str) -> str:
    """Resolve command name to an executable path across Linux/NixOS and Windows."""
    if os.path.isabs(command):
        if os.access(command, os.X_OK):
            return command
        return command

    if sys.platform == "win32":
        if command.lower() in {"cmd.exe", "where.exe"}:
            return command
        try:
            res = subprocess.run(["where.exe", command], capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                candidates = [c.strip() for c in res.stdout.splitlines() if c.strip()]
                valid_exts = {".exe", ".cmd", ".bat", ".com"}
                for candidate in candidates:
                    ext = Path(candidate).suffix.lower()
                    if ext in valid_exts or not ext:
                        return candidate
        except Exception:
            pass
        return command

    if "/" in command or "\\" in command:
        p = Path(command)
        try:
            if p.is_file() and os.access(p, os.X_OK):
                return str(p.resolve())
        except OSError:
            pass
        return command

    # POSIX search
    which_path = shutil.which(command)
    if which_path:
        return which_path

    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / command
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    user_local_bin = Path.home() / ".local" / "bin" / command
    try:
        if user_local_bin.is_file() and os.access(user_local_bin, os.X_OK):
            return str(user_local_bin)
    except OSError:
        pass
    return command


def normalize_test_command(cmd: str) -> str:
    """Adapt test command for the current platform."""
    if not cmd:
        return cmd
    if sys.platform == "win32":
        if cmd.startswith("python3 "):
            return f'"{sys.executable}" ' + cmd[8:]
        elif cmd == "python3":
            return f'"{sys.executable}"'
        elif cmd.startswith("python "):
            return f'"{sys.executable}" ' + cmd[7:]
        elif cmd == "python":
            return f'"{sys.executable}"'
    else:
        if shutil.which("python3") is None and shutil.which("python") is None:
            if cmd.startswith("python3 "):
                return f'"{sys.executable}" ' + cmd[8:]
            elif cmd == "python3":
                return f'"{sys.executable}"'
            elif cmd.startswith("python "):
                return f'"{sys.executable}" ' + cmd[7:]
            elif cmd == "python":
                return f'"{sys.executable}"'
    return cmd


def kill_process_tree(proc: subprocess.Popen, timeout: float = 2.0) -> None:
    """Kill the process and all child processes across platforms."""
    pid = proc.pid
    if pid is None:
        return

    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return

    # POSIX process-group kill
    try:
        pgid = os.getpgid(pid)
        if pgid == os.getpgrp():
            try:
                proc.kill()
            except Exception:
                pass
            return
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except Exception:
            pass
        return

    # Escalate to SIGKILL if not dead after timeout
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                pass
        time.sleep(0.05)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def execute_process(
    argv: list[str] | str,
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int | float | None = None,
    shell: bool = False,
    stdin: str | bytes | None = None,
    max_output_bytes: int = 8 * 1024 * 1024,
) -> subprocess.CompletedProcess[str]:
    """Run a process with timeout, process-tree cleanup, and output limits."""
    if isinstance(argv, str) and not shell:
        import shlex
        cmd_args = shlex.split(argv)
    else:
        cmd_args = argv

    if (
        not cmd_args
        or (isinstance(cmd_args, str) and not cmd_args.strip())
        or (isinstance(cmd_args, (list, tuple)) and (not cmd_args[0] or not str(cmd_args[0]).strip()))
    ):
        raise ProcessError("command cannot be empty")

    start_new_session = sys.platform != "win32"
    stdin_bytes = stdin.encode("utf-8") if isinstance(stdin, str) else stdin

    try:
        proc = subprocess.Popen(
            cmd_args,
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env else None,
            stdin=subprocess.PIPE if stdin_bytes is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell,
            start_new_session=start_new_session,
        )
    except OSError as exc:
        raise ProcessError(f"could not execute {argv}: {exc}") from exc

    t_in: threading.Thread | None = None
    if stdin_bytes is not None and proc.stdin:
        def write_stdin():
            try:
                proc.stdin.write(stdin_bytes)
                proc.stdin.flush()
                proc.stdin.close()
            except Exception:
                pass

        t_in = threading.Thread(target=write_stdin, daemon=True)
        t_in.start()

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    total_bytes = 0
    limit_exceeded = False
    lock = threading.Lock()

    def read_stream(stream, chunks: list[bytes]):
        nonlocal total_bytes, limit_exceeded
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                should_kill = False
                with lock:
                    if total_bytes + len(chunk) > max_output_bytes:
                        allowed = max(0, max_output_bytes - total_bytes)
                        if allowed > 0:
                            chunks.append(chunk[:allowed])
                        total_bytes += len(chunk)
                        limit_exceeded = True
                        should_kill = True
                    else:
                        total_bytes += len(chunk)
                        chunks.append(chunk)
                if should_kill:
                    kill_process_tree(proc)
                    break
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    t_out = threading.Thread(target=read_stream, args=(proc.stdout, stdout_chunks), daemon=True)
    t_err = threading.Thread(target=read_stream, args=(proc.stderr, stderr_chunks), daemon=True)
    t_out.start()
    t_err.start()

    timed_out = False
    timer: threading.Timer | None = None
    if timeout:
        def on_timeout():
            nonlocal timed_out
            timed_out = True
            kill_process_tree(proc)

        timer = threading.Timer(float(timeout), on_timeout)
        timer.start()

    try:
        proc.wait()
    finally:
        if timer:
            timer.cancel()
        if proc.poll() is None:
            kill_process_tree(proc)
        if t_in is not None:
            t_in.join(timeout=1.0)
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

    stdout_str = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_str = b"".join(stderr_chunks).decode("utf-8", errors="replace")

    if limit_exceeded:
        raise ProcessOutputLimitError(
            f"command output exceeded {max_output_bytes} bytes: {argv}",
            stdout=stdout_str,
            stderr=stderr_str,
        )

    if timed_out:
        raise ProcessTimeoutError(
            f"command timed out after {timeout}s: {argv}",
            stdout=stdout_str,
            stderr=stderr_str,
        )

    return subprocess.CompletedProcess(
        args=argv,
        returncode=proc.returncode if proc.returncode is not None else 1,
        stdout=stdout_str,
        stderr=stderr_str,
    )
