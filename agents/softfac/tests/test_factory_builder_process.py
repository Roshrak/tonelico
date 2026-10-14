"""Step 6 tests for the bounded Builder subprocess supervisor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from hermes_factory_v2 import (  # noqa: E402
    BuilderProcessError,
    FactoryError,
    run_builder_process,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "builder_process_fixture.py"


class BuilderProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwd = self.root / "unicode \u6d4b\u8bd5 directory with spaces"
        self.cwd.mkdir()
        self.stdout_path = self.root / "evidence" / "stdout.log"
        self.stderr_path = self.root / "evidence" / "stderr.log"
        self.env = os.environ.copy()
        self.env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_fixture(self, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return run_builder_process(
            [sys.executable, str(FIXTURE), *args],
            cwd=self.cwd,
            env=self.env,
            timeout=kwargs.pop("timeout", 10),
            stdout_path=self.stdout_path,
            stderr_path=self.stderr_path,
            **kwargs,
        )

    def test_argv_cwd_unicode_and_stdin_are_exact(self) -> None:
        values = ["雪", 'quote " preserved', "semi; & | $()"]
        result = self.run_fixture("echo", *values)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["argv"], values)
        self.assertEqual(Path(payload["cwd"]).resolve(), self.cwd.resolve())
        self.assertEqual(payload["stdin"], "")
        self.assertEqual(self.stdout_path.read_bytes(), result.stdout.encode("utf-8"))
        self.assertEqual(self.stderr_path.read_bytes(), b"")

    def test_both_pipes_are_drained_without_deadlock(self) -> None:
        result = self.run_fixture("both-flood", "200000", max_output_bytes=300000)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout.encode("utf-8")), 200000)
        self.assertEqual(len(result.stderr.encode("utf-8")), 200000)

    def test_output_overflow_keeps_bounded_partial_stderr(self) -> None:
        with self.assertRaises(BuilderProcessError) as context:
            self.run_fixture("stderr-flood", "100000", max_output_bytes=4096)
        self.assertIn("output exceeded", str(context.exception))
        retained = self.stderr_path.read_bytes()
        self.assertLessEqual(len(retained), 4096)
        self.assertTrue(retained.startswith(b"E"))

    def test_malformed_utf8_is_retained_and_fails_closed(self) -> None:
        with self.assertRaises(BuilderProcessError) as context:
            self.run_fixture("invalid-utf8")
        self.assertIn("malformed UTF-8", str(context.exception))
        self.assertEqual(self.stdout_path.read_bytes(), b"before-\xff-after")

    def test_timeout_keeps_partial_stdout(self) -> None:
        with self.assertRaises(BuilderProcessError) as context:
            self.run_fixture("sleep", "10", timeout=0.4)
        self.assertIn("timed out", str(context.exception))
        self.assertEqual(self.stdout_path.read_bytes(), b"ready\n")

    def test_progress_probe_observes_host_file_write_without_early_kill(self) -> None:
        target = self.cwd / "progress.txt"
        first_write: list[float] = []
        started = time.monotonic()

        def observe() -> None:
            if target.is_file() and not first_write:
                first_write.append(time.monotonic() - started)

        result = self.run_fixture("write-file", str(target), "0.15", progress_probe=observe)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(first_write)
        self.assertGreaterEqual(first_write[0], 0.1)
        self.assertLess(first_write[0], 2)
        self.assertTrue(target.is_file())

    def test_cancellation_stops_descendant_before_delayed_write(self) -> None:
        target = self.root / "unrelated \u6d4b\u8bd5" / "late.txt"
        armed = self.root / "unrelated \u6d4b\u8bd5" / "armed.txt"
        target.parent.mkdir()
        cancel = threading.Event()
        outcome: dict[str, object] = {}

        def run() -> None:
            try:
                outcome["result"] = self.run_fixture(
                    "spawn-late-writer",
                    str(target),
                    "0.8",
                    str(armed),
                    timeout=10,
                    cancel_event=cancel,
                )
            except BuilderProcessError as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=run)
        worker.start()
        try:
            deadline = time.monotonic() + 3
            while not armed.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(armed.exists(), "descendant readiness marker was not observed")
            cancel.set()
        finally:
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "supervisor did not finish after cancellation")
        self.assertIsInstance(outcome.get("error"), BuilderProcessError)
        self.assertIn("cancelled", str(outcome["error"]))
        time.sleep(1.2)
        self.assertFalse(target.exists())

    def test_successful_parent_exit_stops_descendant_before_return(self) -> None:
        target = self.root / "normal-exit \u6d4b\u8bd5" / "late.txt"
        armed = self.root / "normal-exit \u6d4b\u8bd5" / "armed.txt"
        target.parent.mkdir()
        result = self.run_fixture(
            "spawn-late-writer-and-exit",
            str(target),
            "0.8",
            str(armed),
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.stdout_path.read_bytes(), b"parent-exited\n")
        self.assertTrue(armed.exists(), "descendant readiness marker was not observed")
        time.sleep(1.2)
        self.assertFalse(target.exists())

    def test_uncontained_control_writes_after_deadline(self) -> None:
        """Prove the delayed-writer fixture discriminates missing containment."""
        target = self.root / "uncontained \u6d4b\u8bd5" / "late.txt"
        armed = self.root / "uncontained \u6d4b\u8bd5" / "armed.txt"
        target.parent.mkdir()
        control = subprocess.Popen(
            [
                sys.executable,
                str(FIXTURE),
                "spawn-late-writer-and-exit",
                str(target),
                "0.8",
                str(armed),
            ],
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        try:
            armed_deadline = time.monotonic() + 3
            while not armed.exists() and time.monotonic() < armed_deadline:
                time.sleep(0.02)
            self.assertTrue(armed.exists(), "uncontained control never armed its descendant")
            self.assertEqual(control.wait(timeout=3), 0)
            observe_until = time.monotonic() + 0.8 + 0.6
            while not target.exists() and time.monotonic() < observe_until:
                time.sleep(0.02)
            self.assertTrue(target.exists(), "uncontained control did not write after its deadline")
        finally:
            if control.poll() is None:
                control.kill()
                control.wait(timeout=3)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object assignment cleanup")
    def test_failed_job_assignment_directly_terminates_suspended_process(self) -> None:
        class FakeProcess:
            _handle = 123

            def __init__(self) -> None:
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self) -> None:
                self.terminated = True
                self.returncode = -15

            def kill(self) -> None:
                self.terminated = True
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode

        class FailingJob:
            def __init__(self) -> None:
                self.closed = False
                self.terminated = False

            def assign(self, process) -> None:
                raise OSError("assignment rejected")

            def terminate(self) -> None:
                self.terminated = True

            def close(self) -> None:
                self.closed = True

        process = FakeProcess()
        job = FailingJob()
        with patch("hermes_factory_v2._WindowsBuilderJob", return_value=job):
            with patch("hermes_factory_v2.subprocess.Popen", return_value=process):
                with self.assertRaises(BuilderProcessError) as context:
                    run_builder_process(
                        [sys.executable, str(FIXTURE), "echo"],
                        cwd=self.cwd,
                        env=self.env,
                        timeout=2,
                        stdout_path=self.stdout_path,
                        stderr_path=self.stderr_path,
                    )
        self.assertIn("assign", str(context.exception))
        self.assertTrue(process.terminated)
        self.assertTrue(job.closed)
        self.assertFalse(job.terminated)
        self.assertEqual(self.stdout_path.read_bytes(), b"")
        self.assertEqual(self.stderr_path.read_bytes(), b"")

    def test_nonzero_exit_is_returned_for_result_parser(self) -> None:
        result = self.run_fixture("exit", "7")
        self.assertEqual(result.returncode, 7)

    def test_spawn_failure_creates_empty_evidence_without_prompt_leak(self) -> None:
        secret = "prompt-secret-雪"
        with patch("hermes_factory_v2.subprocess.Popen", side_effect=OSError(secret)) as popen:
            with self.assertRaises(BuilderProcessError) as context:
                run_builder_process(
                    [sys.executable, str(FIXTURE), "echo", secret],
                    cwd=self.cwd,
                    env=self.env,
                    timeout=2,
                    stdout_path=self.stdout_path,
                    stderr_path=self.stderr_path,
                )
        popen.assert_called_once()
        self.assertNotIn(secret, str(context.exception))
        self.assertEqual(self.stdout_path.read_bytes(), b"")
        self.assertEqual(self.stderr_path.read_bytes(), b"")

    def test_nul_is_rejected_before_spawn(self) -> None:
        with patch("hermes_factory_v2.subprocess.Popen") as popen:
            with self.assertRaisesRegex(FactoryError, "NUL"):
                run_builder_process(
                    [sys.executable, str(FIXTURE), "echo", "bad\x00prompt"],
                    cwd=self.cwd,
                    env=self.env,
                    timeout=2,
                    stdout_path=self.stdout_path,
                    stderr_path=self.stderr_path,
                )
        popen.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows command-line budget")
    def test_oversized_windows_command_line_is_rejected_before_spawn(self) -> None:
        with patch("hermes_factory_v2.subprocess.Popen") as popen:
            with self.assertRaisesRegex(FactoryError, "conservative Windows limit"):
                run_builder_process(
                    [sys.executable, str(FIXTURE), "echo", "x" * 31000],
                    cwd=self.cwd,
                    env=self.env,
                    timeout=2,
                    stdout_path=self.stdout_path,
                    stderr_path=self.stderr_path,
                )
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
