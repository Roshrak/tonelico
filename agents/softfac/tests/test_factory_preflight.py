"""Step 5 tests for AGY executable resolution and capability preflight."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import hermes_factory_v2 as factory_module

from hermes_factory_v2 import (
    AGY_REQUIRED_CAPABILITIES,
    AgyBuilder,
    Config,
    FactoryError,
    FactoryEngine,
    atomic_json,
    resolve_agy_executable,
)


HELP_TEXT = "\n".join(
    [
        "Usage of agy.exe:",
        *(
            (
                f"  {capability}                 "
                "Output format in print mode (text, json, stream-json)"
                if capability == "--output-format"
                else f"  {capability}"
            )
            for capability in AGY_REQUIRED_CAPABILITIES
        ),
    ]
)
MODEL_TEXT = (
    "Fetching available models...\n"
    "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
    "gemini-3.1-pro-high\tGemini 3.1 Pro (High)\n"
)
ACTIVE_PREFLIGHT_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "agy"
    / "1.2.2"
    / "preflight_evidence.json"
)


class CommandFixture:
    def __init__(
        self,
        *,
        model: str,
        version: str = factory_module.SUPPORTED_AGY_VERSION,
        help_text: str = HELP_TEXT,
        models_text: str = MODEL_TEXT,
        probe_stdout: str | None = None,
        probe_returncode: int = 0,
        probe_stderr: str = "",
        probe_model: str | None = None,
        probe_effective_cwd: Path | None = None,
        probe_result_conversation_id: str | None = None,
        probe_duplicate_result: bool = False,
        probe_order: str | None = None,
        probe_create_file: bool = False,
        probe_create_parent_file: bool = False,
        probe_tools: list[object] | None = None,
        probe_permission_mode: str = "always-proceed",
        probe_num_turns: int = 1,
        probe_duration_seconds: object = 0.1,
        probe_drop_result_keys: tuple[str, ...] = (),
    ) -> None:
        self.model = model
        self.version = version
        self.help_text = help_text
        self.models_text = models_text
        self.probe_stdout = probe_stdout
        self.probe_returncode = probe_returncode
        self.probe_stderr = probe_stderr
        self.probe_model = probe_model or model
        self.probe_effective_cwd = probe_effective_cwd
        self.probe_result_conversation_id = probe_result_conversation_id
        self.probe_duplicate_result = probe_duplicate_result
        self.probe_order = probe_order
        self.probe_create_file = probe_create_file
        self.probe_create_parent_file = probe_create_parent_file
        self.probe_tools = probe_tools
        self.probe_permission_mode = probe_permission_mode
        self.probe_num_turns = probe_num_turns
        self.probe_duration_seconds = probe_duration_seconds
        self.probe_drop_result_keys = probe_drop_result_keys
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        if len(argv) > 1 and argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, self.version + "\n", "")
        if len(argv) > 1 and argv[1] == "--help":
            return subprocess.CompletedProcess(argv, 0, self.help_text, "")
        if len(argv) > 1 and argv[1] == "models":
            return subprocess.CompletedProcess(argv, 0, self.models_text, "")
        if self.probe_stdout is None:
            probe_dir = Path(str(kwargs["cwd"])).resolve()
            self.probe_stdout = make_probe_stream(
                probe_dir,
                self.probe_model,
                effective_cwd=self.probe_effective_cwd,
                result_conversation_id=self.probe_result_conversation_id,
                duplicate_result=self.probe_duplicate_result,
                tools=self.probe_tools,
                permission_mode=self.probe_permission_mode,
                num_turns=self.probe_num_turns,
                duration_seconds=self.probe_duration_seconds,
                drop_result_keys=self.probe_drop_result_keys,
            )
            if self.probe_order:
                events = [json.loads(line) for line in self.probe_stdout.splitlines() if line.strip()]
                if self.probe_order == "result_before_init":
                    events = [events[-1], *events[:-1]]
                elif self.probe_order == "event_after_result":
                    events = [events[0], events[-1], *events[1:-1]]
                else:
                    raise AssertionError(f"unknown probe order: {self.probe_order}")
                self.probe_stdout = "\n".join(json.dumps(event) for event in events) + "\n"
            if self.probe_create_file:
                (probe_dir / "unexpected.txt").write_text("probe wrote a file\n", encoding="utf-8")
            if self.probe_create_parent_file:
                (probe_dir.parent.parent / "escaped.txt").write_text(
                    "probe escaped its private root\n",
                    encoding="utf-8",
                )
        return subprocess.CompletedProcess(
            argv,
            self.probe_returncode,
            self.probe_stdout,
            self.probe_stderr,
        )


def make_probe_stream(
    probe_dir: Path,
    model: str,
    *,
    effective_cwd: Path | None = None,
    result_status: str = "SUCCESS",
    response: str = "AGY_PREFLIGHT_OK",
    conversation_id: str = "fresh-preflight-conversation",
    result_conversation_id: str | None = None,
    duplicate_result: bool = False,
    tools: list[object] | None = None,
    permission_mode: str = "always-proceed",
    num_turns: int = 1,
    duration_seconds: object = 0.1,
    drop_result_keys: tuple[str, ...] = (),
) -> str:
    cwd = effective_cwd or probe_dir
    result_payload = {
        "conversation_id": result_conversation_id or conversation_id,
        "status": result_status,
        "response": response,
        "duration_seconds": duration_seconds,
        "num_turns": num_turns,
        "usage": {},
    }
    for key in drop_result_keys:
        result_payload.pop(key, None)
    result = {
        "event": "result",
        "result": result_payload,
    }
    events = [
        {
            "event": "init",
            "conversation_id": conversation_id,
            "init": {
                "model": model,
                "cwd": str(cwd),
                "tools": tools if tools is not None else ["terminal"],
                "permission_mode": permission_mode,
            },
        },
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": conversation_id,
                "step_index": 0,
                "state": "DONE",
                "step_type": "agent_response",
            },
        },
        result,
    ]
    if duplicate_result:
        events.append(result)
    return "\n".join(json.dumps(event) for event in events) + "\n"


def fixture_probe_runner(
    path: Path,
    config: Config,
    probe_dir: Path,
) -> dict[str, object]:
    prompt = "Reply with exactly AGY_PREFLIGHT_OK. Do not call tools and do not read or write any files."
    result = factory_module.command(
        [
            str(path),
            "--model",
            config.builder_model,
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--disable-slash-commands",
            "--print-timeout",
            "90s",
            "--print",
            prompt,
        ],
        cwd=probe_dir,
        timeout=min(max(config.builder_timeout, 1), 120),
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
    }


class AgyResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def executable(self, name: str = "agy.exe", make_executable: bool = True) -> Path:
        path = self.root / name
        path.write_bytes(b"native agy fixture")
        if make_executable:
            path.chmod(0o755)
        return path

    def test_explicit_path_wins_and_invalid_explicit_path_does_not_fall_back(self):
        explicit = self.executable()
        with patch("hermes_factory_v2.shutil.which", return_value=str(self.executable("path-agy.exe"))):
            self.assertEqual(resolve_agy_executable(str(explicit)), explicit.resolve())

        with patch("hermes_factory_v2.shutil.which", return_value=str(explicit)):
            with self.assertRaisesRegex(FactoryError, "not a valid file"):
                resolve_agy_executable(str(self.root / "missing.exe"))

    @unittest.skipUnless(os.name == "nt", "Windows LOCALAPPDATA fallback is Windows-specific")
    def test_path_then_windows_local_app_data_fallback(self):
        path_candidate = self.executable("path-agy.exe")
        with patch("hermes_factory_v2.shutil.which", return_value=str(path_candidate)):
            self.assertEqual(resolve_agy_executable(None), path_candidate.resolve())

        fallback = self.root / "agy" / "bin" / "agy.exe"
        fallback.parent.mkdir(parents=True)
        fallback.write_bytes(b"fallback agy fixture")
        fallback.chmod(0o755)
        with patch("hermes_factory_v2.shutil.which", return_value=None), patch(
            "hermes_factory_v2.os.name", "nt"
        ), patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}, clear=False):
            self.assertEqual(resolve_agy_executable(None), fallback.resolve())

    def test_directories_and_shell_shims_are_rejected(self):
        directory = self.root / "agy.exe"
        directory.mkdir()
        with self.assertRaisesRegex(FactoryError, "not a file"):
            resolve_agy_executable(str(directory))

        shim = self.executable("agy.cmd")
        with self.assertRaisesRegex(FactoryError, "unsupported shell shim"):
            resolve_agy_executable(str(shim))

        non_native = self.executable("agy.md", make_executable=False)
        with self.assertRaisesRegex(FactoryError, "native Windows executable" if os.name == "nt" else "not executable"):
            resolve_agy_executable(str(non_native))

    @unittest.skipUnless(os.name == "nt", "Windows LOCALAPPDATA fallback is Windows-specific")
    def test_windows_fallback_requires_local_app_data(self):
        with patch("hermes_factory_v2.shutil.which", return_value=None), patch(
            "hermes_factory_v2.os.name", "nt"
        ), patch.dict(os.environ, {"LOCALAPPDATA": ""}, clear=False):
            with self.assertRaisesRegex(FactoryError, "LOCALAPPDATA"):
                resolve_agy_executable(None)

    def test_factory_default_builder_is_direct_agy_after_step7(self):
        engine = FactoryEngine(state_root=self.root / "state", role_client=object(), builder=None)
        self.assertIsInstance(engine.builder, AgyBuilder)
        self.assertTrue(callable(getattr(engine.builder, "run", None)))


class AgyPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.executable = self.root / "agy.exe"
        self.executable.write_bytes(b"native agy fixture")
        self.executable.chmod(0o755)
        self.failure_number = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, **updates: object) -> Config:
        values: dict[str, object] = {
            "repo": str(self.root),
            "request": "preflight fixture",
            "requested_files": [],
            "test_command": None,
            "agy_bin": str(self.executable),
        }
        values.update(updates)
        return Config(**values)

    def run_preflight(
        self,
        fixture: CommandFixture,
        *,
        run_dir: Path | None = None,
        **config_updates: object,
    ) -> dict[str, object]:
        builder = AgyBuilder(str(self.executable), _probe_runner=fixture_probe_runner)
        approved_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        with patch("hermes_factory_v2.APPROVED_AGY_SHA256", approved_hash), patch(
            "hermes_factory_v2.command", side_effect=fixture
        ):
            return builder.preflight(self.config(**config_updates), run_dir or self.run_dir)

    def assert_preflight_rejected(self, fixture: CommandFixture, pattern: str) -> None:
        self.failure_number += 1
        failure_run_dir = self.root / f"failure-{self.failure_number}"
        failure_run_dir.mkdir()
        with self.assertRaisesRegex(FactoryError, pattern) as context:
            self.run_preflight(fixture, run_dir=failure_run_dir)
        self.assertEqual(context.exception.category, "preflight")
        failure_evidence = failure_run_dir / "preflight_builder.json"
        self.assertTrue(failure_evidence.exists())
        stored = json.loads(failure_evidence.read_text(encoding="utf-8"))
        self.assertEqual(stored["status"], "FAIL")
        self.assertEqual(stored["error_category"], "preflight")
        self.assertNotIn("stdout", stored)
        self.assertNotIn("stderr", stored)
        self.assertNotIn("GEMINI_API_KEY", json.dumps(stored))

    def test_success_records_pinned_identity_catalog_capabilities_and_probe(self):
        fixture = CommandFixture(model="gemini-3.8-flash-high")
        evidence = self.run_preflight(fixture)
        stored = json.loads((self.run_dir / "preflight_builder.json").read_text(encoding="utf-8"))
        expected_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()

        self.assertEqual(evidence, stored)
        self.assertEqual(stored["executable"]["path"], str(self.executable.resolve()))
        self.assertEqual(stored["executable"]["version"], factory_module.SUPPORTED_AGY_VERSION)
        self.assertEqual(stored["executable"]["sha256"], expected_hash)
        self.assertEqual(stored["model_catalog"]["requested_model"], "gemini-3.8-flash-high")
        self.assertEqual(stored["model_catalog"]["exact_entry"], "Gemini 3.8 Flash (High)")
        self.assertEqual(stored["capabilities"]["missing"], [])
        self.assertEqual(stored["probe"]["status"], "SUCCESS")
        self.assertEqual(stored["probe"]["effective_model"], "gemini-3.8-flash-high")
        self.assertEqual(stored["probe"]["disposable_files_created"], [])
        self.assertNotIn("GEMINI_API_KEY", json.dumps(stored))
        self.assertNotIn("sk-", json.dumps(stored))

        probe_argv, probe_kwargs = fixture.calls[-1]
        self.assertEqual(probe_argv[1:], [
            "--model",
            "gemini-3.8-flash-high",
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--disable-slash-commands",
            "--print-timeout",
            "90s",
            "--print",
            "Reply with exactly AGY_PREFLIGHT_OK. Do not call tools and do not read or write any files.",
        ])
        self.assertIsInstance(probe_kwargs["cwd"], Path)
        self.assertNotIn("--continue", probe_argv)
        self.assertNotIn("--conversation", probe_argv)
        self.assertNotIn("--project", probe_argv)

    def test_checked_in_windows_preflight_evidence_matches_windows_pin(self):
        evidence = json.loads(ACTIVE_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], 1)
        self.assertEqual(evidence["builder_backend"], "agy")
        self.assertEqual(evidence["executable"]["version"], factory_module.WINDOWS_AGY_VERSION)
        self.assertEqual(evidence["executable"]["sha256"], factory_module.WINDOWS_AGY_SHA256)
        self.assertEqual(evidence["model_catalog"]["requested_model"], factory_module.DEFAULT_BUILDER_MODEL)
        self.assertEqual(evidence["probe"]["boundary"], "Windows Sandbox")
        self.assertTrue(evidence["probe"]["host_attested"])
        self.assertEqual(evidence["probe"]["status"], "SUCCESS")
        self.assertEqual(evidence["probe"]["disposable_files_created"], [])

    def test_bannered_or_unsupported_versions_fail_closed(self):
        self.assert_preflight_rejected(
            CommandFixture(
                model="gemini-3.8-flash-high",
                version=f"agy version {factory_module.SUPPORTED_AGY_VERSION}",
            ),
            "bare semantic version",
        )
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", version="1.2.1"),
            "unsupported AGY version",
        )

    def test_missing_capability_fails_before_model_or_probe(self):
        help_text = HELP_TEXT.replace("--print-timeout", "")
        fixture = CommandFixture(model="gemini-3.8-flash-high", help_text=help_text)
        self.assert_preflight_rejected(fixture, "missing required capabilities")
        self.assertEqual(len(fixture.calls), 2)

    def test_help_parser_rejects_false_positive_tokens_and_wrong_output_format(self):
        embedded_only = "\n".join(
            f"prefix{capability}suffix" for capability in AGY_REQUIRED_CAPABILITIES
        ) + "\nprefix--output-formatsuffix stream-json"
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", help_text=embedded_only),
            "no parseable option declarations",
        )
        self.assert_preflight_rejected(
            CommandFixture(
                model="gemini-3.8-flash-high",
                help_text=HELP_TEXT.replace("stream-json", "ndjson"),
            ),
            "output-format=stream-json",
        )

    def test_malformed_or_missing_model_catalog_fails_closed(self):
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", models_text="not a catalog\n"),
            "malformed entry",
        )
        self.assert_preflight_rejected(
            CommandFixture(
                model="gemini-3.8-flash-high",
                models_text="gemini-3.1-pro-high\tGemini 3.1 Pro (High)\n",
            ),
            "does not contain",
        )

    def test_probe_nonzero_exit_and_error_result_fail_closed(self):
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", probe_returncode=1, probe_stderr="login required"),
            "capability probe failed",
        )
        def error_runner(
            path: Path,
            config: Config,
            probe_dir: Path,
        ) -> dict[str, object]:
            return {
                "returncode": 0,
                "stdout": make_probe_stream(
                    probe_dir,
                    config.builder_model,
                    result_status="ERROR",
                ),
                "stderr": "",
            }

        fixture = CommandFixture(model="gemini-3.8-flash-high")
        approved_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        with patch("hermes_factory_v2.APPROVED_AGY_SHA256", approved_hash), patch(
            "hermes_factory_v2.command", side_effect=fixture
        ):
            with self.assertRaisesRegex(FactoryError, "did not complete successfully"):
                AgyBuilder(
                    str(self.executable),
                    _probe_runner=error_runner,
                ).preflight(self.config(), self.run_dir)

    def test_unauthenticated_preflight_does_not_launch_a_browser(self):
        source = Path(__file__).resolve().parent.parent / "lib" / "hermes_factory_v2.py"
        source_text = source.read_text(encoding="utf-8")
        self.assertNotIn("webbrowser", source_text)
        self.assertNotIn("start https", source_text.lower())

    def test_wrong_model_cwd_conversation_and_duplicate_result_fail_closed(self):
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", probe_model="gemini-3.7-flash-high"),
            "wrong model",
        )
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", probe_effective_cwd=self.root / "wrong-cwd"),
            "wrong cwd",
        )
        self.assert_preflight_rejected(
            CommandFixture(
                model="gemini-3.8-flash-high",
                probe_result_conversation_id="stale-conversation",
            ),
            "stale conversation",
        )
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", probe_duplicate_result=True),
            "exactly one terminal result",
        )

    def test_probe_requires_init_first_and_result_last(self):
        self.assert_preflight_rejected(
            CommandFixture(
                model="gemini-3.8-flash-high",
                probe_order="result_before_init",
            ),
            "begin with init",
        )
        self.assert_preflight_rejected(
            CommandFixture(
                model="gemini-3.8-flash-high",
                probe_order="event_after_result",
            ),
            "result must be the final event",
        )

    def test_probe_requires_audited_field_types_and_completion_metadata(self):
        invalid_fixtures = [
            (
                CommandFixture(model="gemini-3.8-flash-high", probe_tools=[123]),
                "missing audited capability metadata",
            ),
            (
                CommandFixture(
                    model="gemini-3.8-flash-high",
                    probe_permission_mode="request-review",
                ),
                "unexpected permission mode",
            ),
            (
                CommandFixture(
                    model="gemini-3.8-flash-high",
                    probe_drop_result_keys=("usage",),
                ),
                "missing required fields",
            ),
            (
                CommandFixture(model="gemini-3.8-flash-high", probe_num_turns=0),
                "invalid completion metadata",
            ),
            (
                CommandFixture(
                    model="gemini-3.8-flash-high",
                    probe_duration_seconds="unknown",
                ),
                "invalid completion metadata",
            ),
        ]
        for fixture, pattern in invalid_fixtures:
            with self.subTest(pattern=pattern):
                self.assert_preflight_rejected(fixture, pattern)

    def test_probe_filesystem_mutation_fails_before_success_evidence(self):
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", probe_create_file=True),
            "mutated its disposable boundary",
        )
        self.assert_preflight_rejected(
            CommandFixture(model="gemini-3.8-flash-high", probe_create_parent_file=True),
            "mutated its disposable boundary",
        )

    def test_malformed_probe_stream_fails_closed(self):
        fixture = CommandFixture(model="gemini-3.8-flash-high", probe_stdout="not json\n")
        self.assert_preflight_rejected(fixture, "malformed stream JSON")

    def test_binary_identity_change_after_probe_is_rejected(self):
        fixture = CommandFixture(model="gemini-3.8-flash-high")
        original = fixture.__call__

        def mutate_after_models(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            result = original(argv, **kwargs)
            if len(argv) > 1 and argv[1] == "models":
                self.executable.write_bytes(b"changed agy fixture")
            return result

        with self.assertRaisesRegex(FactoryError, "identity changed"):
            approved_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()
            with patch("hermes_factory_v2.APPROVED_AGY_SHA256", approved_hash), patch(
                "hermes_factory_v2.command", side_effect=mutate_after_models
            ):
                AgyBuilder(str(self.executable), _probe_runner=fixture_probe_runner).preflight(
                    self.config(), self.run_dir
                )
        self.assertEqual(
            [argv[1] for argv, _ in fixture.calls],
            ["--version", "--help", "models"],
        )

    def test_pinned_identity_survives_a_new_builder_instance(self):
        config = self.config(agy_bin=None)
        fixture = CommandFixture(model="gemini-3.8-flash-high")
        approved_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        with patch("hermes_factory_v2.APPROVED_AGY_SHA256", approved_hash), patch(
            "hermes_factory_v2.shutil.which", return_value=str(self.executable)
        ), patch("hermes_factory_v2.command", side_effect=fixture):
            AgyBuilder(_probe_runner=fixture_probe_runner).preflight(config, self.run_dir)

        self.executable.write_bytes(b"changed after first process")
        with self.assertRaisesRegex(FactoryError, "identity changed"):
            with patch("hermes_factory_v2.shutil.which", return_value=str(self.executable)), patch(
                "hermes_factory_v2.APPROVED_AGY_SHA256", approved_hash
            ):
                AgyBuilder(_probe_runner=fixture_probe_runner).preflight(config, self.run_dir)
        original_evidence = json.loads(
            (self.run_dir / "preflight_builder.json").read_text(encoding="utf-8")
        )
        self.assertEqual(original_evidence["executable"]["sha256"], approved_hash)
        self.assertTrue((self.run_dir / "preflight_builder_failure.json").exists())

        with self.assertRaisesRegex(FactoryError, "since preflight_builder.json"):
            with patch("hermes_factory_v2.shutil.which", return_value=str(self.executable)), patch(
                "hermes_factory_v2.APPROVED_AGY_SHA256", approved_hash
            ):
                AgyBuilder(_probe_runner=fixture_probe_runner).preflight(config, self.run_dir)

    def test_same_version_but_unapproved_binary_is_rejected_before_invocation(self):
        fixture = CommandFixture(model="gemini-3.8-flash-high")
        failure_run_dir = self.root / "unapproved"
        failure_run_dir.mkdir()
        with self.assertRaisesRegex(FactoryError, "not an approved audited identity"):
            with patch("hermes_factory_v2.command", side_effect=fixture):
                AgyBuilder(
                    str(self.executable),
                    _probe_runner=fixture_probe_runner,
                ).preflight(self.config(), failure_run_dir)
        self.assertEqual(fixture.calls, [])

    def test_preflight_command_failures_are_preflight_and_persisted(self):
        def failing_command(argv: list[str], **kwargs: object) -> object:
            raise FactoryError("command timed out after 30s", "failed")

        approved_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        with self.assertRaisesRegex(FactoryError, "command timed out"):
            with patch("hermes_factory_v2.APPROVED_AGY_SHA256", approved_hash), patch(
                "hermes_factory_v2.command", side_effect=failing_command
            ):
                AgyBuilder(str(self.executable), _probe_runner=fixture_probe_runner).preflight(
                    self.config(), self.run_dir
                )
        self.assertEqual(
            json.loads((self.run_dir / "preflight_builder.json").read_text(encoding="utf-8"))[
                "status"
            ],
            "FAIL",
        )

    def test_failure_artifact_omits_raw_secret_diagnostics(self):
        builder = AgyBuilder(str(self.executable), _probe_runner=fixture_probe_runner)
        builder._write_preflight_failure(
            self.run_dir,
            "GEMINI_API_KEY=fixture-secret Bearer bearer-secret oauth_code=oauth-secret Cookie: cookie-secret",
        )
        stored = json.loads((self.run_dir / "preflight_builder.json").read_text(encoding="utf-8"))
        serialized = json.dumps(stored)
        for secret in ("fixture-secret", "bearer-secret", "oauth-secret", "cookie-secret"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(stored["error"], "preflight_failed")
        self.assertIn("failure_message_sha256", stored)

    def test_engine_persists_pinned_identity_in_run_state(self):
        executable = self.executable

        class Builder:
            def preflight(self, config: Config, run_dir: Path) -> dict[str, object]:
                return {
                    "executable": {
                        "path": str(executable.resolve()),
                        "sha256": "a" * 64,
                    }
                }

        class SmokeRoles:
            def call(self, *, role: str, **kwargs: object) -> dict[str, object]:
                if role in {"Luna", "Luna Debugger"}:
                    raise AssertionError("Luna is outside the v1 production path")
                return {"capability": "planner-reviewer", "schema_ok": True}

        state = {"phase": "initializing"}
        atomic_json(self.run_dir / "run_state.json", state)
        engine = FactoryEngine(
            state_root=self.root / "state",
            role_client=SmokeRoles(),
            builder=Builder(),
        )
        engine._capability_preflight(self.run_dir, state, self.config())
        persisted = json.loads((self.run_dir / "run_state.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["agy_executable_path"], str(self.executable.resolve()))
        self.assertEqual(persisted["agy_executable_sha256"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
