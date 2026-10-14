"""Small real subprocess fixture for the Step 6 Builder supervisor tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _write(stream, value: str) -> None:
    raw_stream = getattr(stream, "buffer", stream)
    raw_stream.write(value.encode("utf-8"))
    raw_stream.flush()


def main() -> int:
    mode = sys.argv[1]
    if mode == "echo":
        payload = {
            "argv": sys.argv[2:],
            "cwd": os.getcwd(),
            "stdin": sys.stdin.buffer.read().decode("utf-8"),
        }
        _write(sys.stdout, json.dumps(payload, ensure_ascii=False) + "\n")
        return 0
    if mode == "both-flood":
        count = int(sys.argv[2])
        chunk = b"X" * 4096
        remaining = count
        while remaining:
            part = chunk[: min(remaining, len(chunk))]
            sys.stdout.buffer.write(part)
            sys.stderr.buffer.write(part)
            remaining -= len(part)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.flush()
        return 0
    if mode == "stderr-flood":
        count = int(sys.argv[2])
        sys.stderr.buffer.write(b"E" * count)
        sys.stderr.buffer.flush()
        return 0
    if mode == "invalid-utf8":
        sys.stdout.buffer.write(b"before-\xff-after")
        sys.stdout.buffer.flush()
        return 0
    if mode == "sleep":
        _write(sys.stdout, "ready\n")
        time.sleep(float(sys.argv[2]))
        return 0
    if mode == "write-file":
        time.sleep(float(sys.argv[3]))
        Path(sys.argv[2]).write_text("progress-write\n", encoding="utf-8")
        return 0
    if mode == "spawn-late-writer":
        target = sys.argv[2]
        delay = sys.argv[3]
        armed = sys.argv[4] if len(sys.argv) > 4 else ""
        _write(sys.stdout, "ready\n")
        subprocess.Popen(
            [sys.executable, __file__, "late-write", target, delay, armed],
            stdin=subprocess.DEVNULL,
            stdout=sys.stdout,
            stderr=sys.stderr,
            close_fds=True,
        )
        if armed:
            deadline = time.monotonic() + 2
            while not Path(armed).exists() and time.monotonic() < deadline:
                time.sleep(0.01)
        time.sleep(30)
        return 0
    if mode == "spawn-late-writer-and-exit":
        target = sys.argv[2]
        delay = sys.argv[3]
        armed = sys.argv[4] if len(sys.argv) > 4 else ""
        _write(sys.stdout, "parent-exited\n")
        subprocess.Popen(
            [sys.executable, __file__, "late-write", target, delay, armed],
            stdin=subprocess.DEVNULL,
            stdout=sys.stdout,
            stderr=sys.stderr,
            close_fds=True,
        )
        if armed:
            deadline = time.monotonic() + 2
            while not Path(armed).exists() and time.monotonic() < deadline:
                time.sleep(0.01)
        return 0
    if mode == "late-write":
        armed = sys.argv[4] if len(sys.argv) > 4 else ""
        if armed:
            Path(armed).write_text("descendant-started\n", encoding="utf-8")
        time.sleep(float(sys.argv[3]))
        Path(sys.argv[2]).write_text("late-writer-ran\n", encoding="utf-8")
        return 0
    if mode == "exit":
        return int(sys.argv[2])
    raise ValueError(f"unknown fixture mode: {mode}")


if __name__ == "__main__":
    raise SystemExit(main())
