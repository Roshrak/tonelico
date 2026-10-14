"""Step 4 tests for AGY configuration and historical state compatibility."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from hermes_factory_v2 import (
    Config,
    FactoryEngine,
    FactoryError,
    MemoryLedger,
    add_common,
    atomic_json,
    config_from_args,
    load_config_for_execution,
    load_prior_run_context,
    read_run_state,
)
from test_factory_v2 import FakeBuilder, FakeRoles, make_repo


class ConfigCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = make_repo(self.root)
        self.state_root = self.root / "state"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, **updates) -> Config:
        values = {
            "repo": str(self.repo),
            "request": "Make value return two",
            "requested_files": ["calc.py", "test_calc.py"],
            "test_command": "python3 -m unittest -q",
        }
        values.update(updates)
        return Config(**values)

    def parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        add_common(parser)
        return parser

    def test_default_and_explicit_agy_configuration_round_trip(self):
        default = self.config()
        self.assertEqual(default.builder_model, "gemini-3.8-flash-high")
        self.assertEqual(default.max_task_attempts, 12)
        self.assertEqual(default.agy_navigation_recovery, "adaptive")
        self.assertIsNone(default.agy_bin)
        self.assertFalse(hasattr(default, "bridge_url"))
        self.assertFalse(hasattr(default, "builder_architect_model"))

        args = self.parser().parse_args(
            [
                str(self.repo),
                "request",
                "--agy-bin",
                r"C:\Tools\agy.exe",
                "--builder-model",
                "gemini-3.8-flash-high",
                "--agy-navigation-recovery",
                "off",
            ]
        )
        explicit = config_from_args(args)
        self.assertEqual(explicit.agy_bin, r"C:\Tools\agy.exe")
        self.assertEqual(explicit.builder_model, "gemini-3.8-flash-high")
        self.assertEqual(explicit.agy_navigation_recovery, "off")
        self.assertEqual(dataclasses.asdict(Config(**dataclasses.asdict(explicit))), dataclasses.asdict(explicit))

    def test_removed_legacy_arguments_are_rejected_by_cli(self):
        for argument in ("--bridge-url", "--builder-architect-model", "--aider-bin"):
            with self.subTest(argument=argument):
                with self.assertRaises(SystemExit) as ctx:
                    self.parser().parse_args([str(self.repo), "request", argument, "value"])
                self.assertEqual(ctx.exception.code, 2)

    def test_obsolete_prefixed_model_and_invalid_integer_values_fail_closed(self):
        with self.assertRaisesRegex(FactoryError, "bare AGY model slug") as ctx:
            self.config(builder_model="openai/gemini-3.8-flash-high")
        self.assertEqual(ctx.exception.category, "config")

        invalid = [
            ("max_debug_attempts", True),
            ("max_debug_attempts", -1),
            ("max_review_cycles", 1.5),
            ("role_timeout", 0),
            ("builder_timeout", False),
            ("test_timeout", "900"),
        ]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                with self.assertRaises(FactoryError) as ctx:
                    self.config(**{field: value})
                self.assertEqual(ctx.exception.category, "config")

    def test_new_runs_record_versioned_agy_state(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config(agy_bin=r"C:\Tools\agy.exe"))
        state = read_run_state(self.state_root / identifier)
        self.assertEqual(state["run_config_version"], 2)
        self.assertEqual(state["builder_backend"], "agy")
        self.assertEqual(state["builder_contract_version"], 1)
        self.assertEqual(state["config"]["agy_bin"], r"C:\Tools\agy.exe")
        self.assertEqual(load_config_for_execution(state).agy_bin, r"C:\Tools\agy.exe")

    def test_historical_status_reads_legacy_state_without_constructing_current_config(self):
        run_dir = self.state_root / "legacy-run"
        run_dir.mkdir(parents=True)
        legacy = {
            "schema_version": 1,
            "phase": "failed",
            "run_id": "legacy-run",
            "config": {
                "repo": str(self.repo),
                "request": "historical request",
                "requested_files": ["calc.py"],
                "test_command": "python3 -m unittest -q",
                "builder_architect_model": "openai/old",
                "bridge_url": "http://127.0.0.1:8045/v1",
            },
            "unknown_historical_field": {"preserve": True},
        }
        atomic_json(run_dir / "run_state.json", legacy)
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())

        with patch("hermes_factory_v2.Config", side_effect=AssertionError("status constructed Config")):
            self.assertEqual(engine.status("legacy-run"), legacy)

        for entrypoint in (engine.execute, engine.resume):
            with self.subTest(entrypoint=entrypoint.__name__):
                with self.assertRaisesRegex(FactoryError, "legacy or unknown run configuration") as ctx:
                    entrypoint("legacy-run")
                self.assertEqual(ctx.exception.category, "state")

    def test_unknown_current_config_keys_and_contract_versions_fail_closed(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        run_dir = self.state_root / identifier
        state = read_run_state(run_dir)
        state["config"]["unknown_active_key"] = "must reject"
        atomic_json(run_dir / "run_state.json", state)
        with self.assertRaisesRegex(FactoryError, "unknown active keys") as ctx:
            engine.execute(identifier)
        self.assertEqual(ctx.exception.category, "state")

        state["config"].pop("unknown_active_key")
        state["run_config_version"] = 99
        atomic_json(run_dir / "run_state.json", state)
        with self.assertRaisesRegex(FactoryError, "legacy or unknown run configuration") as ctx:
            engine.execute(identifier)
        self.assertEqual(ctx.exception.category, "state")

    def test_unknown_execution_state_schema_rejected_for_execute_and_resume(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        run_dir = self.state_root / identifier
        state = read_run_state(run_dir)
        state["schema_version"] = 999
        atomic_json(run_dir / "run_state.json", state)

        for entrypoint in (engine.execute, engine.resume):
            with self.subTest(entrypoint=entrypoint.__name__):
                with self.assertRaisesRegex(FactoryError, "unsupported run state schema_version") as ctx:
                    entrypoint(identifier)
                self.assertEqual(ctx.exception.category, "state")

    def test_legacy_prior_run_remains_readable_as_historical_context(self):
        run_id = "legacy-history"
        run_dir = self.state_root / run_id
        run_dir.mkdir(parents=True)
        atomic_json(
            run_dir / "run_state.json",
            {
                "schema_version": 1,
                "phase": "failed",
                "run_id": run_id,
                "config": {
                    "repo": str(self.repo),
                    "request": "old request",
                    "requested_files": ["calc.py"],
                    "test_command": "python3 -m unittest -q",
                    "bridge_url": "http://127.0.0.1:8045/v1",
                },
            },
        )
        ledger = MemoryLedger(run_dir, run_id, str(self.repo), "repair")
        issue_id = ledger.record_or_update_issue(
            source="legacy",
            title="historical issue",
            description="kept for prior-run disclosure",
            status="open",
        )
        context = load_prior_run_context(self.state_root, self.repo, run_id)
        self.assertEqual(context["prior_run_id"], run_id)
        self.assertEqual(context["selected_issues"][0]["id"], issue_id)
        self.assertEqual(context["prior_root_objective_class"], "repair")


if __name__ == "__main__":
    unittest.main(verbosity=2)
