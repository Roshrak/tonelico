"""Deterministic exact-definition discovery tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from hermes_factory_v2 import (  # noqa: E402
    AgyBuilder,
    Config,
    FactoryEngine,
    discover_exact_python_definition,
)


class ExactDefinitionDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="exact-definition-")
        self.root = Path(self.temp.name)
        self.worktree = self.root / "repo"
        self.worktree.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, source: str) -> None:
        path = self.worktree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def discover(self, instruction: str, allowed: list[str] | None = None):
        return discover_exact_python_definition(
            self.worktree,
            instruction,
            allowed or ["lib/module.py"],
        )

    def test_module_and_async_definitions_are_exact(self):
        self.write(
            "lib/module.py",
            "def parse_agy_event_stream(raw):\n    return raw\n\n"
            "async def async_worker():\n    return 1\n",
        )
        result = self.discover("Fix parse_agy_event_stream JSON decode handling")
        self.assertEqual(result["status"], "UNIQUE")
        self.assertEqual(result["candidate"]["qualified_symbol"], "parse_agy_event_stream")
        self.assertEqual(result["candidate"]["node_kind"], "FunctionDef")
        async_result = self.discover("Fix async_worker")
        self.assertEqual(async_result["candidate"]["node_kind"], "AsyncFunctionDef")

    def test_classes_and_qualified_methods_are_exact(self):
        self.write(
            "lib/module.py",
            "class FactoryEngine:\n"
            "    def _select_builder_surface(self):\n        return None\n"
            "    async def async_step(self):\n        return None\n\n"
            "class Other:\n    def _select_builder_surface(self):\n        return None\n",
        )
        self.assertEqual(
            self.discover("Update FactoryEngine._select_builder_surface")["candidate"]["qualified_symbol"],
            "FactoryEngine._select_builder_surface",
        )
        self.assertEqual(
            self.discover("Update FactoryEngine.async_step")["candidate"]["node_kind"],
            "AsyncFunctionDef",
        )
        self.assertEqual(
            self.discover("Update FactoryEngine")["candidate"]["node_kind"],
            "ClassDef",
        )

    def test_production_helpers_are_found_without_an_explicit_path(self):
        source = (
            "class AgyBuilder:\n"
            "    def _validate_capsule_surface_delta(self):\n        return None\n"
            "    def _preflight_error_code(self):\n        return None\n\n"
            "def _classify_agy_diagnostic(value):\n    return value\n"
        )
        self.write("lib/production.py", source)
        allowed = ["lib/other.py", "lib/production.py"]
        for instruction, expected in (
            ("Fix _validate_capsule_surface_delta", "AgyBuilder._validate_capsule_surface_delta"),
            ("Fix _preflight_error_code", "AgyBuilder._preflight_error_code"),
            ("Fix _classify_agy_diagnostic", "_classify_agy_diagnostic"),
        ):
            with self.subTest(instruction=instruction):
                result = self.discover(instruction, allowed)
                self.assertEqual(result["status"], "UNIQUE")
                self.assertEqual(result["candidate"]["qualified_symbol"], expected)
                self.assertEqual(result["candidate"]["file_path"], "lib/production.py")

    def test_explicit_file_line_remains_level_one_input(self):
        self.assertEqual(
            FactoryEngine._navigation_line_hint(
                "Fix lib/module.py (line 123)", "lib/module.py"
            ),
            123,
        )

    def test_ambiguous_definitions_abstain(self):
        self.write("lib/one.py", "def duplicate_name():\n    return 1\n")
        self.write("lib/two.py", "def duplicate_name():\n    return 2\n")
        result = self.discover("Fix duplicate_name", ["lib/one.py", "lib/two.py"])
        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertIsNone(result["candidate"])
        self.assertEqual(len(result["candidates"]), 2)

        self.write(
            "lib/methods.py",
            "class First:\n    def run_task(self):\n        return 1\n\n"
            "class Second:\n    def run_task(self):\n        return 2\n",
        )
        result = self.discover("Fix run_task", ["lib/methods.py"])
        self.assertEqual(result["status"], "AMBIGUOUS")

    def test_conflicting_identifiers_resolve_all_then_abstain(self):
        self.write(
            "lib/conflicts.py",
            "def helper_function():\n    return 1\n\n"
            "def parse_result():\n    return 2\n\n"
            "class FactoryEngine:\n"
            "    def _select_builder_surface(self):\n        return None\n\n"
            "class BuilderFailure(Exception):\n    pass\n",
        )
        allowed = ["lib/conflicts.py"]
        for instruction in (
            "Fix helper_function when FactoryEngine._select_builder_surface fails",
            "Update parse_result because BuilderFailure is produced incorrectly",
            "FactoryEngine._select_builder_surface and BuilderFailure are both wrong",
        ):
            with self.subTest(instruction=instruction):
                result = self.discover(instruction, allowed)
                self.assertEqual(result["status"], "AMBIGUOUS")
                self.assertIsNone(result["candidate"])
                self.assertGreaterEqual(len(result["candidates"]), 2)

        same_target = self.discover(
            "Fix parse_result parse_result behavior", allowed
        )
        self.assertEqual(same_target["status"], "UNIQUE")
        self.assertEqual(same_target["candidate"]["qualified_symbol"], "parse_result")

    def test_calls_without_a_definition_and_nested_definitions_do_not_resolve(self):
        self.write(
            "lib/calls.py",
            "def caller():\n    return parse_agy_event_stream(data)\n\n"
            "def outer():\n"
            "    def nested_target():\n        return 1\n"
            "    return nested_target()\n",
        )
        self.assertEqual(
            self.discover("Fix parse_agy_event_stream", ["lib/calls.py"])["status"],
            "NOT_FOUND",
        )
        self.assertEqual(
            self.discover("Fix nested_target", ["lib/calls.py"])["status"],
            "NOT_FOUND",
        )

    def test_decorated_definitions_and_generic_tokens_are_safe(self):
        self.write(
            "lib/decorated.py",
            "@decorator\ndef decorated_target(value):\n    return value\n\n"
            "class FooBar:\n    pass\n",
        )
        result = self.discover("Fix decorated_target", ["lib/decorated.py"])
        self.assertEqual(result["status"], "UNIQUE")
        self.assertEqual(result["candidate"]["start_line"], 1)
        self.assertEqual(
            self.discover("Fix behavior handling", ["lib/decorated.py"])["status"],
            "NOT_FOUND",
        )
        self.assertEqual(
            self.discover("Fix agy_token_budget_exhausted", ["lib/decorated.py"])["status"],
            "NOT_FOUND",
        )
        self.assertEqual(
            self.discover("Fix FooBar", ["lib/decorated.py"])["candidate"]["node_kind"],
            "ClassDef",
        )

    def test_unique_definition_feeds_existing_capsule_selection(self):
        repo = self.worktree
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Definition Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "definition@example.invalid"], cwd=repo, check=True)
        self.write(
            "lib/module.py",
            "def parse_agy_event_stream(raw):\n    return raw\n\n"
            "def caller(raw):\n    return parse_agy_event_stream(raw)\n",
        )
        subprocess.run(["git", "add", "lib/module.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
        run_dir = self.root / "run"
        run_dir.mkdir()
        engine = FactoryEngine(
            state_root=self.root / "state",
            builder=AgyBuilder.__new__(AgyBuilder),
        )
        config = Config(
            repo=str(repo),
            request="discover parse_agy_event_stream",
            requested_files=["lib/module.py"],
            test_command="python -c pass",
        )
        surface = engine._select_builder_surface(
            worktree=repo,
            run_dir=run_dir,
            config=config,
            plan={"allowed_files": ["lib/module.py"], "task_id": "T1"},
            instruction="Fix parse_agy_event_stream JSON decode error handling",
            recovery_stage=1,
            attempt=1,
        )
        self.assertEqual(surface["kind"], "python_capsule")
        self.assertEqual(surface["target_symbols"], ["parse_agy_event_stream"])
        self.assertEqual(surface["capsule"]["source_path"], "lib/module.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
