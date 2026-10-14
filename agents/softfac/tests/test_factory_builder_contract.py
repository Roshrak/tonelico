"""Step 3 characterization tests for the current Builder boundary."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from hermes_factory_v2 import Config, FactoryEngine, FactoryError, atomic_json
from test_factory_v2 import FakeRoles, make_repo


class BaseBuilderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = make_repo(self.root)
        self.state_root = self.root / "state"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, *, test_command: str | None = None) -> Config:
        return Config(
            repo=str(self.repo),
            request="Make value return two",
            requested_files=["calc.py", "test_calc.py"],
            test_command=test_command or "python3 -m unittest -q",
            max_debug_attempts=1,
            max_review_cycles=1,
            test_timeout=30,
        )

    def engine(self, builder, roles=None) -> FactoryEngine:
        return FactoryEngine(
            state_root=self.state_root,
            role_client=roles or FakeRoles(),
            builder=builder,
        )


class NoOpBuilder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def preflight(self, config, run_dir):
        atomic_json(run_dir / "preflight_builder.json", {"ok": True})
        return {"ok": True}

    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        initial_count = sum(item == "builder_initial" for item in self.calls)
        self.calls.append(label)
        if label == "builder_initial" and initial_count:
            (worktree / "calc.py").write_text(
                f"# task {initial_count + 1}\ndef value():\n    return 2\n",
                encoding="utf-8",
            )


class PartialFailureBuilder(NoOpBuilder):
    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        self.calls.append(label)
        (worktree / "calc.py").write_text("partial = True\n", encoding="utf-8")
        raise FactoryError("builder wrote a partial file and stopped", "builder")


class OutOfScopeFailureBuilder(NoOpBuilder):
    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        self.calls.append(label)
        (worktree / "forbidden.txt").write_text("out of scope\n", encoding="utf-8")
        (worktree / "calc.py").write_text("def value():\n    return 2\n", encoding="utf-8")
        raise FactoryError("builder failed after an out-of-scope write", "builder")


class IndexMutatingBuilder(NoOpBuilder):
    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        initial_count = sum(item == "builder_initial" for item in self.calls)
        self.calls.append(label)
        marker = "" if not initial_count else f"# task {initial_count + 1}\n"
        (worktree / "calc.py").write_text(
            f"{marker}def value():\n    return 2\n", encoding="utf-8"
        )
        result = subprocess.run(["git", "add", "--", "calc.py"], cwd=worktree, capture_output=True, text=True)
        self.assert_no_git_error(result)

    @staticmethod
    def assert_no_git_error(result) -> None:
        if result.returncode:
            raise AssertionError(result.stderr or result.stdout)


class HeadMutatingBuilder(NoOpBuilder):
    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        self.calls.append(label)
        (worktree / "calc.py").write_text("def value():\n    return 2\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "calc.py"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-qm", "builder-owned-commit"], cwd=worktree, check=True)


class IgnoredFileBuilder(NoOpBuilder):
    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        self.calls.append(label)
        (worktree / "calc.py").write_text("def value():\n    return 2\n", encoding="utf-8")
        (worktree / "ignored.out").write_text("hidden out-of-scope change\n", encoding="utf-8")


class BuilderContractTests(BaseBuilderContractTests):
    def test_empty_candidate_diff_stops_before_review_or_commit(self):
        builder = NoOpBuilder()
        roles = FakeRoles()
        engine = self.engine(builder, roles)
        identifier = engine.plan(
            self.config(test_command=f'"{sys.executable}" -c "exit(0)"')
        )

        with self.assertRaisesRegex(FactoryError, "no changes"):
            engine.execute(identifier)

        state = engine.status(identifier)
        self.assertEqual(state["phase"], "failed")
        self.assertEqual(state["error_category"], "builder")
        self.assertEqual(builder.calls, ["builder_initial"])
        self.assertEqual(roles.reviewer_prompts, [])
        self.assertNotIn("commit", state)

    def test_partial_write_then_builder_error_retains_failure_without_downstream_gates(self):
        builder = PartialFailureBuilder()
        roles = FakeRoles()
        engine = self.engine(builder, roles)
        identifier = engine.plan(self.config())

        with self.assertRaisesRegex(FactoryError, "partial file"):
            engine.execute(identifier)

        run_dir = self.state_root / identifier
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "failed")
        self.assertEqual(state["error_category"], "builder")
        self.assertEqual(builder.calls, ["builder_initial"])
        self.assertEqual(roles.reviewer_prompts, [])
        self.assertFalse((run_dir / "test_1.json").exists())
        self.assertTrue((run_dir / "ledger" / "trajectory.json").is_file())
        worktree = run_dir / "worktree"
        self.assertTrue(worktree.is_dir())
        self.assertEqual((worktree / "calc.py").read_text(encoding="utf-8"), "partial = True\n")

    def test_out_of_scope_write_and_builder_error_stop_before_review_or_commit(self):
        builder = OutOfScopeFailureBuilder()
        roles = FakeRoles()
        engine = self.engine(builder, roles)
        identifier = engine.plan(self.config())

        with self.assertRaisesRegex(FactoryError, "out-of-scope write"):
            engine.execute(identifier)

        run_dir = self.state_root / identifier
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "failed")
        self.assertEqual(state["error_category"], "builder")
        self.assertEqual(roles.reviewer_prompts, [])
        self.assertFalse((run_dir / "test_1.json").exists())
        self.assertTrue((run_dir / "worktree" / "forbidden.txt").is_file())
        self.assertFalse((self.repo / "forbidden.txt").exists())

    def test_builder_head_mutation_cannot_produce_a_task_commit(self):
        builder = HeadMutatingBuilder()
        roles = FakeRoles()
        engine = self.engine(builder, roles)
        identifier = engine.plan(self.config())

        with self.assertRaises(FactoryError) as ctx:
            engine.execute(identifier)

        state = engine.status(identifier)
        self.assertEqual(ctx.exception.category, "builder")
        self.assertEqual(state["phase"], "failed")
        self.assertNotIn("commit", state)
        self.assertEqual(roles.reviewer_prompts, [])

    def test_builder_index_mutation_is_characterized_before_future_git_guard(self):
        """Characterize that the pre-Step-9 baseline does not observe a staged index change."""
        builder = IndexMutatingBuilder()
        roles = FakeRoles()
        engine = self.engine(builder, roles)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)

        self.assertEqual(state["phase"], "complete")
        self.assertEqual(builder.calls, ["builder_initial"] * 3)
        self.assertEqual(len(roles.reviewer_prompts), 3)

    def test_zero_test_discovery_is_explicitly_characterized_before_provider_switch(self):
        """Characterize the current exit-zero/no-discovery gap for Step 12."""
        class CleanBuilder(NoOpBuilder):
            def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
                initial_count = sum(item == "builder_initial" for item in self.calls)
                self.calls.append(label)
                marker = "" if not initial_count else f"# task {initial_count + 1}\n"
                (worktree / "calc.py").write_text(
                    f"{marker}def value():\n    return 2\n", encoding="utf-8"
                )

        engine = self.engine(CleanBuilder())
        cfg = self.config(test_command=f'"{sys.executable}" -c "pass"')
        identifier = engine.plan(cfg)
        state = engine.execute(identifier)

        self.assertEqual(state["phase"], "complete")
        attestation = json.loads(
            (self.state_root / identifier / state["verification_ref"]).read_text(encoding="utf-8")
        )
        self.assertEqual(attestation["returncode"], 0)
        self.assertTrue(attestation["passed"])
        test_log = (self.state_root / identifier / attestation["log_ref"]).read_text(encoding="utf-8")
        self.assertNotIn("Ran ", test_log)

    def test_ignored_out_of_scope_file_is_in_changed_file_inventory(self):
        (self.repo / ".gitignore").write_text("*.ignored\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add ignored fixture"], cwd=self.repo, check=True)

        builder = IgnoredFileBuilder()
        engine = self.engine(builder)
        identifier = engine.plan(self.config())
        run_dir = self.state_root / identifier
        worktree = engine._create_worktree(
            run_dir,
            json.loads((run_dir / "run_state.json").read_text(encoding="utf-8")),
            self.config(),
        )
        (worktree / "ignored.ignored").write_text("ignored\n", encoding="utf-8")
        self.assertIn("ignored.ignored", engine._changed_files(worktree))


if __name__ == "__main__":
    unittest.main(verbosity=2)
