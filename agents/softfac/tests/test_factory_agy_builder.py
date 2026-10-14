"""Step 7 tests for the direct AGY Builder and stream protocol."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermes_factory_v2 as factory_module  # noqa: E402
from hermes_factory_v2 import (  # noqa: E402
    AGY_EVENT_RECORD_MAX_BYTES,
    AgyBuilder,
    BuilderFailure,
    BuilderProcessError,
    Config,
    FactoryError,
    parse_agy_event_stream,
)


FIXTURE_METADATA = Path(__file__).resolve().parent / "fixtures" / "agy" / "1.2.0" / "step7_stream_fixtures.json"
PROCESS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "builder_process_fixture.py"


def make_stream(
    *,
    model: str,
    cwd: str,
    conversation_id: str = "fresh-conversation",
    result_conversation_id: str | None = None,
    status: str = "SUCCESS",
    response: str = "implementation complete; error and token limit are ordinary prose",
    num_turns: int = 1,
    duplicate_result: bool = False,
    omit_result: bool = False,
    omit_update: bool = False,
    duplicate_key: bool = False,
    extra_init: bool = False,
) -> str:
    init = {
        "event": "init",
        "conversation_id": conversation_id,
        "init": {
            "model": model,
            "cwd": cwd,
            "tools": ["terminal", "file"],
            "permission_mode": "always-proceed",
        },
    }
    update = {
        "event": "step_update",
        "step_update": {
            "conversation_id": conversation_id,
            "step_index": 0,
            "state": "DONE",
            "step_type": "agent_response",
        },
    }
    result_payload: dict[str, object] = {
        "conversation_id": result_conversation_id or conversation_id,
        "status": status,
        "response": response,
        "duration_seconds": 0.2,
        "num_turns": num_turns,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    if status == "ERROR":
        result_payload["error"] = "fixture runtime error"
    result = {"event": "result", "result": result_payload}
    events = [init] if omit_update else [init, update]
    if extra_init:
        events.append(
            {
                "event": "init",
                "conversation_id": "later-conversation",
                "init": {
                    "model": model,
                    "cwd": cwd,
                    "tools": ["terminal", "file"],
                    "permission_mode": "always-proceed",
                },
            }
        )
    if not omit_result:
        events.append(result)
        if duplicate_result:
            events.append(result)
    if duplicate_key:
        return (
            '{"event":"init","event":"init","conversation_id":"fresh-conversation",'
            '"init":{"model":"gemini-3.8-flash-high","cwd":"%s",'
            '"tools":["terminal"],"permission_mode":"always-proceed"}}\n' % cwd
        )
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"


class AgyBuilderRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.candidate = self.run_dir / "worktree"
        for repo in (self.source, self.candidate):
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Step 7 Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "step7@example.invalid"], cwd=repo, check=True)
        (self.source / "allowed.py").write_text("value = 1\n", encoding="utf-8")
        (self.candidate / "allowed.py").write_text("value = 1\n", encoding="utf-8")
        for repo in (self.source, self.candidate):
            subprocess.run(["git", "add", "allowed.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
        self.executable = self.root / "agy.exe"
        self.executable.write_bytes(b"audited agy fixture")
        self.executable.chmod(0o755)
        self.executable_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        candidate_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.candidate, text=True
        ).strip()
        factory_module.atomic_json(
            self.run_dir / "run_state.json",
            {
                "schema_version": factory_module.SCHEMA_VERSION,
                "run_config_version": factory_module.RUN_CONFIG_VERSION,
                "builder_backend": "agy",
                "builder_contract_version": factory_module.BUILDER_CONTRACT_VERSION,
                "run_id": self.run_dir.name,
                "worktree": str(self.candidate.resolve()),
                "base_commit": candidate_head,
                "branch": "hermes/task-step7-test",
                "factory_worktree_authorized": True,
                "boundary_test_fixture": True,
                "candidate_git_common_dir": str((self.candidate / ".git").resolve()),
            },
        )
        self.config = Config(
            repo=str(self.source),
            request="step 7 fixture",
            requested_files=["allowed.py"],
            test_command="python -c pass",
            agy_bin=str(self.executable),
            builder_timeout=30,
        )
        self.calls: list[dict[str, object]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_builder(self) -> AgyBuilder:
        def runner(*, argv, candidate, config, stdout_path, stderr_path, run_root):
            env = os.environ.copy()
            env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
            result = factory_module.run_builder_process(
                argv,
                cwd=candidate,
                env=env,
                timeout=config.builder_timeout,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            return result, str(candidate.resolve()), {
                "boundary": "injected_builder_runner",
                "protected_roots_mapped": False,
            }

        return AgyBuilder(str(self.executable), _builder_runner=runner)

    def fake_process(self, *, stream: str, returncode: int = 0, stderr: str = ""):
        def call(argv, **kwargs):
            self.calls.append({"argv": list(argv), **kwargs})
            Path(kwargs["stdout_path"]).write_bytes(stream.encode("utf-8"))
            Path(kwargs["stderr_path"]).write_bytes(stderr.encode("utf-8"))
            return subprocess.CompletedProcess(argv, returncode, stream, stderr)

        return call

    def run_builder(self, stream: str, *, returncode: int = 0, stderr: str = "") -> AgyBuilder:
        builder = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module,
            "run_builder_process",
            side_effect=self.fake_process(stream=stream, returncode=returncode, stderr=stderr),
        ):
            builder.run(
                worktree=self.candidate,
                instruction="Make the allowed change; do not use Git.",
                allowed_files=["allowed.py"],
                config=self.config,
                run_dir=self.run_dir,
                label="builder_initial",
            )
        return builder

    def stream(self, **updates: object) -> str:
        values: dict[str, object] = {
            "model": self.config.builder_model,
            "cwd": str(self.candidate.resolve()),
        }
        values.update(updates)
        return make_stream(**values)

    def test_valid_run_binds_attempt_artifact_and_argv(self) -> None:
        self.run_builder(self.stream())
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        argv = call["argv"]
        self.assertEqual(argv[0], str(self.executable.resolve()))
        self.assertEqual(argv[1:9], [
            "--model",
            "gemini-3.8-flash-high",
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--disable-slash-commands",
            "--print-timeout",
            "24s",
        ])
        self.assertEqual(argv[9], "--print")
        self.assertNotIn("--continue", argv)
        self.assertNotIn("--conversation", argv)
        self.assertEqual(call["cwd"], self.candidate.resolve())
        attempts = list((self.run_dir / "builder_attempts").glob("builder_initial-*"))
        self.assertEqual(len(attempts), 1)
        artifact = json.loads((attempts[0] / "attempt.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact["status"], "SUCCESS")
        self.assertEqual(artifact["termination_reason"], "NO_PATCH")
        self.assertEqual(artifact["navigation"]["strategy"], "normal")
        self.assertGreater(artifact["navigation"]["inspectable_bytes"], 0)
        self.assertIn("allowed.py", artifact["navigation"]["inspectable_files"])
        self.assertEqual(artifact["allowed_files"], ["allowed.py"])
        self.assertEqual(artifact["executable"]["sha256"], self.executable_hash)
        self.assertTrue((attempts[0] / "instruction.txt").is_file())
        self.assertFalse((self.candidate / "builder_attempts").exists())

    def test_dirty_allowed_candidate_is_a_valid_repair_baseline(self) -> None:
        self.run_builder(self.stream(conversation_id="initial-turn"))
        (self.candidate / "allowed.py").write_text("value = 2\n", encoding="utf-8")
        state = json.loads((self.run_dir / "run_state.json").read_text(encoding="utf-8"))
        state["candidate_baseline_identity"] = AgyBuilder._candidate_baseline_identity(self.candidate)
        factory_module.atomic_json(self.run_dir / "run_state.json", state)
        builder = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module,
            "run_builder_process",
            side_effect=self.fake_process(stream=self.stream(conversation_id="repair-turn")),
        ):
            builder.run(
                worktree=self.candidate,
                instruction="Repair the allowed change; do not use Git.",
                allowed_files=["allowed.py"],
                config=self.config,
                run_dir=self.run_dir,
                label="builder_repair",
            )
        self.assertEqual(len(self.calls), 2)
        attempts = list((self.run_dir / "builder_attempts").glob("builder_repair-*"))
        self.assertEqual(len(attempts), 1)
        self.assertEqual(
            json.loads((attempts[0] / "attempt.json").read_text(encoding="utf-8"))["status"],
            "SUCCESS",
        )

    def test_fixture_metadata_is_sanitized_and_complete(self) -> None:
        data = json.loads(FIXTURE_METADATA.read_text(encoding="utf-8"))
        self.assertTrue(data["sanitized"])
        self.assertIn("missing_terminal_result", data["negative_cases"])
        self.assertIn("duplicate_json_key", data["negative_cases"])

    def test_parser_accepts_ordinary_response_words(self) -> None:
        parsed = parse_agy_event_stream(self.stream().encode("utf-8"))
        self.assertEqual(parsed["result"]["status"], "SUCCESS")
        self.assertIn("token limit", parsed["result"]["response"])

    def test_parser_rejects_required_negative_cases(self) -> None:
        cases = [
            (b"\xff", "agy_protocol_error"),
            (self.stream(omit_result=True).encode("utf-8"), "agy_output_incomplete"),
            (make_stream(model=self.config.builder_model, cwd=str(self.candidate), duplicate_result=True).encode("utf-8"), "agy_protocol_error"),
            (make_stream(model=self.config.builder_model, cwd=str(self.candidate), duplicate_key=True).encode("utf-8"), "agy_protocol_error"),
            (make_stream(model=self.config.builder_model, cwd=str(self.candidate), status="ERROR").encode("utf-8"), "agy_runtime_error"),
            (make_stream(model=self.config.builder_model, cwd=str(self.candidate), num_turns=0).encode("utf-8"), "agy_output_incomplete"),
        ]
        for raw, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(BuilderFailure) as context:
                    parse_agy_event_stream(raw)
                self.assertEqual(context.exception.code, code)

    def test_parser_requires_a_step_update_before_terminal_success(self) -> None:
        with self.assertRaises(BuilderFailure) as context:
            parse_agy_event_stream(
                self.stream(omit_update=True).encode("utf-8")
            )
        self.assertEqual(context.exception.code, "agy_output_incomplete")

    def test_run_maps_wrong_model_cwd_and_process_failures(self) -> None:
        cases = [
            (self.stream(model="gemini-3.7-flash-high"), "agy_model_mismatch", "model"),
            (self.stream(cwd=str(self.source.resolve()), conversation_id="wrong-cwd"), "agy_isolation_failed", "cwd"),
        ]
        for stream, code, label in cases:
            with self.subTest(label=label):
                builder = self.make_builder()
                with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
                    factory_module,
                    "run_builder_process",
                    side_effect=self.fake_process(stream=stream),
                ):
                    with self.assertRaises(BuilderFailure) as context:
                        builder.run(
                            worktree=self.candidate,
                            instruction="bounded instruction",
                            allowed_files=["allowed.py"],
                            config=self.config,
                            run_dir=self.run_dir,
                            label="builder_retry",
                        )
                self.assertEqual(context.exception.code, code)

        builder = self.make_builder()
        process_error = BuilderProcessError(
            "Builder process timed out; partial evidence was retained",
            stdout_path=self.root / "stdout",
            stderr_path=self.root / "stderr",
            failure_code="agy_timeout",
        )
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module, "run_builder_process", side_effect=process_error
        ):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="bounded instruction",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="builder_timeout",
                )
        self.assertEqual(context.exception.code, "agy_timeout")

    def test_explicit_provider_outcomes_are_not_classified_as_timeouts(self) -> None:
        cases = [
            ("token budget exhausted for this session", "agy_token_budget_exhausted"),
            ("429 rate limit exceeded", "agy_rate_limit"),
            ("provider quota exhausted", "agy_provider_quota"),
        ]
        for stderr, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                builder = self.make_builder()
                with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
                    factory_module,
                    "run_builder_process",
                    side_effect=self.fake_process(
                        stream=self.stream(conversation_id=expected_code),
                        returncode=1,
                        stderr=stderr,
                    ),
                ):
                    with self.assertRaises(BuilderFailure) as context:
                        builder.run(
                            worktree=self.candidate,
                            instruction="bounded instruction",
                            allowed_files=["allowed.py"],
                            config=self.config,
                            run_dir=self.run_dir,
                            label="provider_outcome",
                        )
                self.assertEqual(context.exception.code, expected_code)

    def test_structured_and_overlapping_diagnostics_use_shared_precedence(self) -> None:
        events = [json.loads(line) for line in self.stream(conversation_id="structured-token").splitlines()]
        events[-1]["result"]["status"] = "ERROR"
        events[-1]["result"]["error"] = "token budget exhausted at turn limit"
        structured = "\n".join(json.dumps(event) for event in events) + "\n"
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module,
            "run_builder_process",
            side_effect=self.fake_process(stream=structured, returncode=1),
        ):
            with self.assertRaises(BuilderFailure) as context:
                self.make_builder().run(
                    worktree=self.candidate,
                    instruction="bounded instruction",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="structured_token",
                )
        self.assertEqual(context.exception.code, "agy_token_budget_exhausted")

        cases = [
            ("RESOURCE_EXHAUSTED: quota exceeded by rate limit", "agy_rate_limit"),
            ("provider account quota exhausted", "agy_provider_quota"),
            ("the bounded CLI timed out", "agy_timeout"),
        ]
        for stderr, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
                    factory_module,
                    "run_builder_process",
                    side_effect=self.fake_process(
                        stream=self.stream(conversation_id=f"diagnostic-{expected_code}"),
                        returncode=1,
                        stderr=stderr,
                    ),
                ):
                    with self.assertRaises(BuilderFailure) as context:
                        self.make_builder().run(
                            worktree=self.candidate,
                            instruction="bounded instruction",
                            allowed_files=["allowed.py"],
                            config=self.config,
                            run_dir=self.run_dir,
                            label=f"diagnostic_{expected_code}",
                        )
                self.assertEqual(context.exception.code, expected_code)

    def test_run_rejects_stale_conversation_and_nonzero_exit(self) -> None:
        stream = self.stream(conversation_id="same-id")
        builder = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module, "run_builder_process", side_effect=self.fake_process(stream=stream)
        ):
            builder.run(
                worktree=self.candidate,
                instruction="first bounded instruction",
                allowed_files=["allowed.py"],
                config=self.config,
                run_dir=self.run_dir,
                label="first",
            )
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="second bounded instruction",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="second",
                )
        self.assertEqual(context.exception.code, "agy_protocol_error")

        builder = self.make_builder()
        nonzero_stream = self.stream(conversation_id="nonzero-id")
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module,
            "run_builder_process",
            side_effect=self.fake_process(stream=nonzero_stream, returncode=1),
        ):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="failed bounded instruction",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="nonzero",
                )
        self.assertEqual(context.exception.code, "agy_runtime_error")

    def test_failed_conversation_is_reserved_across_attempts_and_instances(self) -> None:
        stream = self.stream(conversation_id="reserved-error", status="ERROR")
        first = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module, "run_builder_process", side_effect=self.fake_process(stream=stream)
        ):
            with self.assertRaises(BuilderFailure) as first_context:
                first.run(
                    worktree=self.candidate,
                    instruction="failed first turn",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="error_first",
                )
        self.assertEqual(first_context.exception.code, "agy_runtime_error")
        attempt_files = list((self.run_dir / "builder_attempts").glob("error_first-*/attempt.json"))
        self.assertEqual(len(attempt_files), 1)
        first_artifact = json.loads(attempt_files[0].read_text(encoding="utf-8"))
        self.assertRegex(first_artifact["conversation_id_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(first_artifact["conversation_reservation"], "RESERVED")

        second = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module, "run_builder_process", side_effect=self.fake_process(stream=stream)
        ):
            with self.assertRaises(BuilderFailure) as second_context:
                second.run(
                    worktree=self.candidate,
                    instruction="reused failed turn",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="error_second",
                )
        self.assertEqual(second_context.exception.code, "agy_protocol_error")

    def test_all_init_identities_are_reserved_before_malformed_stream_acceptance(self) -> None:
        stream = self.stream(conversation_id="first-conversation", extra_init=True)
        builder = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module, "run_builder_process", side_effect=self.fake_process(stream=stream)
        ):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="duplicate init stream",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="duplicate_init",
                )
        self.assertEqual(context.exception.code, "agy_protocol_error")
        evidence_path = next((self.run_dir / "builder_attempts").glob("duplicate_init-*/attempt.json"))
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(len(evidence["conversation_id_sha256s"]), 2)

    def test_corrupt_prior_reservation_evidence_fails_closed(self) -> None:
        corrupt = self.run_dir / "builder_attempts" / "corrupt"
        corrupt.mkdir(parents=True)
        (corrupt / "attempt.json").write_text("not-json", encoding="utf-8")
        builder = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module, "run_builder_process", side_effect=self.fake_process(stream=self.stream())
        ):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="corrupt reservation",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="corrupt_reservation",
                )
        self.assertEqual(context.exception.code, "agy_protocol_error")

    def test_all_supervisor_failure_classes_map_without_raw_diagnostics(self) -> None:
        cases = [
            ("spawn failed", "agy_spawn_failed"),
            ("cancelled", "agy_canceled"),
            ("output exceeded bounded evidence limit", "agy_output_incomplete"),
            ("malformed UTF-8", "agy_output_incomplete"),
            ("process boundary did not become quiescent", "agy_isolation_failed"),
            ("generic process failure", "agy_runtime_error"),
        ]
        for index, (message, code) in enumerate(cases):
            with self.subTest(code=code):
                builder = self.make_builder()
                process_error = BuilderProcessError(
                    f"{message}; secret-prompt-value",
                    stdout_path=self.root / f"stdout-{index}",
                    stderr_path=self.root / f"stderr-{index}",
                    failure_code=code,
                )
                with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
                    factory_module, "run_builder_process", side_effect=process_error
                ):
                    with self.assertRaises(BuilderFailure) as context:
                        builder.run(
                            worktree=self.candidate,
                            instruction="secret-prompt-value",
                            allowed_files=["allowed.py"],
                            config=self.config,
                            run_dir=self.run_dir,
                            label=f"process_{index}",
                        )
                self.assertEqual(context.exception.code, code)
                self.assertNotIn("secret-prompt-value", str(context.exception))

    def test_initial_process_evidence_write_failure_is_structured(self) -> None:
        builder = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module,
            "_write_builder_evidence",
            side_effect=OSError("evidence-write-secret"),
        ):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="initial evidence failure",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="evidence_write_failure",
                )
        self.assertEqual(context.exception.code, "agy_runtime_error")
        self.assertNotIn("evidence-write-secret", str(context.exception))
        attempt_path = Path(context.exception.evidence_path or "")
        self.assertTrue(attempt_path.is_file())
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        self.assertEqual(attempt["process_failure_code"], "agy_runtime_error")

    def test_real_supervisor_boundary_failure_overrides_timeout_cancel_and_overflow(self) -> None:
        env = os.environ.copy()
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
        cases = [
            (["sleep", "10"], "agy_timeout", None, None),
            (["sleep", "10"], "agy_canceled", threading.Event(), None),
            (["stderr-flood", "100000"], "agy_output_incomplete", None, 4096),
        ]
        for index, (fixture_args, primary_code, cancel, output_limit) in enumerate(cases):
            with self.subTest(primary_code=primary_code):
                stdout_path = self.root / f"real-boundary-{index}.stdout"
                stderr_path = self.root / f"real-boundary-{index}.stderr"
                timer = None
                if cancel is not None:
                    timer = threading.Timer(0.05, cancel.set)
                    timer.start()
                original_terminate = factory_module._terminate_builder_process
                calls = {"count": 0}

                def fail_first(process, job, timeout, *, process_group_id=None):
                    calls["count"] += 1
                    if calls["count"] == 1:
                        return False
                    return original_terminate(
                        process,
                        job,
                        timeout,
                        process_group_id=process_group_id,
                    )

                try:
                    with patch.object(factory_module, "BUILDER_SHUTDOWN_TIMEOUT_SECONDS", 0.2), patch.object(
                        factory_module, "_terminate_builder_process", side_effect=fail_first
                    ):
                        with self.assertRaises(BuilderProcessError) as context:
                            factory_module.run_builder_process(
                                [sys.executable, str(PROCESS_FIXTURE), *fixture_args],
                                cwd=self.candidate,
                                env=env,
                                timeout=0.15 if cancel is None and output_limit is None else 3,
                                stdout_path=stdout_path,
                                stderr_path=stderr_path,
                                cancel_event=cancel,
                                max_output_bytes=output_limit or factory_module.BUILDER_OUTPUT_LIMIT_BYTES,
                            )
                finally:
                    if timer is not None:
                        timer.cancel()
                        timer.join()
                self.assertEqual(context.exception.failure_code, "agy_isolation_failed")
                self.assertEqual(context.exception.secondary_failure_code, primary_code)
                self.assertTrue(stdout_path.exists())
                self.assertTrue(stderr_path.exists())

    def test_zero_exit_cli_timeout_and_partial_edit_are_fail_closed(self) -> None:
        timeout_builder = self.make_builder()
        timeout_stream = self.stream()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module,
            "run_builder_process",
            side_effect=self.fake_process(stream=timeout_stream, stderr="print timeout after 1s"),
        ):
            with self.assertRaises(BuilderFailure) as context:
                timeout_builder.run(
                    worktree=self.candidate,
                    instruction="timeout turn",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="cli_timeout",
                )
        self.assertEqual(context.exception.code, "agy_timeout")

        partial_builder = self.make_builder()
        error_stream = self.stream(status="ERROR", conversation_id="partial-error-id")

        def partial_process(argv, **kwargs):
            (self.candidate / "allowed.py").write_text("partial = True\n", encoding="utf-8")
            return self.fake_process(stream=error_stream)(argv, **kwargs)

        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module, "run_builder_process", side_effect=partial_process
        ):
            with self.assertRaises(BuilderFailure) as context:
                partial_builder.run(
                    worktree=self.candidate,
                    instruction="partial failure turn",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="partial_error",
                )
        self.assertEqual(context.exception.code, "agy_runtime_error")
        self.assertEqual((self.candidate / "allowed.py").read_text(encoding="utf-8"), "partial = True\n")

    def test_attempt_creation_and_finalization_failures_are_structured(self) -> None:
        builder = self.make_builder()
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            builder, "_builder_attempt_path", side_effect=OSError("disk secret")
        ):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="artifact creation",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="artifact_create",
                )
        self.assertEqual(context.exception.code, "agy_runtime_error")
        self.assertIsNone(context.exception.evidence_path)

        builder = self.make_builder()
        stream = self.stream()
        original_atomic = factory_module.atomic_json

        def fail_success_persist(path, value):
            if Path(path).name == "attempt.json" and value.get("status") == "SUCCESS":
                raise OSError("finalization secret")
            return original_atomic(path, value)

        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            factory_module, "run_builder_process", side_effect=self.fake_process(stream=stream)
        ), patch.object(factory_module, "atomic_json", side_effect=fail_success_persist):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="artifact finalization",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="artifact_finalize",
                )
        self.assertEqual(context.exception.code, "agy_runtime_error")
        self.assertIsNotNone(context.exception.evidence_path)

    def test_identity_change_after_process_is_structured(self) -> None:
        builder = self.make_builder()
        original = builder._recheck_identity
        calls = {"count": 0}

        def drift(path, digest):
            calls["count"] += 1
            if calls["count"] > 1:
                raise FactoryError("identity changed after process", "preflight")
            return original(path, digest)

        with patch.object(builder, "_recheck_identity", side_effect=drift), patch.object(
            factory_module, "APPROVED_AGY_SHA256", self.executable_hash
        ), patch.object(factory_module, "run_builder_process", side_effect=self.fake_process(stream=self.stream())):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="identity drift",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="identity_drift",
                )
        self.assertEqual(context.exception.code, "agy_identity_changed")

    def test_engine_builder_instruction_and_artifact_reference_are_backend_correct(self) -> None:
        engine = factory_module.FactoryEngine(builder=AgyBuilder(), role_client=object())
        plan = {
            "allowed_files": ["allowed.py"],
            "implementation_steps": ["Change the value"],
            "acceptance_criteria": ["The test passes"],
        }
        instruction = engine._builder_instruction(self.config, plan)
        self.assertIn("AGY is the direct Builder", instruction)
        self.assertNotIn("Aider is the Lean Builder", instruction)

        artifact = self.run_dir / "builder_attempts" / "artifact.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{}", encoding="utf-8")
        engine.builder.last_attempt_artifact = str(artifact)
        engine.builder.last_attempt_label = "artifact"
        engine.builder.last_attempt_run_root = self.run_dir.resolve()
        with self.assertRaises(BuilderFailure) as context:
            engine._builder_artifacts(self.run_dir, "artifact")
        self.assertEqual(context.exception.code, "agy_isolation_failed")

        valid_artifact = self.run_dir / "builder_attempts" / "artifact-uuid" / "attempt.json"
        valid_artifact.parent.mkdir(parents=True)
        valid_artifact.write_text("{}", encoding="utf-8")
        engine.builder.last_attempt_artifact = str(valid_artifact)
        self.assertEqual(engine._builder_artifacts(self.run_dir, "artifact"), [str(valid_artifact.resolve())])

    def test_default_engine_initial_and_repair_routes_record_existing_attempts(self) -> None:
        from test_factory_v2 import FakeRoles, make_repo

        def execute_route(root: Path, *, initial_bad: bool, reject_first: bool) -> tuple[dict[str, object], list[str], Path]:
            root.mkdir(parents=True, exist_ok=True)
            repo = make_repo(root)
            state_root = root / "state"
            executable = root / "agy.exe"
            executable.write_bytes(b"route fixture")
            roles = FakeRoles(reject_first=reject_first)

            def fake_preflight(builder, config, run_dir):
                return {
                    "executable": {
                        "path": str(executable.resolve()),
                        "sha256": "a" * 64,
                    }
                }

            labels: list[str] = []

            def fake_run(builder, *, worktree, instruction, allowed_files, config, run_dir, label):
                initial_count = sum(item == "builder_initial" for item in labels)
                labels.append(label)
                attempt_dir = run_dir / "builder_attempts" / f"{label}-route"
                attempt_dir.mkdir(parents=True, exist_ok=True)
                artifact = attempt_dir / "attempt.json"
                factory_module.atomic_json(artifact, {"status": "SUCCESS", "label": label})
                builder.last_attempt_artifact = str(artifact)
                builder.last_attempt_label = label
                builder.last_attempt_run_root = run_dir.resolve()
                value = 3 if initial_bad and label == "builder_initial" and initial_count == 0 else 2
                marker = (
                    f"# task {initial_count + 1}\n"
                    if label == "builder_initial" and initial_count
                    else ""
                )
                (worktree / "calc.py").write_text(
                    f"{marker}def value():\n    return {value}\n", encoding="utf-8"
                )

            config = factory_module.Config(
                repo=str(repo),
                request="make value return two",
                requested_files=["calc.py", "test_calc.py"],
                test_command=f'"{sys.executable}" -m unittest -q',
                max_debug_attempts=1,
                max_review_cycles=1 if reject_first else 0,
            )
            with patch.object(factory_module.AgyBuilder, "preflight", fake_preflight), patch.object(
                factory_module.AgyBuilder, "run", fake_run
            ):
                engine = factory_module.FactoryEngine(state_root=state_root, role_client=roles)
                identifier = engine.plan(config)
                state = engine.execute(identifier)
            return state, labels, state_root / str(state["run_id"])

        first_state, first_labels, first_run_dir = execute_route(self.root / "engine-debug", initial_bad=True, reject_first=False)
        self.assertEqual(first_state["phase"], "complete")
        self.assertEqual(
            first_labels,
            ["builder_initial", "builder_debug_1", "builder_initial", "builder_initial"],
        )
        first_events = json.loads((first_run_dir / "ledger" / "trajectory.json").read_text(encoding="utf-8"))["events"]
        first_builds = [event for event in first_events if event.get("phase") == "build"]
        self.assertEqual(len(first_builds), 4)
        for event in first_builds:
            self.assertEqual(len(event["artifacts"]), 1)
            self.assertTrue(Path(event["artifacts"][0]).is_file())

        second_state, second_labels, second_run_dir = execute_route(self.root / "engine-review", initial_bad=False, reject_first=True)
        self.assertEqual(second_state["phase"], "complete")
        self.assertEqual(
            second_labels,
            ["builder_initial", "builder_review_rework_1", "builder_initial", "builder_initial"],
        )
        second_events = json.loads((second_run_dir / "ledger" / "trajectory.json").read_text(encoding="utf-8"))["events"]
        second_builds = [event for event in second_events if event.get("phase") == "build"]
        self.assertEqual(len(second_builds), 4)
        for event in second_builds:
            self.assertEqual(len(event["artifacts"]), 1)
            self.assertTrue(Path(event["artifacts"][0]).is_file())

    def test_run_rejects_label_scope_and_artifact_escape(self) -> None:
        builder = self.make_builder()
        with self.assertRaises(BuilderFailure) as context:
            builder.run(
                worktree=self.candidate,
                instruction="bounded instruction",
                allowed_files=["allowed.py"],
                config=self.config,
                run_dir=self.run_dir,
                label="../escape",
            )
        self.assertEqual(context.exception.code, "agy_protocol_error")
        with self.assertRaises(BuilderFailure) as context:
            builder.run(
                worktree=self.candidate,
                instruction="bounded instruction",
                allowed_files=["allowed.py"],
                config=self.config,
                run_dir=self.candidate / "run",
                label="candidate_artifact",
            )
        self.assertEqual(context.exception.code, "agy_isolation_failed")

    def test_candidate_must_be_the_authorized_factory_worktree(self) -> None:
        arbitrary = self.root / "arbitrary-repository"
        arbitrary.mkdir()
        with self.assertRaises(BuilderFailure) as context:
            self.make_builder().run(
                worktree=arbitrary,
                instruction="bounded instruction",
                allowed_files=["allowed.py"],
                config=self.config,
                run_dir=self.run_dir,
                label="arbitrary_candidate",
            )
        self.assertEqual(context.exception.code, "agy_isolation_failed")

        ancestor = self.root / "ancestor"
        (ancestor / "worktree").mkdir(parents=True)
        with self.assertRaises(BuilderFailure) as context:
            self.make_builder().run(
                worktree=ancestor / "worktree",
                instruction="bounded instruction",
                allowed_files=["allowed.py"],
                config=self.config,
                run_dir=ancestor,
                label="ancestor_candidate",
            )
        self.assertEqual(context.exception.code, "agy_isolation_failed")

    def test_dirty_index_untracked_ignored_and_out_of_scope_baselines_fail_closed(self) -> None:
        for label in ("dirty_index", "untracked", "ignored", "out_of_scope"):
            with self.subTest(label=label):
                run_dir = self.root / label / "run"
                candidate = run_dir / "worktree"
                candidate.mkdir(parents=True)
                subprocess.run(["git", "init", "-q"], cwd=candidate, check=True)
                subprocess.run(["git", "config", "user.name", "Step 7 Test"], cwd=candidate, check=True)
                subprocess.run(["git", "config", "user.email", "step7@example.invalid"], cwd=candidate, check=True)
                (candidate / "allowed.py").write_text("value = 1\n", encoding="utf-8")
                if label == "ignored":
                    (candidate / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
                subprocess.run(["git", "add", "-A"], cwd=candidate, check=True)
                subprocess.run(["git", "commit", "-qm", "fixture"], cwd=candidate, check=True)
                head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=candidate, text=True).strip()
                factory_module.atomic_json(
                    run_dir / "run_state.json",
                    {
                        "schema_version": factory_module.SCHEMA_VERSION,
                        "run_config_version": factory_module.RUN_CONFIG_VERSION,
                        "builder_backend": "agy",
                        "builder_contract_version": factory_module.BUILDER_CONTRACT_VERSION,
                        "run_id": run_dir.name,
                        "worktree": str(candidate.resolve()),
                        "base_commit": head,
                        "branch": "hermes/task-step7-test",
                        "factory_worktree_authorized": True,
                        "boundary_test_fixture": True,
                        "candidate_git_common_dir": str((candidate / ".git").resolve()),
                    },
                )
                if label == "dirty_index":
                    (candidate / "allowed.py").write_text("dirty = True\n", encoding="utf-8")
                elif label == "untracked":
                    (candidate / "untracked.py").write_text("untracked = True\n", encoding="utf-8")
                elif label == "ignored":
                    (candidate / "ignored.py").write_text("ignored = True\n", encoding="utf-8")
                else:
                    (candidate / "forbidden.py").write_text("forbidden = True\n", encoding="utf-8")
                with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash):
                    with self.assertRaises(BuilderFailure) as context:
                        self.make_builder().run(
                            worktree=candidate,
                            instruction=f"{label} baseline",
                            allowed_files=["allowed.py"],
                            config=self.config,
                            run_dir=run_dir,
                            label=f"{label}_baseline",
                        )
                self.assertEqual(context.exception.code, "agy_isolation_failed")

    def test_disposable_candidate_mirror_syncs_only_allowed_files(self) -> None:
        mirror = self.root / "candidate-mirror"
        AgyBuilder._copy_sandbox_candidate(self.candidate, mirror)
        self.assertTrue((self.candidate / ".git").exists())
        self.assertFalse((mirror / ".git").exists())
        before = factory_module._snapshot_probe_tree(mirror)
        (mirror / "allowed.py").write_text("value = 2\n", encoding="utf-8")
        evidence = AgyBuilder._sync_sandbox_candidate(
            self.candidate,
            mirror,
            ["allowed.py"],
            before,
            stdout_path=self.root / "stdout",
            stderr_path=self.root / "stderr",
        )
        self.assertEqual((self.candidate / "allowed.py").read_text(encoding="utf-8"), "value = 2\n")
        self.assertFalse((self.candidate / "%SystemDrive%").exists())
        self.assertEqual(evidence["allowed_files_synchronized"], ["allowed.py"])
        self.assertEqual(evidence["unexpected_guest_change_count"], 0)

    def test_disposable_candidate_mirror_rejects_unexpected_guest_changes(self) -> None:
        mirror = self.root / "candidate-mirror-reject"
        AgyBuilder._copy_sandbox_candidate(self.candidate, mirror)
        before = factory_module._snapshot_probe_tree(mirror)
        (mirror / "forbidden.py").write_text("forbidden = True\n", encoding="utf-8")
        with self.assertRaises(BuilderProcessError) as context:
            AgyBuilder._sync_sandbox_candidate(
                self.candidate,
                mirror,
                ["allowed.py"],
                before,
                stdout_path=self.root / "stdout",
                stderr_path=self.root / "stderr",
            )
        self.assertEqual(context.exception.failure_code, "agy_isolation_failed")
        self.assertFalse((self.candidate / "forbidden.py").exists())

        runtime = mirror / "%SystemDrive%" / "ProgramData" / "Microsoft" / "Windows" / "Caches"
        runtime.mkdir(parents=True)
        (runtime / "cache.db").write_bytes(b"guest runtime cache")
        with self.assertRaises(BuilderProcessError) as context:
            AgyBuilder._sync_sandbox_candidate(
                self.candidate,
                mirror,
                ["allowed.py"],
                before,
                stdout_path=self.root / "stdout-runtime",
                stderr_path=self.root / "stderr-runtime",
            )
        self.assertEqual(context.exception.failure_code, "agy_isolation_failed")

    def test_disposable_candidate_sync_rolls_back_an_atomic_delta(self) -> None:
        second = self.candidate / "second.py"
        second.write_text("second = 1\n", encoding="utf-8")
        mirror = self.root / "candidate-mirror-rollback"
        AgyBuilder._copy_sandbox_candidate(self.candidate, mirror)
        before = factory_module._snapshot_probe_tree(mirror)
        (mirror / "allowed.py").write_text("value = 2\n", encoding="utf-8")
        (mirror / "second.py").write_text("second = 2\n", encoding="utf-8")
        original_replace = factory_module.os.replace
        calls = {"count": 0}

        def fail_second_replace(source, target):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("injected sync failure")
            return original_replace(source, target)

        with patch.object(factory_module.os, "replace", side_effect=fail_second_replace):
            with self.assertRaises(BuilderProcessError) as context:
                AgyBuilder._sync_sandbox_candidate(
                    self.candidate,
                    mirror,
                    ["allowed.py", "second.py"],
                    before,
                    stdout_path=self.root / "stdout-rollback",
                    stderr_path=self.root / "stderr-rollback",
                )
        self.assertEqual(context.exception.failure_code, "agy_isolation_failed")
        self.assertEqual((self.candidate / "allowed.py").read_text(encoding="utf-8"), "value = 1\n")
        self.assertEqual(second.read_text(encoding="utf-8"), "second = 1\n")

    def test_disposable_candidate_sync_rejects_concurrent_host_target_drift(self) -> None:
        second = self.candidate / "second.py"
        second.write_text("second = 1\n", encoding="utf-8")
        mirror = self.root / "candidate-mirror-concurrent"
        AgyBuilder._copy_sandbox_candidate(self.candidate, mirror)
        before = factory_module._snapshot_probe_tree(mirror)
        baseline = AgyBuilder._candidate_baseline_identity(self.candidate)
        (mirror / "allowed.py").write_text("value = 2\n", encoding="utf-8")
        (mirror / "second.py").write_text("second = 2\n", encoding="utf-8")
        original_replace = factory_module._replace_candidate_file
        calls = {"count": 0}

        def mutate_other_target(source, target, *, race_safe, expected_target=None, target_fd=None):
            calls["count"] += 1
            if calls["count"] == 1:
                second.write_text("concurrent-host\n", encoding="utf-8")
            return original_replace(
                source,
                target,
                race_safe=race_safe,
                expected_target=expected_target,
                target_fd=target_fd,
            )

        with patch.object(factory_module, "_replace_candidate_file", side_effect=mutate_other_target):
            with self.assertRaises(BuilderProcessError) as context:
                AgyBuilder._sync_sandbox_candidate(
                    self.candidate,
                    mirror,
                    ["allowed.py", "second.py"],
                    before,
                    baseline,
                    stdout_path=self.root / "stdout-concurrent",
                    stderr_path=self.root / "stderr-concurrent",
                )
        self.assertEqual(context.exception.failure_code, "agy_isolation_failed")
        self.assertEqual((self.candidate / "allowed.py").read_text(encoding="utf-8"), "value = 1\n")
        self.assertEqual(second.read_text(encoding="utf-8"), "concurrent-host\n")

    @unittest.skipUnless(os.name == "nt", "Windows Sandbox / exclusive locking is Windows-specific")
    def test_disposable_candidate_sync_blocks_same_target_writer_during_replace(self) -> None:
        mirror = self.root / "candidate-mirror-same-target-race"
        AgyBuilder._copy_sandbox_candidate(self.candidate, mirror)
        before = factory_module._snapshot_probe_tree(mirror)
        baseline = AgyBuilder._candidate_baseline_identity(self.candidate)
        (mirror / "allowed.py").write_text("value = 2\n", encoding="utf-8")
        original_replace = factory_module._replace_candidate_file
        attempted = {"value": False}

        def mutate_same_target(source, target, *, race_safe, expected_target=None, target_fd=None):
            attempted["value"] = True
            (self.candidate / "allowed.py").write_text("concurrent-host\n", encoding="utf-8")
            return original_replace(
                source,
                target,
                race_safe=race_safe,
                expected_target=expected_target,
                target_fd=target_fd,
            )

        with patch.object(factory_module, "_replace_candidate_file", side_effect=mutate_same_target):
            with self.assertRaises(BuilderProcessError) as context:
                AgyBuilder._sync_sandbox_candidate(
                    self.candidate,
                    mirror,
                    ["allowed.py"],
                    before,
                    baseline,
                    stdout_path=self.root / "stdout-same-target",
                    stderr_path=self.root / "stderr-same-target",
                )
        self.assertTrue(attempted["value"])
        self.assertEqual(context.exception.failure_code, "agy_isolation_failed")
        self.assertEqual((self.candidate / "allowed.py").read_text(encoding="utf-8"), "value = 1\n")

    def test_disposable_candidate_sync_atomically_creates_authorized_missing_file(self) -> None:
        mirror = self.root / "candidate-mirror-new-file"
        AgyBuilder._copy_sandbox_candidate(self.candidate, mirror)
        before = factory_module._snapshot_probe_tree(mirror)
        baseline = AgyBuilder._candidate_baseline_identity(self.candidate)
        (mirror / "new.py").write_text("created = True\n", encoding="utf-8")
        evidence = AgyBuilder._sync_sandbox_candidate(
            self.candidate,
            mirror,
            ["new.py"],
            before,
            baseline,
            stdout_path=self.root / "stdout-new-file",
            stderr_path=self.root / "stderr-new-file",
        )
        self.assertEqual((self.candidate / "new.py").read_text(encoding="utf-8"), "created = True\n")
        self.assertEqual(evidence["allowed_files_synchronized"], ["new.py"])

    def test_disposable_candidate_sync_rejects_host_creation_race_for_missing_file(self) -> None:
        mirror = self.root / "candidate-mirror-new-file-race"
        AgyBuilder._copy_sandbox_candidate(self.candidate, mirror)
        before = factory_module._snapshot_probe_tree(mirror)
        baseline = AgyBuilder._candidate_baseline_identity(self.candidate)
        (mirror / "new.py").write_text("created = True\n", encoding="utf-8")
        original_create = factory_module._replace_candidate_file
        attempted = {"value": False}

        def create_host_first(source, target, **kwargs):
            attempted["value"] = True
            target.write_text("host-created-first\n", encoding="utf-8")
            return original_create(source, target, **kwargs)

        with patch.object(factory_module, "_replace_candidate_file", side_effect=create_host_first):
            with self.assertRaises(BuilderProcessError) as context:
                AgyBuilder._sync_sandbox_candidate(
                    self.candidate,
                    mirror,
                    ["new.py"],
                    before,
                    baseline,
                    stdout_path=self.root / "stdout-new-file-race",
                    stderr_path=self.root / "stderr-new-file-race",
                )
        self.assertTrue(attempted["value"])
        self.assertEqual(context.exception.failure_code, "agy_isolation_failed")
        self.assertEqual((self.candidate / "new.py").read_text(encoding="utf-8"), "host-created-first\n")

    def test_disposable_candidate_sync_rejects_same_content_host_creation_race(self) -> None:
        mirror = self.root / "candidate-mirror-new-file-same-content-race"
        AgyBuilder._copy_sandbox_candidate(self.candidate, mirror)
        before = factory_module._snapshot_probe_tree(mirror)
        baseline = AgyBuilder._candidate_baseline_identity(self.candidate)
        desired = "created = True\n"
        (mirror / "new.py").write_text(desired, encoding="utf-8")
        original_create = factory_module._replace_candidate_file

        def create_same_content_host_first(source, target, **kwargs):
            target.write_text(desired, encoding="utf-8")
            return original_create(source, target, **kwargs)

        with patch.object(factory_module, "_replace_candidate_file", side_effect=create_same_content_host_first):
            with self.assertRaises(BuilderProcessError) as context:
                AgyBuilder._sync_sandbox_candidate(
                    self.candidate,
                    mirror,
                    ["new.py"],
                    before,
                    baseline,
                    stdout_path=self.root / "stdout-new-file-same-content-race",
                    stderr_path=self.root / "stderr-new-file-same-content-race",
                )
        self.assertEqual(context.exception.failure_code, "agy_isolation_failed")
        self.assertEqual((self.candidate / "new.py").read_text(encoding="utf-8"), desired)

    @unittest.skipUnless(os.name == "nt", "Windows Sandbox / exclusive locking is Windows-specific")
    def test_production_sandbox_config_maps_only_candidate_and_untrusted_output(self) -> None:
        auth_file = self.root / "auth" / "oauth.json"
        auth_file.parent.mkdir()
        auth_file.write_text("redacted test credential", encoding="utf-8")
        observed: dict[str, object] = {}
        valid_stream = make_stream(
            model=self.config.builder_model,
            cwd=r"C:\softfac-step7\candidate",
            conversation_id="sandbox-config-conversation",
        )

        def fake_outer(argv, **kwargs):
            command = argv[-1]
            match = re.search(r"-ArgumentList @\('((?:''|[^'])*)'\)", command)
            self.assertIsNotNone(match)
            config_path = Path(match.group(1).replace("''", "'"))
            config_text = config_path.read_text(encoding="utf-8")
            observed["config"] = config_text
            output_dir = config_path.parent / "output"
            output_dir.mkdir(exist_ok=True)
            (output_dir / "stdout.txt").write_bytes(valid_stream.encode("utf-8"))
            (output_dir / "stderr.txt").write_bytes(b"")
            (output_dir / "done.json").write_text(
                '{"schema_version":1,"exit_code":0,"error_type":null,"error_sha256":null}',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(argv, 0, "", "")

        builder = AgyBuilder(str(self.executable))
        with patch.object(builder, "_stage_windows_oauth_credential", return_value=auth_file), patch.object(
            factory_module, "run_builder_process", side_effect=fake_outer
        ):
            result, expected_cwd, evidence = builder._run_windows_sandbox_builder(
                path=self.executable,
                config=self.config,
                candidate=self.candidate,
                instruction="bounded 'quoted' instruction; $HOME must remain literal",
                stdout_path=self.run_dir / "outer.stdout",
                stderr_path=self.run_dir / "outer.stderr",
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(expected_cwd, r"C:\softfac-step7\candidate")
        self.assertEqual(evidence["boundary"], "Windows Sandbox")
        self.assertFalse(evidence["protected_roots_mapped"])
        config_text = str(observed["config"])
        self.assertIn("<ReadOnly>false</ReadOnly>", config_text)
        self.assertGreaterEqual(config_text.count("<ReadOnly>true</ReadOnly>"), 3)
        self.assertNotIn(str(self.candidate), config_text)
        self.assertIn("<SandboxFolder>C:\\softfac-step7\\candidate</SandboxFolder>", config_text)
        self.assertNotIn(str(self.source), config_text)
        self.assertNotIn(str(self.run_dir / "run_state.json"), config_text)

    def test_failed_sandbox_attempt_is_rejected_before_mirror_sync(self) -> None:
        for index, (stream, exit_code) in enumerate(
            [(self.stream(conversation_id="failed-process"), 7), ("not-json\n", 0)]
        ):
            with self.subTest(index=index):
                auth_file = self.root / f"auth-{index}" / "oauth.json"
                auth_file.parent.mkdir()
                auth_file.write_text("redacted test credential", encoding="utf-8")

                def fake_outer(argv, **kwargs):
                    command = argv[-1]
                    match = re.search(r"-ArgumentList @\('((?:''|[^'])*)'\)", command)
                    self.assertIsNotNone(match)
                    config_path = Path(match.group(1).replace("''", "'"))
                    output_dir = config_path.parent / "output"
                    output_dir.mkdir(exist_ok=True)
                    (config_path.parent / "candidate" / "allowed.py").write_text(
                        "failed-process-change\n", encoding="utf-8"
                    )
                    (output_dir / "stdout.txt").write_bytes(stream.encode("utf-8"))
                    (output_dir / "stderr.txt").write_bytes(b"")
                    (output_dir / "done.json").write_text(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "exit_code": exit_code,
                                "error_type": None,
                                "error_sha256": None,
                            }
                        ),
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(argv, 0, "", "")

                builder = AgyBuilder(str(self.executable))
                with patch.object(builder, "_stage_windows_oauth_credential", return_value=auth_file), patch.object(
                    factory_module, "run_builder_process", side_effect=fake_outer
                ):
                    with self.assertRaises(BuilderProcessError):
                        builder._run_windows_sandbox_builder(
                            path=self.executable,
                            config=self.config,
                            candidate=self.candidate,
                            instruction="failed attempt",
                            stdout_path=self.run_dir / f"failed-{index}.stdout",
                            stderr_path=self.run_dir / f"failed-{index}.stderr",
                        )
                self.assertEqual(
                    (self.candidate / "allowed.py").read_text(encoding="utf-8"),
                    "value = 1\n",
                )

    @unittest.skipUnless(os.name == "nt", "Windows Sandbox / exclusive locking is Windows-specific")
    def test_post_process_identity_failure_cannot_leave_sandbox_delta_in_candidate(self) -> None:
        auth_file = self.root / "auth-post-identity" / "oauth.json"
        auth_file.parent.mkdir()
        auth_file.write_text("redacted test credential", encoding="utf-8")
        valid_stream = make_stream(
            model=self.config.builder_model,
            cwd=r"C:\softfac-step7\candidate",
            conversation_id="post-identity-failure",
        )
        original_recheck = AgyBuilder._recheck_identity
        recheck_calls = {"count": 0}

        def fail_after_dispatch(path, digest):
            recheck_calls["count"] += 1
            if recheck_calls["count"] > 1:
                raise FactoryError("identity changed after process", "preflight")
            return original_recheck(builder, path, digest)

        def fake_outer(argv, **kwargs):
            command = argv[-1]
            match = re.search(r"-ArgumentList @\('((?:''|[^'])*)'\)", command)
            self.assertIsNotNone(match)
            config_path = Path(match.group(1).replace("''", "'"))
            output_dir = config_path.parent / "output"
            output_dir.mkdir(exist_ok=True)
            (config_path.parent / "candidate" / "allowed.py").write_text(
                "failed-post-identity\n", encoding="utf-8"
            )
            (output_dir / "stdout.txt").write_bytes(valid_stream.encode("utf-8"))
            (output_dir / "stderr.txt").write_bytes(b"")
            (output_dir / "done.json").write_text(
                '{"schema_version":1,"exit_code":0,"error_type":null,"error_sha256":null}',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(argv, 0, "", "")

        builder = AgyBuilder(str(self.executable))
        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            builder, "_stage_windows_oauth_credential", return_value=auth_file
        ), patch.object(builder, "_recheck_identity", side_effect=fail_after_dispatch), patch.object(
            factory_module, "run_builder_process", side_effect=fake_outer
        ):
            with self.assertRaises(BuilderFailure) as context:
                builder.run(
                    worktree=self.candidate,
                    instruction="post identity failure",
                    allowed_files=["allowed.py"],
                    config=self.config,
                    run_dir=self.run_dir,
                    label="post_identity_failure",
                )
        self.assertEqual(context.exception.code, "agy_identity_changed", context.exception.__dict__)
        self.assertEqual(
            (self.candidate / "allowed.py").read_text(encoding="utf-8"),
            "value = 1\n",
        )

    def test_sandbox_host_environment_keeps_case_insensitive_systemroot_only(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYSTEMROOT": r"C:\Windows",
                "AGY_WORKSPACE": r"C:\protected-workspace",
                "OPENAI_API_KEY": "host-secret",
            },
            clear=True,
        ):
            observed = AgyBuilder._sandbox_host_environment()
        self.assertEqual(observed, {"SYSTEMROOT": r"C:\Windows"})

    @unittest.skipUnless(os.name == "nt", "Windows Sandbox / exclusive locking is Windows-specific")
    def test_production_run_selects_sandbox_runner_and_attests_protected_state(self) -> None:
        builder = AgyBuilder(str(self.executable))
        stream = self.stream(conversation_id="production-route")
        called: dict[str, object] = {}

        def fake_sandbox(**kwargs):
            called.update(kwargs)
            return (
                subprocess.CompletedProcess([str(self.executable)], 0, stream, ""),
                str(self.candidate),
                {"boundary": "Windows Sandbox", "protected_roots_mapped": False},
            )

        with patch.object(factory_module, "APPROVED_AGY_SHA256", self.executable_hash), patch.object(
            builder, "_run_windows_sandbox_builder", side_effect=fake_sandbox
        ):
            builder.run(
                worktree=self.candidate,
                instruction="production route",
                allowed_files=["allowed.py"],
                config=self.config,
                run_dir=self.run_dir,
                label="production_route",
            )
        self.assertEqual(called["candidate"], self.candidate)
        self.assertEqual(called["config"], self.config)
        attempt = next((self.run_dir / "builder_attempts").glob("production_route-*/attempt.json"))
        data = json.loads(attempt.read_text(encoding="utf-8"))
        self.assertEqual(data["boundary"]["boundary"], "Windows Sandbox")
        self.assertFalse(data["boundary"]["protected_roots_mapped"])
        self.assertEqual(data["protected_host_before"], data["protected_host_after"])


if __name__ == "__main__":
    unittest.main()
