"""Step 3 characterization tests for resume, budgets, trust, and step targets."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from hermes_factory_v2 import Config, FactoryEngine, FactoryError, MemoryLedger, atomic_json, validate_plan
import hermes_factory_v2 as factory_module
from test_factory_v2 import FakeBuilder, FakeRoles, ProgressingReviewBuilder, make_repo


class DispatchObservationBuilder:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state_at_dispatch: list[dict] = []

    def preflight(self, config, run_dir):
        atomic_json(run_dir / "preflight_builder.json", {"ok": True})
        return {"ok": True}

    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        initial_count = sum(item == "builder_initial" for item in self.calls)
        self.calls.append(label)
        self.state_at_dispatch.append(json.loads((run_dir / "run_state.json").read_text(encoding="utf-8")))
        marker = "" if not initial_count else f"# task {initial_count + 1}\n"
        (worktree / "calc.py").write_text(
            f"{marker}def value():\n    return 2\n", encoding="utf-8"
        )


class ResumeContractTests(unittest.TestCase):
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
            "max_debug_attempts": 1,
            "max_review_cycles": 1,
            "test_timeout": 30,
        }
        values.update(updates)
        return Config(**values)

    def test_resume_from_ambiguous_builder_dispatch_fails_closed_before_builder(self):
        roles = FakeRoles()
        builder = FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        run_dir = self.state_root / identifier
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        state.update({"phase": "building", "builder_dispatch": {"state": "dispatched", "label": "builder_initial"}})
        atomic_json(run_dir / "run_state.json", state)

        with self.assertRaisesRegex(FactoryError, "cannot be resumed safely") as ctx:
            engine.resume(identifier)

        self.assertEqual(ctx.exception.category, "state")
        self.assertEqual(builder.labels, [])
        self.assertFalse((run_dir / "worktree").exists())

    def test_resume_from_reviewing_fails_closed_without_replaying_builder(self):
        roles = FakeRoles()
        builder = FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        run_dir = self.state_root / identifier
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        state.update({"phase": "reviewing", "active_attempt_ref": None})
        atomic_json(run_dir / "run_state.json", state)

        with self.assertRaisesRegex(FactoryError, "resumable phase (has no current task|worktree is missing)"):
            engine.resume(identifier)

        self.assertEqual(builder.labels, [])
        self.assertEqual(engine.status(identifier)["phase"], "blocked")

    def test_debug_budget_zero_stops_before_repair_dispatch_and_preserves_failure(self):
        roles = FakeRoles()
        builder = FakeBuilder(initial_bad=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        cfg = self.config(max_debug_attempts=0, max_task_attempts=1)
        identifier = engine.plan(cfg)

        with self.assertRaisesRegex(FactoryError, "tests still fail"):
            engine.execute(identifier)

        state = engine.status(identifier)
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(builder.labels, ["builder_initial"])
        self.assertFalse(any(label.startswith("builder_debug_") for label in builder.labels))
        self.assertEqual(len(roles.reviewer_prompts), 0)
        self.assertGreaterEqual(len(state["test_results"]), 1)

    def test_builder_call_budget_reservation_is_observed_before_dispatch(self):
        """Characterize the pre-Step-10 baseline's missing durable reservation."""
        builder = DispatchObservationBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)

        self.assertEqual(state["phase"], "complete")
        self.assertEqual(builder.calls, ["builder_initial"] * 3)
        self.assertEqual(len(builder.state_at_dispatch), 3)
        dispatch_state = builder.state_at_dispatch[0]
        self.assertEqual(dispatch_state["phase"], "building")
        self.assertEqual(dispatch_state["current_task_attempts"], 1)
        final_state = json.loads((self.state_root / identifier / "run_state.json").read_text(encoding="utf-8"))
        self.assertEqual(final_state["current_task_attempts"], 1)

    def test_tampered_ledger_snapshot_is_detected_without_replacing_it(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        engine.execute(identifier)
        ledger_dir = self.state_root / identifier / "ledger"
        trajectory_path = ledger_dir / "trajectory.json"
        original = trajectory_path.read_bytes()
        trajectory = json.loads(original.decode("utf-8"))
        trajectory["sync_seq"] = trajectory["sync_seq"] + 100
        tampered = json.dumps(trajectory, indent=2).encode("utf-8")
        trajectory_path.write_bytes(tampered)

        consistent, reason = MemoryLedger.check_snapshot_consistency(ledger_dir)
        self.assertFalse(consistent)
        self.assertIn("snapshot sequence mismatch", reason)
        self.assertEqual(trajectory_path.read_bytes(), tampered)
        self.assertNotEqual(trajectory_path.read_bytes(), original)

    def test_tampered_review_artifact_blocks_terminal_fast_path(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        completed = engine.execute(identifier)
        review_ref = completed["criterion_evidence"]["G1"]["review_ref"]
        review_path = self.state_root / identifier / review_ref
        original = review_path.read_bytes()
        tampered = json.loads(original.decode("utf-8"))
        tampered["decision"] = "REJECT"
        tampered["required_changes"] = ["tampered review artifact"]
        review_path.write_text(json.dumps(tampered, indent=2), encoding="utf-8")

        observed = json.loads(review_path.read_text(encoding="utf-8"))
        self.assertEqual(observed["decision"], "REJECT")
        self.assertEqual(observed["required_changes"], ["tampered review artifact"])
        self.assertNotEqual(review_path.read_bytes(), original)
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.status(identifier)
        with self.assertRaisesRegex(FactoryError, "blocked run"):
            engine.resume(identifier)
        self.assertEqual(engine.status(identifier)["phase"], "blocked")
        self.assertEqual(json.loads(review_path.read_text(encoding="utf-8"))["decision"], "REJECT")

    def test_corrupted_complete_phase_is_revalidated_and_blocked(self):
        builder = FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=builder)
        identifier = engine.plan(self.config())
        run_dir = self.state_root / identifier
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        state["phase"] = "complete"
        atomic_json(run_dir / "run_state.json", state)
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.execute(identifier)
        self.assertEqual(engine.status(identifier)["phase"], "blocked")
        self.assertEqual(builder.labels, [])

    def test_tampered_verification_provenance_blocks_terminal_fast_path(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        completed = engine.execute(identifier)
        verification_ref = completed["criterion_evidence"]["G1"]["verification_ref"]
        verification_path = self.state_root / identifier / verification_ref
        value = json.loads(verification_path.read_text(encoding="utf-8"))
        value["returncode"] = 9
        value["command"] = "not-the-authorized-runner"
        value["passed"] = True
        verification_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.status(identifier)
        self.assertEqual(engine.status(identifier)["phase"], "blocked")

    def test_pending_commit_rejects_correlated_verification_and_review_tampering(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        original_command = factory_module.command
        interrupted = False

        def crash_before_commit(argv, *args, **kwargs):
            nonlocal interrupted
            if not interrupted and isinstance(argv, list) and argv[:2] == ["git", "commit-tree"]:
                interrupted = True
                raise KeyboardInterrupt("injected pending-commit interruption")
            return original_command(argv, *args, **kwargs)

        with patch.object(factory_module, "command", side_effect=crash_before_commit):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)

        run_dir = self.state_root / identifier
        state = engine.status(identifier)
        verification_path = run_dir / state["verification_ref"]
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        verification["command"] = "attacker-controlled-command"
        verification_path.write_text(json.dumps(verification), encoding="utf-8")
        review_path = run_dir / state["review_ref"]
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["verification"]["command"] = "attacker-controlled-command"
        review_path.write_text(json.dumps(review), encoding="utf-8")

        with self.assertRaisesRegex(FactoryError, "verification attestation digest is stale"):
            engine.resume(identifier)
        self.assertEqual(engine.status(identifier)["phase"], "blocked")

    def test_normal_commit_rejects_index_mutation_before_ref_advance(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        original_command = factory_module.command
        mutated = False

        def mutate_before_exact_commit(argv, *args, **kwargs):
            nonlocal mutated
            if not mutated and isinstance(argv, list) and argv[:2] == ["git", "commit-tree"]:
                mutated = True
                worktree = Path(kwargs["cwd"])
                (worktree / "calc.py").write_text(
                    "def value():\n    return 99\n", encoding="utf-8"
                )
                subprocess.run(["git", "add", "calc.py"], cwd=worktree, check=True)
            return original_command(argv, *args, **kwargs)

        with patch.object(factory_module, "command", side_effect=mutate_before_exact_commit):
            with self.assertRaisesRegex(FactoryError, "candidate index or base changed"):
                engine.execute(identifier)

        state = engine.status(identifier)
        self.assertTrue(mutated)
        self.assertEqual(state["phase"], "failed")
        self.assertEqual(state["completed_commits"], [])
        candidate = Path(state["worktree"])
        self.assertEqual(factory_module.git(candidate, "rev-parse", "HEAD").stdout.strip(), state["base_commit"])
        self.assertEqual(len(factory_module.git(candidate, "log", "--oneline").stdout.splitlines()), 1)

    def test_pending_reconciliation_rejects_index_mutation_before_ref_advance(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        original_command = factory_module.command
        commit_tree_calls = 0

        def crash_then_mutate(argv, *args, **kwargs):
            nonlocal commit_tree_calls
            if isinstance(argv, list) and argv[:2] == ["git", "commit-tree"]:
                commit_tree_calls += 1
                if commit_tree_calls == 1:
                    raise KeyboardInterrupt("injected pending commit interruption")
                worktree = Path(kwargs["cwd"])
                (worktree / "calc.py").write_text(
                    "def value():\n    return 98\n", encoding="utf-8"
                )
                subprocess.run(["git", "add", "calc.py"], cwd=worktree, check=True)
            return original_command(argv, *args, **kwargs)

        with patch.object(factory_module, "command", side_effect=crash_then_mutate):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
            interrupted = engine.status(identifier)
            candidate = Path(interrupted["worktree"])
            with self.assertRaisesRegex(FactoryError, "candidate index or base changed"):
                engine.resume(identifier)

        state = engine.status(identifier)
        self.assertEqual(commit_tree_calls, 2)
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["completed_commits"], [])
        self.assertEqual(factory_module.git(candidate, "rev-parse", "HEAD").stdout.strip(), interrupted["base_commit"])
        self.assertEqual(len(factory_module.git(candidate, "log", "--oneline").stdout.splitlines()), 1)

    def test_normal_commit_transaction_blocks_index_mutation_at_ref_update(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        original_command = factory_module.command
        attempted = False

        def mutate_at_ref_update(argv, *args, **kwargs):
            nonlocal attempted
            if (
                not attempted
                and isinstance(argv, list)
                and argv[:2] == ["git", "update-ref"]
                and len(argv) >= 5
            ):
                attempted = True
                worktree = Path(kwargs["cwd"])
                (worktree / "calc.py").write_text(
                    "def value():\n    return 97\n", encoding="utf-8"
                )
                mutation = subprocess.run(
                    ["git", "add", "calc.py"], cwd=worktree, capture_output=True, text=True, check=False
                )
                if mutation.returncode == 0:
                    raise AssertionError("candidate index mutation bypassed the transaction lock")
                raise FactoryError("candidate index mutation rejected by commit transaction lock", "hash")
            return original_command(argv, *args, **kwargs)

        with patch.object(factory_module, "command", side_effect=mutate_at_ref_update):
            with self.assertRaisesRegex(FactoryError, "transaction lock"):
                engine.execute(identifier)

        state = engine.status(identifier)
        self.assertTrue(attempted)
        self.assertEqual(state["phase"], "failed")
        self.assertEqual(state["completed_commits"], [])
        candidate = Path(state["worktree"])
        self.assertEqual(factory_module.git(candidate, "rev-parse", "HEAD").stdout.strip(), state["base_commit"])
        self.assertEqual(len(factory_module.git(candidate, "log", "--oneline").stdout.splitlines()), 1)

    def test_pending_transaction_blocks_index_mutation_at_ref_update(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        original_command = factory_module.command
        commit_tree_calls = 0
        attempted = False

        def crash_then_block_ref_mutation(argv, *args, **kwargs):
            nonlocal commit_tree_calls, attempted
            if isinstance(argv, list) and argv[:2] == ["git", "commit-tree"]:
                commit_tree_calls += 1
                if commit_tree_calls == 1:
                    raise KeyboardInterrupt("injected pending commit interruption")
            if (
                not attempted
                and isinstance(argv, list)
                and argv[:2] == ["git", "update-ref"]
                and len(argv) >= 5
            ):
                attempted = True
                worktree = Path(kwargs["cwd"])
                (worktree / "calc.py").write_text(
                    "def value():\n    return 96\n", encoding="utf-8"
                )
                mutation = subprocess.run(
                    ["git", "add", "calc.py"], cwd=worktree, capture_output=True, text=True, check=False
                )
                if mutation.returncode == 0:
                    raise AssertionError("candidate index mutation bypassed the transaction lock")
                raise FactoryError("candidate index mutation rejected by commit transaction lock", "hash")
            return original_command(argv, *args, **kwargs)

        with patch.object(factory_module, "command", side_effect=crash_then_block_ref_mutation):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
            interrupted = engine.status(identifier)
            candidate = Path(interrupted["worktree"])
            with self.assertRaisesRegex(FactoryError, "transaction lock"):
                engine.resume(identifier)

        state = engine.status(identifier)
        self.assertEqual(commit_tree_calls, 2)
        self.assertTrue(attempted)
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["completed_commits"], [])
        self.assertEqual(factory_module.git(candidate, "rev-parse", "HEAD").stdout.strip(), interrupted["base_commit"])
        self.assertEqual(len(factory_module.git(candidate, "log", "--oneline").stdout.splitlines()), 1)

    def test_valid_complete_status_revalidates_without_false_block(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        completed = engine.execute(identifier)
        self.assertEqual(completed["phase"], "complete")
        self.assertTrue(completed["verification_ref"].startswith("attestations/"))
        self.assertEqual(
            completed["verification_attestation_sha256"],
            completed["verification_ref"].split("/")[-1][:-5],
        )
        self.assertEqual(engine.status(identifier)["phase"], "complete")

    def test_canonical_verification_attestation_adversarial_matrix(self):
        mutations = (
            "sequence",
            "artifact_sequence",
            "command",
            "returncode",
            "passed",
            "result_artifact_ref",
            "result_artifact_sha256",
            "log_ref",
            "log_sha256",
            "log_contents",
            "sol_verification",
        )
        operations = ("execute", "resume", "status")
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=mutation):
                engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
                identifier = engine.plan(self.config(test_command=f'"{sys.executable}" -c "pass"'))
                completed = engine.execute(identifier)
                run_dir = self.state_root / identifier
                attestation_path = run_dir / completed["verification_ref"]
                attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
                if mutation == "log_contents":
                    (run_dir / attestation["log_ref"]).write_text("tampered log\n", encoding="utf-8")
                elif mutation == "sol_verification":
                    review_path = run_dir / completed["review_ref"]
                    review = json.loads(review_path.read_text(encoding="utf-8"))
                    review["verification"]["command"] = "tampered review verification"
                    review_path.write_text(json.dumps(review), encoding="utf-8")
                else:
                    attestation[mutation] = (
                        "tampered-command"
                        if mutation == "command"
                        else 987654
                        if mutation in {"sequence", "artifact_sequence"}
                        else 99
                        if mutation == "returncode"
                        else False
                        if mutation == "passed"
                        else "missing.json"
                        if mutation == "result_artifact_ref"
                        else "0" * 64
                    )
                    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
                operation = getattr(engine, operations[index % len(operations)])
                with self.assertRaisesRegex(FactoryError, "terminal state|verification attestation"):
                    operation(identifier)
                self.assertEqual(engine.status(identifier)["phase"], "blocked")

    def test_corrupted_retained_runner_snapshot_cannot_survive_terminal_state(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        engine.execute(identifier)
        state_path = self.state_root / identifier / "run_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["test_results"] = [
            {
                "sequence": 987654,
                "artifact_sequence": 987654,
                "command": "attacker-command",
                "returncode": 99,
                "passed": False,
                "log": "attacker.log",
                "log_sha256": "0" * 64,
                "artifact_sha256": "0" * 64,
            }
        ]
        atomic_json(state_path, state)
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.status(identifier)
        self.assertEqual(engine.status(identifier)["phase"], "blocked")

    def test_tampered_review_criterion_blocks_terminal_fast_path(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        identifier = engine.plan(self.config())
        completed = engine.execute(identifier)
        review_ref = completed["criterion_evidence"]["G1"]["review_ref"]
        review_path = self.state_root / identifier / review_ref
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["criteria"][0]["passed"] = False
        review_path.write_text(json.dumps(review), encoding="utf-8")
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.status(identifier)
        self.assertEqual(engine.status(identifier)["phase"], "blocked")

    def test_resume_reconciles_an_interrupted_exact_pending_commit(self):
        roles = FakeRoles()
        engine = FactoryEngine(
            state_root=self.state_root,
            role_client=roles,
            builder=FakeBuilder(),
        )
        identifier = engine.plan(self.config())
        original_command = factory_module.command
        crashed = False

        def crash_before_first_commit(argv, *args, **kwargs):
            nonlocal crashed
            if not crashed and isinstance(argv, list) and argv[:2] == ["git", "commit-tree"]:
                crashed = True
                raise KeyboardInterrupt("injected commit interruption")
            return original_command(argv, *args, **kwargs)

        with patch.object(factory_module, "command", side_effect=crash_before_first_commit):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)

        interrupted = engine.status(identifier)
        self.assertEqual(interrupted["phase"], "committing")
        self.assertEqual(interrupted["pending_commit"]["candidate_id"], interrupted["candidate_id"])

        resumed = engine.resume(identifier)
        self.assertEqual(resumed["phase"], "complete")
        self.assertEqual(len(resumed["completed_commits"]), 3)

    def test_resume_allows_progressing_review_repairs_until_task_budget(self):
        roles = FakeRoles(reject_always=True)
        builder = ProgressingReviewBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config(max_task_attempts=5)
        identifier = engine.plan(config)
        original_review = engine._review
        interrupted = {"value": False}

        def pause_before_first_recheck(*args, **kwargs):
            if kwargs.get("review_mode") == "FINDING_ONLY_RECHECK" and not interrupted["value"]:
                interrupted["value"] = True
                raise KeyboardInterrupt("pause before resumed finding-only review")
            return original_review(*args, **kwargs)

        with patch.object(engine, "_review", side_effect=pause_before_first_recheck):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
        paused = engine.status(identifier)
        self.assertEqual(paused["phase"], "reviewing")
        self.assertEqual(paused["current_task_attempts"], 2)
        self.assertEqual(len(paused["completed_commits"]), 0)

        with self.assertRaisesRegex(FactoryError, "resumed task attempt budget exhausted"):
            engine.resume(identifier)
        blocked = engine.status(identifier)
        self.assertEqual(blocked["phase"], "blocked")
        self.assertEqual(blocked["current_task_attempts"], 5)
        self.assertGreaterEqual(len(roles.review_hashes), 4)
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(roles.luna_invocation_count, 0)
        self.assertEqual(len(blocked["completed_commits"]), 0)

    def test_resume_rejects_post_commit_tracked_untracked_and_ignored_mutations(self):
        (self.repo / ".gitignore").write_text("ignored-after-commit.txt\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add ignored fixture"], cwd=self.repo, check=True)
        engine = FactoryEngine(
            state_root=self.state_root,
            role_client=FakeRoles(),
            builder=FakeBuilder(),
        )
        identifier = engine.plan(self.config())
        original_command = factory_module.command
        crashed = False

        def commit_then_mutate(argv, *args, **kwargs):
            nonlocal crashed
            if not crashed and isinstance(argv, list) and argv[:2] == ["git", "update-ref"]:
                crashed = True
                result = original_command(argv, *args, **kwargs)
                worktree = Path(kwargs["cwd"])
                (worktree / "calc.py").write_text("post-approval tracked mutation\n", encoding="utf-8")
                (worktree / "untracked-after-commit.txt").write_text("untracked\n", encoding="utf-8")
                (worktree / "ignored-after-commit.txt").write_text("ignored\n", encoding="utf-8")
                raise KeyboardInterrupt("injected after commit before state finalization")
            return original_command(argv, *args, **kwargs)

        with patch.object(factory_module, "command", side_effect=commit_then_mutate):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)

        with self.assertRaisesRegex(FactoryError, "post-approval|post-commit|scope violation"):
            engine.resume(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "blocked")
        self.assertNotEqual(state.get("phase"), "complete")

    def test_structured_steps_are_rejected_before_editable_file_sets_can_run(self):
        """Characterize the pre-Step-8 baseline limitation explicitly."""
        plan = {
            "objective": "characterize slices",
            "allowed_files": ["calc.py", "test_calc.py"],
            "implementation_steps": [
                {"step": "change implementation", "editable_files": ["calc.py"]},
                {"step": "change test", "editable_files": ["test_calc.py"]},
            ],
            "acceptance_criteria": ["both files are valid"],
            "recommended_tests": ["python3 -m unittest -q"],
            "risks": [],
        }
        with self.assertRaisesRegex(FactoryError, "implementation_steps must contain only non-empty strings") as ctx:
            validate_plan(plan, ["calc.py", "test_calc.py"])
        self.assertEqual(ctx.exception.category, "contract")

    def test_structured_step_editable_files_outside_plan_are_rejected(self):
        plan = {
            "objective": "characterize scope",
            "allowed_files": ["calc.py"],
            "implementation_steps": [{"step": "escape", "editable_files": ["outside.py"]}],
            "acceptance_criteria": ["never escapes"],
            "recommended_tests": ["python3 -m unittest -q"],
            "risks": [],
        }
        with self.assertRaisesRegex(FactoryError, "implementation_steps must contain only non-empty strings") as ctx:
            validate_plan(plan, ["calc.py"])
        self.assertEqual(ctx.exception.category, "contract")

    def test_failed_run_keeps_ledger_and_last_failure_event_for_resume_diagnostics(self):
        engine = FactoryEngine(
            state_root=self.state_root,
            role_client=FakeRoles(),
            builder=FakeBuilder(violate_scope=True),
        )
        identifier = engine.plan(self.config())
        with self.assertRaisesRegex(FactoryError, "scope violation"):
            engine.execute(identifier)

        ledger_dir = self.state_root / identifier / "ledger"
        trajectory = json.loads((ledger_dir / "trajectory.json").read_text(encoding="utf-8"))
        self.assertEqual(trajectory["events"][-1]["phase"], "failed")
        self.assertEqual(trajectory["events"][-1]["result"], "scope")
        self.assertTrue((self.state_root / identifier / "run_state.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
