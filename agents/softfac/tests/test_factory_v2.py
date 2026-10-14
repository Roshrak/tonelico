#!/usr/bin/env python3
"""Offline integration tests for Hermes Software Factory v2."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/home/aesc/.local/lib")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from hermes_factory_v2 import (
    Config,
    FactoryEngine,
    FactoryError,
    HermesRoleClient,
    MemoryLedger,
    atomic_json,
    build_file_tree_skeleton,
    classify_objective,
    failure_signature,
    load_prior_run_context,
    make_review_evidence_packet,
    master_plan_tasks,
    parse_json_object,
    validate_master_plan,
    validate_review,
    validate_replan_reason,
    write_text,
)
import hermes_factory_v2 as factory_module


def cmd(argv: list[str], cwd: Path) -> str:
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    cmd(["git", "init", "-q"], repo)
    cmd(["git", "config", "user.name", "Factory Test"], repo)
    cmd(["git", "config", "user.email", "factory@example.invalid"], repo)
    (repo / "calc.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (repo / "test_calc.py").write_text(
        "import unittest\nfrom calc import value\n\n"
        "class CalcTest(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        self.assertEqual(value(), 2)\n\n"
        "if __name__ == '__main__':\n    unittest.main()\n",
        encoding="utf-8",
    )
    cmd(["git", "add", "calc.py", "test_calc.py"], repo)
    cmd(["git", "commit", "-qm", "initial"], repo)
    return repo


class FakeRoles:
    def __init__(self, *, reject_first: bool = False, reject_always: bool = False, bad_hash: bool = False, plan_files=None, replan_code: str | None = None, replan_codes: list[str] | None = None, generic_replan: bool = False) -> None:
        self.reject_first = reject_first
        self.reject_always = reject_always
        self.bad_hash = bad_hash
        self.plan_files = plan_files or ["calc.py", "test_calc.py"]
        self.replan_code = replan_code
        self.replan_codes = replan_codes or []
        self.generic_replan = generic_replan
        self.review_hashes: list[str] = []
        self.planner_prompt = ""
        self.reviewer_prompts: list[str] = []
        self.role_calls: list[str] = []
        self.model_calls: list[str] = []
        self.luna_invocation_count = 0
        self.astra_invocation_count = 0

    def call(self, *, role, provider, model, prompt, usage_path, output_path, timeout):
        self.role_calls.append(role)
        self.model_calls.append(model)
        if role in {"Luna", "Luna Debugger"}:
            self.luna_invocation_count += 1
            raise AssertionError("Luna is outside the v1 production path")
        atomic_json(
            usage_path,
            {"model": model, "provider": provider, "completed": True, "failed": False},
        )
        if role == "Sol":
            value = {"capability": "planner-reviewer", "schema_ok": True}
        elif role == "Astra Planner":
            self.astra_invocation_count += 1
            self.planner_prompt = prompt
            value = {
                "objective": "make value return two",
                "schema_version": 1,
                "request_ref": "request.json",
                "global_criteria": [{"id": "G1", "statement": "The unit test passes"}],
                "architecture_invariants": [{"id": "A1", "statement": "The source checkout remains unchanged"}],
                "assumptions": [{"id": "AS1", "statement": "The task repository is a Git worktree", "critical": True}],
                "non_goals": [],
                "milestones": [
                    {
                        "id": "M1",
                        "objective": "Implement the requested behavior",
                        "tasks": [
                            {
                                "id": "T1",
                                "objective": "Implement the first task slice",
                                "depends_on": [],
                                "editable_scope": self.plan_files,
                                "acceptance_criteria": ["The unit test passes"],
                                "verification_commands": ["python3 -m unittest -q"],
                                "preservation_constraints": [],
                                "global_criteria": ["G1"],
                            },
                            {
                                "id": "T2",
                                "objective": "Implement the second task slice",
                                "depends_on": ["T1"],
                                "editable_scope": self.plan_files,
                                "acceptance_criteria": ["The unit test passes"],
                                "verification_commands": ["python3 -m unittest -q"],
                                "preservation_constraints": [],
                                "global_criteria": ["G1"],
                            },
                            {
                                "id": "T3",
                                "objective": "Implement the third task slice",
                                "depends_on": ["T2"],
                                "editable_scope": self.plan_files,
                                "acceptance_criteria": ["The unit test passes"],
                                "verification_commands": ["python3 -m unittest -q"],
                                "preservation_constraints": [],
                                "global_criteria": ["G1"],
                            },
                        ],
                    }
                ],
            }
            request_ref = re.search(r'"authoritative_request_ref":\s*"([^"]+)"', prompt)
            if request_ref:
                value["request_ref"] = request_ref.group(1)
        elif role == "Sol Reviewer":
            self.reviewer_prompts.append(prompt)
            verification = json.loads(prompt.split("Input:\n", 1)[1])["verification"]
            match = re.search(r'"sha256":\s*"([0-9a-f]{64})"', prompt)
            if not match:
                raise AssertionError("review prompt omitted candidate hash")
            digest = match.group(1)
            base_match = re.search(r'"base_commit":\s*"([0-9a-f]{40})"', prompt)
            candidate_match = re.search(r'"candidate_id":\s*"([0-9a-f]{40})"', prompt)
            if not base_match or not candidate_match:
                raise AssertionError("review prompt omitted candidate identity")
            base_commit = base_match.group(1)
            candidate_id = candidate_match.group(1)
            acceptance_match = re.search(r'"id":\s*"([A-Za-z0-9][A-Za-z0-9_.-]*\.AC[0-9]+)"', prompt)
            acceptance_id = acceptance_match.group(1) if acceptance_match else "T1.AC1"
            self.review_hashes.append(digest)
            if self.bad_hash:
                digest = "0" * 64
            if self.reject_always or (self.reject_first and len(self.review_hashes) == 1):
                value = {
                    "decision": "REJECT",
                    "reviewed_diff_sha256": digest,
                    "base_commit": base_commit,
                    "candidate_id": candidate_id,
                    "verification": verification,
                    "criteria": [
                        {"criterion": "G1", "passed": False},
                        {"criterion": acceptance_id, "passed": False},
                    ],
                    "findings": ["Clarify the implementation"],
                    "required_changes": ["Add a short explanatory comment"],
                    "route": "builder",
                }
            else:
                value = {
                    "decision": "APPROVE",
                    "reviewed_diff_sha256": digest,
                    "base_commit": base_commit,
                    "candidate_id": candidate_id,
                    "verification": verification,
                    "criteria": [
                        {"criterion": "G1", "passed": True},
                        {"criterion": acceptance_id, "passed": True},
                    ],
                    "findings": [],
                    "required_changes": [],
                    "route": "none",
                }
            input_payload = json.loads(prompt.split("Input:\n", 1)[1])
            review_mode = input_payload.get("review_mode", "LARGE_STEP_REVIEW")
            target_ids = input_payload.get("target_finding_ids", [])
            value["review_mode"] = review_mode
            value["predecessor_review_ref"] = input_payload.get("predecessor_review_ref")
            value["target_finding_ids"] = list(target_ids)
            if review_mode == "LARGE_STEP_REVIEW":
                value["finding_records"] = [] if value["decision"] == "APPROVE" else [
                    {
                        "finding_id": f"T1-F001",
                        "status": "OPEN",
                        "criterion_ids": ["G1"],
                        "summary": "Clarify the implementation",
                        "evidence": "review evidence",
                        "required_correction": "Add a short explanatory comment",
                    }
                ]
            else:
                target_ids = list(target_ids)
                target_criteria = sorted(
                    {
                        criterion_id
                        for record in input_payload.get("prior_review_findings", [])
                        if isinstance(record, dict)
                        and record.get("finding_id") in target_ids
                        for criterion_id in record.get("criterion_ids", [])
                    }
                ) or ["G1"]
                value["criteria"] = [
                    {"criterion": criterion_id, "passed": True}
                    for criterion_id in target_criteria
                ]
                repair_delta_hash = hashlib.sha256(
                    str(input_payload.get("repair_delta") or "").encode("utf-8")
                ).hexdigest()
                prior_records = {
                    record.get("finding_id"): record
                    for record in input_payload.get("prior_review_findings", [])
                    if isinstance(record, dict)
                }
                value["finding_records"] = [
                    {
                        "finding_id": finding_id,
                        "status": "OPEN" if value["decision"] == "REJECT" else "RESOLVED",
                        "criterion_ids": prior_records.get(finding_id, {}).get("criterion_ids", ["G1"]),
                        "summary": prior_records.get(finding_id, {}).get("summary", "Clarify the implementation"),
                        "evidence": {
                            "repair_delta_sha256": repair_delta_hash,
                            "verification_ref": verification["attestation_ref"],
                            "observation": "repair",
                        },
                        "required_correction": prior_records.get(finding_id, {}).get("required_correction", "Add a short explanatory comment"),
                    }
                    for finding_id in target_ids
                ]
            active_replan_code = (
                self.replan_codes[len(self.review_hashes) - 1]
                if self.replan_codes and len(self.review_hashes) <= len(self.replan_codes)
                else self.replan_code if not self.replan_codes and len(self.review_hashes) == 1 else None
            )
            if active_replan_code:
                replan_contract = json.loads(prompt.split("Input:\n", 1)[1])["replan_reason_contract"]
                replan_evidence = dict(replan_contract["evidence_identity"])
                replan_evidence["kind"] = {
                    "ASSUMPTION_DISPROVED": "assumption",
                    "REQUIRED_GAP_UNCOVERED": "gap",
                    "ARCHITECTURE_DEPENDENCY_CONFLICT": "dependency_conflict",
                }[active_replan_code]
                replan_evidence["verified"] = True
                value["replan_reason"] = {
                    "code": active_replan_code,
                    "evidence": (
                        {"artifact_ref": "model-asserted.json", "kind": replan_evidence["kind"], "verified": True}
                        if self.generic_replan
                        else {
                            **replan_evidence,
                            **{
                                "ASSUMPTION_DISPROVED": {"assumption_id": "AS1"},
                                "REQUIRED_GAP_UNCOVERED": {"criterion_id": "G1"},
                                "ARCHITECTURE_DEPENDENCY_CONFLICT": {"dependency": "T1->T2"},
                            }[active_replan_code],
                        }
                    ),
                }
        else:
            raise AssertionError(f"unexpected role {role}")
        write_text(output_path, json.dumps(value))
        return value


class PrebindTamperingRoles(FakeRoles):
    def __init__(self, field: str) -> None:
        super().__init__()
        self.field = field

    def call(self, **kwargs):
        if kwargs["role"] == "Sol Reviewer":
            payload = json.loads(kwargs["prompt"].split("Input:\n", 1)[1])
            verification = payload["verification"]
            path = kwargs["output_path"].parent / verification["attestation_ref"]
            value = json.loads(path.read_text(encoding="utf-8"))
            if self.field == "log":
                (kwargs["output_path"].parent / value["log_ref"]).write_text(
                    "tampered Runner log\n", encoding="utf-8"
                )
            else:
                value[self.field] = "attacker-controlled-command" if self.field == "command" else 987654
                path.write_text(json.dumps(value), encoding="utf-8")
        return super().call(**kwargs)


class RecoveringRoles(FakeRoles):
    def __init__(self) -> None:
        super().__init__()
        self.sol_available = False

    def call(self, **kwargs):
        if kwargs["role"] == "Sol" and not self.sol_available:
            raise FactoryError("Sol temporarily unavailable", "provider")
        return super().call(**kwargs)


class FakeBuilder:
    def __init__(
        self,
        *,
        initial_bad: bool = False,
        always_bad: bool = False,
        violate_scope: bool = False,
        review_rework_bad: bool = False,
        replace_with_symlink: bool = False,
        syntax_error: bool = False,
        conflict_marker: bool = False,
    ) -> None:
        self.initial_bad = initial_bad
        self.always_bad = always_bad
        self.violate_scope = violate_scope
        self.review_rework_bad = review_rework_bad
        self.replace_with_symlink = replace_with_symlink
        self.syntax_error = syntax_error
        self.conflict_marker = conflict_marker
        self.labels: list[str] = []
        self.initial_task_count = 0

    def preflight(self, config, run_dir):
        atomic_json(run_dir / "preflight_builder.json", {"model": config.builder_model, "chat": True})
        return {"ok": True}

    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        self.labels.append(label)
        if label == "builder_initial":
            self.initial_task_count += 1
            if self.syntax_error:
                (worktree / "calc.py").write_text("def value():\n    return 2 +\n", encoding="utf-8")
            elif self.conflict_marker:
                (worktree / "calc.py").write_text("<<<<<<< HEAD\ndef value():\n    return 2\n=======\ndef value():\n    return 3\n>>>>>>>\n", encoding="utf-8")
            else:
                result = 3 if (self.initial_bad and self.initial_task_count == 1) or self.always_bad else 2
                marker = "" if self.initial_task_count == 1 else f"# task {self.initial_task_count}\n"
                (worktree / "calc.py").write_text(
                    f"{marker}def value():\n    return {result}\n", encoding="utf-8"
                )
            if self.violate_scope:
                (worktree / "forbidden.txt").write_text("out of scope\n", encoding="utf-8")
            if self.replace_with_symlink:
                (worktree / "calc.py").unlink()
                (worktree / "calc.py").symlink_to("test_calc.py")
        elif (
            label.startswith("builder_debug_")
            or label.startswith("builder_review_debug_")
            or label.startswith("builder_resume_verify_repair_")
        ):
            result = 3 if self.always_bad else 2
            (worktree / "calc.py").write_text(f"def value():\n    return {result}\n", encoding="utf-8")
        elif label.startswith("builder_review_rework_"):
            result = 3 if self.review_rework_bad else 2
            (worktree / "calc.py").write_text(
                f"def value():\n    # Reviewed behavior.\n    return {result}\n", encoding="utf-8"
            )


class ProgressingReviewBuilder(FakeBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.review_rework_count = 0

    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        super().run(
            worktree=worktree,
            instruction=instruction,
            allowed_files=allowed_files,
            config=config,
            run_dir=run_dir,
            label=label,
        )
        if label.startswith("builder_review_rework_"):
            self.review_rework_count += 1
            (worktree / "calc.py").write_text(
                f"# progressing review repair {self.review_rework_count}\n"
                "def value():\n    return 2\n",
                encoding="utf-8",
            )


class DistributedRoles(FakeRoles):
    def __init__(self, *, overlap: bool = False):
        super().__init__()
        self.overlap = overlap

    def call(self, *, role, provider, model, prompt, usage_path, output_path, timeout):
        if role == "Astra Planner":
            self.role_calls.append(role)
            self.model_calls.append(model)
            self.astra_invocation_count += 1
            value = {
                "objective": "implement three independent slices",
                "schema_version": 1,
                "request_ref": "request.json",
                "global_criteria": [
                    {"id": "G1", "statement": "slice one passes"},
                    {"id": "G2", "statement": "slice two passes"},
                    {"id": "G3", "statement": "slice three passes"},
                ],
                "architecture_invariants": [{"id": "A1", "statement": "source stays unchanged"}],
                "assumptions": [{"id": "AS1", "statement": "repository is Git", "critical": True}],
                "non_goals": [],
                "milestones": [{
                    "id": "M1", "objective": "independent slices", "tasks": [
                        {"id": "T1", "objective": "implement slice one", "depends_on": [],
                         "editable_scope": ["f1.py"], "acceptance_criteria": ["slice one works"],
                         "verification_commands": ["python3 -m unittest -q"],
                         "preservation_constraints": [], "global_criteria": ["G1"]},
                        {"id": "T2", "objective": "implement slice two", "depends_on": ["T1"],
                         "editable_scope": ["f1.py" if self.overlap else "f2.py"], "acceptance_criteria": ["slice two works"],
                         "verification_commands": ["python3 -m unittest -q"],
                         "preservation_constraints": [], "global_criteria": ["G2"]},
                        {"id": "T3", "objective": "implement slice three", "depends_on": ["T2"],
                         "editable_scope": ["f1.py" if self.overlap else "f3.py"], "acceptance_criteria": ["slice three works"],
                         "verification_commands": ["python3 -m unittest -q"],
                         "preservation_constraints": [], "global_criteria": ["G3"]},
                    ]
                }],
            }
            request_ref = re.search(r'"authoritative_request_ref":\s*"([^"]+)"', prompt)
            if request_ref:
                value["request_ref"] = request_ref.group(1)
            atomic_json(usage_path, {"model": model, "completed": True, "failed": False})
            write_text(output_path, json.dumps(value))
            return value
        if role == "Sol Reviewer":
            self.role_calls.append(role)
            self.model_calls.append(model)
            self.reviewer_prompts.append(prompt)
            verification = json.loads(prompt.split("Input:\n", 1)[1])["verification"]
            digest = re.search(r'"sha256":\s*"([0-9a-f]{64})"', prompt).group(1)
            base_commit = re.search(r'"base_commit":\s*"([0-9a-f]{40})"', prompt).group(1)
            candidate_id = re.search(r'"candidate_id":\s*"([0-9a-f]{40})"', prompt).group(1)
            global_match = re.search(r'"global_criteria_ids":\s*\[(.*?)\]', prompt, re.S)
            global_ids = re.findall(r'"([^"]+)"', global_match.group(1))
            acceptance_id = re.search(r'"acceptance_criteria_ids":\s*\[\s*"([^"]+)"', prompt).group(1)
            value = {
                "decision": "APPROVE", "reviewed_diff_sha256": digest,
                "base_commit": base_commit, "candidate_id": candidate_id,
                "verification": verification,
                "criteria": [
                    *({"criterion": item, "passed": True} for item in global_ids),
                    {"criterion": acceptance_id, "passed": True},
                ],
                "findings": [], "required_changes": [], "route": "none",
            }
            atomic_json(usage_path, {"model": model, "completed": True, "failed": False})
            write_text(output_path, json.dumps(value))
            return value
        return super().call(role=role, provider=provider, model=model, prompt=prompt,
                            usage_path=usage_path, output_path=output_path, timeout=timeout)


class DistributedBuilder(FakeBuilder):
    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        self.labels.append(label)
        if label == "builder_initial":
            index = self.initial_task_count + 1
            self.initial_task_count = index
            (worktree / allowed_files[0]).write_text(
                f"def slice_value():\n    return {index}\n", encoding="utf-8"
            )


class RewritingAstraRoles(FakeRoles):
    def call(self, *, role, provider, model, prompt, usage_path, output_path, timeout):
        value = super().call(
            role=role,
            provider=provider,
            model=model,
            prompt=prompt,
            usage_path=usage_path,
            output_path=output_path,
            timeout=timeout,
        )
        if role == "Astra Planner" and self.astra_invocation_count > 1:
            value = json.loads(json.dumps(value))
            value["milestones"][0]["tasks"][0]["objective"] = "rewrite completed task"
            return value
        return value


class ActiveTaskReplacementRoles(FakeRoles):
    def call(self, *, role, provider, model, prompt, usage_path, output_path, timeout):
        value = super().call(
            role=role,
            provider=provider,
            model=model,
            prompt=prompt,
            usage_path=usage_path,
            output_path=output_path,
            timeout=timeout,
        )
        if role == "Astra Planner" and self.astra_invocation_count > 1:
            value = json.loads(json.dumps(value))
            task = value["milestones"][0]["tasks"][0]
            task["objective"] = "implement the revised active contract"
            task["acceptance_criteria"] = ["the revised active contract passes"]
            value["global_criteria"][0]["statement"] = "the revised active requirement passes"
        return value


class ScopeChangingRoles(FakeRoles):
    def call(self, *, role, provider, model, prompt, usage_path, output_path, timeout):
        value = super().call(
            role=role,
            provider=provider,
            model=model,
            prompt=prompt,
            usage_path=usage_path,
            output_path=output_path,
            timeout=timeout,
        )
        if role == "Astra Planner" and self.astra_invocation_count > 1:
            value = json.loads(json.dumps(value))
            for task in value["milestones"][0]["tasks"]:
                task["editable_scope"] = ["new.py"]
            value["objective"] = "the replacement user objective"
            request_ref = re.search(r'"authoritative_request_ref":\s*"([^"]+)"', prompt)
            if request_ref:
                value["request_ref"] = request_ref.group(1)
        return value


class TargetPlanRoles(FakeRoles):
    def call(self, *, role, provider, model, prompt, usage_path, output_path, timeout):
        value = super().call(
            role=role,
            provider=provider,
            model=model,
            prompt=prompt,
            usage_path=usage_path,
            output_path=output_path,
            timeout=timeout,
        )
        if role == "Astra Planner":
            value = json.loads(json.dumps(value))
            for task in value["milestones"][0]["tasks"]:
                task["objective"] = "change function value"
        return value


class NoPatchThenCapsuleBuilder(factory_module.AgyBuilder):
    def __init__(self, normal_failure_code=None):
        super().__init__()
        self.calls: list[tuple[str, str]] = []
        self.normal_failure_code = normal_failure_code

    def preflight(self, config, run_dir):
        atomic_json(run_dir / "preflight_builder.json", {"ok": True})
        return {"ok": True}

    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label, surface=None):
        surface = surface or {"kind": "normal"}
        self.calls.append((label, surface.get("kind", "normal")))
        attempt_dir = run_dir / "builder_attempts" / f"{label}-{len(self.calls)}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        artifact = attempt_dir / "attempt.json"
        atomic_json(artifact, {"status": "SUCCESS", "label": label})
        self.last_attempt_artifact = str(artifact)
        self.last_attempt_label = label
        self.last_attempt_run_root = run_dir.resolve()
        if surface.get("kind") == "normal":
            self.last_attempt_outcome = "NO_PATCH"
            if self.normal_failure_code:
                raise factory_module.BuilderFailure(
                    "explicit fixture diagnostic",
                    code=self.normal_failure_code,
                    non_resumable=True,
                )
            return
        capsule = surface["capsule"]
        source_path = worktree / Path(capsule["source_path"])
        original = source_path.read_text(encoding="utf-8")
        capsule_source = surface["capsule_source"]
        if "return 1" in capsule_source:
            edited = capsule_source.replace("return 1", "return 2")
        else:
            edited = capsule_source.replace("return 2", "# localized repair\n    return 2", 1)
        source_path.write_text(
            factory_module.reintegrate_python_capsule(capsule, original, edited),
            encoding="utf-8",
        )
        self.last_attempt_outcome = "SUCCESS"


class ScopeChangingBuilder(FakeBuilder):
    def run(self, *, worktree, instruction, allowed_files, config, run_dir, label):
        self.labels.append(label)
        if label == "builder_initial":
            (worktree / allowed_files[0]).write_text(
                f"replacement = {self.labels.count('builder_initial')}\n", encoding="utf-8"
            )


class MultiReplanRoles(FakeRoles):
    def call(self, *, role, provider, model, prompt, usage_path, output_path, timeout):
        value = super().call(
            role=role,
            provider=provider,
            model=model,
            prompt=prompt,
            usage_path=usage_path,
            output_path=output_path,
            timeout=timeout,
        )
        if role == "Astra Planner" and self.astra_invocation_count == 3:
            value = json.loads(json.dumps(value))
            request_ref = re.search(r'"authoritative_request_ref":\s*"([^"]+)"', prompt)
            if request_ref:
                value["request_ref"] = request_ref.group(1)
            for task in value["milestones"][0]["tasks"]:
                if task["id"] != "T1":
                    task["editable_scope"] = ["new.py"]
            value["objective"] = "the replacement user objective"
        return value


class HermesThenUserRoles(FakeRoles):
    def call(self, *, role, provider, model, prompt, usage_path, output_path, timeout):
        value = super().call(
            role=role,
            provider=provider,
            model=model,
            prompt=prompt,
            usage_path=usage_path,
            output_path=output_path,
            timeout=timeout,
        )
        if role == "Astra Planner" and self.astra_invocation_count == 3:
            value = json.loads(json.dumps(value))
            request_ref = re.search(r'"authoritative_request_ref":\s*"([^"]+)"', prompt)
            if request_ref:
                value["request_ref"] = request_ref.group(1)
            for task in value["milestones"][0]["tasks"]:
                if task["id"] == "T3":
                    task["editable_scope"] = ["new.py"]
            value["objective"] = "the replacement user objective"
        return value


class FactoryIntegrationTests(unittest.TestCase):
    def test_json_parser_accepts_fenced_nested_objects(self):
        result = parse_json_object(
            '```json\n{"criteria":[{"criterion":"tests","passed":true}]}\n```'
        )
        self.assertEqual(result["criteria"][0]["criterion"], "tests")

    def test_review_protocol_has_stable_findings_and_single_candidate_authority(self):
        packet = make_review_evidence_packet(
            diff_text="diff --git a/calc.py b/calc.py\n",
            digest="a" * 64,
            base_commit="b" * 40,
            candidate_id="c" * 40,
            changed=["calc.py"],
            candidate_source_context={"files": {"calc.py": {"content": "return 2"}}},
            tests=[{"passed": True}],
            plan={"allowed_files": ["calc.py"], "acceptance_criteria": [], "global_criteria": []},
            sequence=1,
            review_mode="FINDING_ONLY_RECHECK",
            predecessor_review_ref="sol_review_1.json",
            target_finding_ids=["T1-F001"],
            repair_delta="small repair delta",
        )
        self.assertEqual(packet["candidate_authority"]["candidate_id_source"], "host git write-tree")
        self.assertEqual(packet["candidate_authority"]["reviewed_diff_sha256_role"], "diagnostic evidence only")
        self.assertEqual(packet["candidate_diff"]["patch"], "small repair delta")
        self.assertEqual(packet["test_results"], [{"passed": True}])
        self.assertEqual(packet["acceptance_criteria"], [])
        self.assertEqual(packet["global_criteria"], [])
        self.assertNotIn("original_request", packet)
        review = {
            "decision": "REJECT",
            "reviewed_diff_sha256": "a" * 64,
            "base_commit": "b" * 40,
            "candidate_id": "c" * 40,
            "criteria": [],
            "findings": ["repair"],
            "required_changes": ["repair"],
            "route": "builder",
            "review_mode": "FINDING_ONLY_RECHECK",
            "predecessor_review_ref": "sol_review_1.json",
            "target_finding_ids": ["T1-F001"],
            "finding_records": [
                {
                    "finding_id": "T1-F001",
                    "status": "REGRESSED",
                    "criterion_ids": [],
                    "summary": "repair",
                    "evidence": {
                        "repair_delta_sha256": "a" * 64,
                        "verification_ref": "attestations/" + "b" * 64 + ".json",
                        "observation": "test",
                    },
                    "required_correction": "repair",
                }
            ],
        }
        predecessor = json.loads(json.dumps(review))
        review["finding_records"][0]["status"] = "OPEN"
        review["finding_records"][0]["evidence"] = "test"
        predecessor["review_mode"] = "LARGE_STEP_REVIEW"
        predecessor["predecessor_review_ref"] = None
        predecessor["target_finding_ids"] = []
        validated = validate_review(
            review,
            "a" * 64,
            "b" * 40,
            "c" * 40,
            expected_review_mode="FINDING_ONLY_RECHECK",
            expected_predecessor_review_ref="sol_review_1.json",
            expected_target_finding_ids=["T1-F001"],
            task_id="T1",
            predecessor_review=predecessor,
        )
        self.assertEqual(validated["finding_records"][0]["finding_id"], "T1-F001")
        validation_kwargs = {
            "expected_review_mode": "FINDING_ONLY_RECHECK",
            "expected_predecessor_review_ref": "sol_review_1.json",
            "expected_target_finding_ids": ["T1-F001"],
            "task_id": "T1",
            "predecessor_review": predecessor,
            "expected_repair_delta_sha256": "a" * 64,
            "expected_verification_ref": "attestations/" + "b" * 64 + ".json",
        }
        missing_records = json.loads(json.dumps(review))
        missing_records.pop("finding_records")
        with self.assertRaisesRegex(FactoryError, "must provide finding_records"):
            validate_review(missing_records, "a" * 64, "b" * 40, "c" * 40, **validation_kwargs)
        stale_resolution = json.loads(json.dumps(review))
        stale_resolution["finding_records"][0]["status"] = "RESOLVED"
        stale_resolution["finding_records"][0]["evidence"] = "old evidence"
        with self.assertRaisesRegex(FactoryError, "structured repair evidence"):
            validate_review(stale_resolution, "a" * 64, "b" * 40, "c" * 40, **validation_kwargs)
        wrong_repair_hash = json.loads(json.dumps(review))
        wrong_repair_hash["finding_records"][0]["status"] = "RESOLVED"
        wrong_repair_hash["finding_records"][0]["evidence"] = {
            "repair_delta_sha256": "0" * 64,
            "verification_ref": "attestations/" + "b" * 64 + ".json",
            "observation": "resolved",
        }
        with self.assertRaisesRegex(FactoryError, "current repair delta"):
            validate_review(wrong_repair_hash, "a" * 64, "b" * 40, "c" * 40, **validation_kwargs)
        wrong_verification = json.loads(json.dumps(review))
        wrong_verification["finding_records"][0]["status"] = "RESOLVED"
        wrong_verification["finding_records"][0]["evidence"] = {
            "repair_delta_sha256": "a" * 64,
            "verification_ref": "attestations/" + "c" * 64 + ".json",
            "observation": "resolved",
        }
        with self.assertRaisesRegex(FactoryError, "current verification"):
            validate_review(wrong_verification, "a" * 64, "b" * 40, "c" * 40, **validation_kwargs)
        self.assertNotEqual(
            failure_signature(
                {
                    "source": "Sol Reviewer",
                    "code": "review_rejection",
                    "criterion_ids": ["T1-F001"],
                    "evidence_signature": "a" * 64,
                }
            ),
            failure_signature(
                {
                    "source": "Sol Reviewer",
                    "code": "review_rejection",
                    "criterion_ids": ["T1-F001"],
                    "evidence_signature": "b" * 64,
                }
            ),
        )
        bad_regression = json.loads(json.dumps(validated))
        bad_regression["decision"] = "REJECT"
        bad_regression["finding_records"][0]["status"] = "REGRESSED"
        bad_regression["finding_records"][0]["evidence"] = ""
        with self.assertRaisesRegex(FactoryError, "resolved/regressed finding"):
            validate_review(
                bad_regression,
                "a" * 64,
                "b" * 40,
                "c" * 40,
                expected_review_mode="FINDING_ONLY_RECHECK",
                expected_predecessor_review_ref="sol_review_1.json",
                expected_target_finding_ids=["T1-F001"],
                task_id="T1",
                predecessor_review=predecessor,
            )
        bad_correction = json.loads(json.dumps(validated))
        bad_correction["required_changes"] = ["unrelated correction"]
        with self.assertRaisesRegex(FactoryError, "not bound to target"):
            validate_review(
                bad_correction,
                "a" * 64,
                "b" * 40,
                "c" * 40,
                expected_review_mode="FINDING_ONLY_RECHECK",
                expected_predecessor_review_ref="sol_review_1.json",
                expected_target_finding_ids=["T1-F001"],
                task_id="T1",
                predecessor_review=predecessor,
            )
        bad_identity = json.loads(json.dumps(validated))
        bad_identity["finding_records"][0]["criterion_ids"] = ["STEP7-F001"]
        with self.assertRaisesRegex(FactoryError, "changed predecessor"):
            validate_review(
                bad_identity,
                "a" * 64,
                "b" * 40,
                "c" * 40,
                expected_review_mode="FINDING_ONLY_RECHECK",
                expected_predecessor_review_ref="sol_review_1.json",
                expected_target_finding_ids=["T1-F001"],
                task_id="T1",
                predecessor_review=predecessor,
            )
        bad_criterion = json.loads(json.dumps(validated))
        bad_criterion["decision"] = "APPROVE"
        bad_criterion["route"] = "none"
        bad_criterion["findings"] = []
        bad_criterion["required_changes"] = []
        bad_criterion["criteria"] = [{"criterion": "G1", "passed": False}]
        bad_criterion["finding_records"][0]["status"] = "RESOLVED"
        bad_criterion["finding_records"][0]["evidence"] = {
            "repair_delta_sha256": "a" * 64,
            "verification_ref": "attestations/" + "b" * 64 + ".json",
            "observation": "resolved",
        }
        with self.assertRaisesRegex(FactoryError, "targeted criteria to pass"):
            validate_review(
                bad_criterion,
                "a" * 64,
                "b" * 40,
                "c" * 40,
                expected_review_mode="FINDING_ONLY_RECHECK",
                expected_predecessor_review_ref="sol_review_1.json",
                expected_target_finding_ids=["T1-F001"],
                task_id="T1",
                predecessor_review=predecessor,
            )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = make_repo(self.root)
        self.state_root = self.root / "state"

    def tearDown(self):
        self.temp.cleanup()

    def config(self) -> Config:
        return Config(
            repo=str(self.repo),
            request="Make value return two",
            requested_files=["calc.py", "test_calc.py"],
            test_command="python3 -m unittest -q",
            max_debug_attempts=2,
            max_review_cycles=2,
            test_timeout=30,
        )

    def test_success_commits_reviewed_hash_and_preserves_checkout(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        original_branch = cmd(["git", "branch", "--show-current"], self.repo)
        original_head = cmd(["git", "rev-parse", "HEAD"], self.repo)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)

        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(roles.model_calls.count(self.config().planner_model), 1)
        self.assertEqual(len(state["completed_commits"]), 3)
        self.assertEqual(
            [item["task_id"] for item in state["completed_commits"]],
            ["T1", "T2", "T3"],
        )
        self.assertTrue(state["master_plan_ref"].startswith("plans/"))
        self.assertTrue((self.state_root / identifier / state["master_plan_ref"]).is_file())
        self.assertNotIn("task_statuses", state)
        self.assertNotIn("remaining_gaps", state)
        for completed in state["completed_commits"]:
            self.assertEqual(
                cmd(["git", "show", "-s", "--format=%T", completed["commit"]], self.repo),
                completed["candidate_id"],
            )
        self.assertEqual(cmd(["git", "branch", "--show-current"], self.repo), original_branch)
        self.assertEqual(cmd(["git", "rev-parse", "HEAD"], self.repo), original_head)
        self.assertEqual(cmd(["git", "status", "--porcelain"], self.repo), "")
        self.assertEqual(state["reviewed_diff_sha256"], roles.review_hashes[-1])
        message = cmd(["git", "show", "-s", "--format=%B", state["commit"]], self.repo)
        self.assertIn(f"Reviewed-Diff-SHA256: {state['reviewed_diff_sha256']}", message)
        self.assertTrue(state["worktree_removed"])

    def test_prebind_verification_sequence_tampering_is_rejected_before_commit(self):
        roles, builder = PrebindTamperingRoles("sequence"), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        with self.assertRaisesRegex(FactoryError, "verification attestation"):
            engine.execute(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "failed")
        self.assertEqual(state["astra_invocation_count"], 1)

    def test_prebind_verification_command_and_log_tampering_is_rejected(self):
        for field in ("command", "log"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = make_repo(root)
                roles = PrebindTamperingRoles(field)
                engine = FactoryEngine(state_root=root / "state", role_client=roles, builder=FakeBuilder())
                config = self.config()
                config.repo = str(repo)
                identifier = engine.plan(config)
                with self.assertRaisesRegex(FactoryError, "verification (attestation|log)"):
                    engine.execute(identifier)
                self.assertEqual(roles.astra_invocation_count, 1)

    def test_pre_attestation_result_mutation_is_rejected_before_sol(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        run_dir = self.state_root / identifier
        original_stage = engine._stage

        def stage_then_tamper(*args, **kwargs):
            result = original_stage(*args, **kwargs)
            result_path = run_dir / "test_1.json"
            result_value = json.loads(result_path.read_text(encoding="utf-8"))
            result_value["injected_after_runner_hash"] = True
            result_path.write_text(json.dumps(result_value), encoding="utf-8")
            return result

        with patch.object(engine, "_stage", side_effect=stage_then_tamper):
            with self.assertRaisesRegex(FactoryError, "Runner result artifact (digest|schema) changed"):
                engine.execute(identifier)
        self.assertEqual(roles.reviewer_prompts, [])
        self.assertEqual(engine.status(identifier)["completed_commits"], [])

    def test_master_plan_artifact_is_content_addressed_and_tamper_evident(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.status(identifier)
        plan_path = self.state_root / identifier / state["master_plan_ref"]
        plan_path.write_text(plan_path.read_text(encoding="utf-8").replace("task", "tampered", 1), encoding="utf-8")
        with self.assertRaisesRegex(FactoryError, "content does not match"):
            engine.execute(identifier)

    def test_master_plan_rejects_uncovered_global_criteria_before_dispatch(self):
        plan = {
            "schema_version": 1,
            "request_ref": "request.json",
            "objective": "coverage",
            "global_criteria": [{"id": "G1", "statement": "required"}],
            "architecture_invariants": [{"id": "A1", "statement": "safe"}],
            "assumptions": [{"id": "AS1", "statement": "known", "critical": True}],
            "non_goals": [],
            "milestones": [{
                "id": "M1",
                "objective": "work",
                "tasks": [{
                    "id": "T1",
                    "objective": "unrelated",
                    "depends_on": [],
                    "editable_scope": ["calc.py"],
                    "acceptance_criteria": ["other"],
                    "verification_commands": ["python3 -m unittest -q"],
                    "preservation_constraints": [],
                    "global_criteria": [],
                }],
            }],
        }
        with self.assertRaisesRegex(FactoryError, "uncovered global criteria"):
            validate_master_plan(plan, ["calc.py", "test_calc.py"])

    def test_resume_from_verifying_continues_without_replaying_initial_builder(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        original_test = engine._test

        with patch.object(engine, "_test", side_effect=KeyboardInterrupt("verification interruption")):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
        self.assertEqual(builder.labels, ["builder_initial"])
        self.assertEqual(engine.status(identifier)["phase"], "verifying")

        with patch.object(engine, "_test", wraps=original_test) as resumed_test:
            state = engine.resume(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(builder.labels, ["builder_initial"] * 3)
        self.assertGreaterEqual(resumed_test.call_count, 1)

    def test_resume_from_reviewing_reuses_candidate_without_replaying_builder(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        original_review = engine._review

        with patch.object(engine, "_review", side_effect=KeyboardInterrupt("review interruption")):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
        self.assertEqual(builder.labels, ["builder_initial"])
        self.assertEqual(engine.status(identifier)["phase"], "reviewing")

        with patch.object(engine, "_review", wraps=original_review) as resumed_review:
            state = engine.resume(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(builder.labels, ["builder_initial"] * 3)
        self.assertGreaterEqual(resumed_review.call_count, 1)

    def test_resumed_runner_failure_routes_to_agy_repair_with_durable_attempt(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        original_test = engine._test

        with patch.object(engine, "_test", side_effect=KeyboardInterrupt("verification interruption")):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)

        calls = {"count": 0}

        def fail_once_then_pass(worktree, config, run_dir, sequence):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "sequence": sequence,
                    "artifact_sequence": sequence,
                    "command": config.test_command,
                    "returncode": 1,
                    "passed": False,
                    "log": str(run_dir / "resume-failure.log"),
                }
            return original_test(worktree, config, run_dir, sequence)

        with patch.object(engine, "_test", side_effect=fail_once_then_pass):
            state = engine.resume(identifier)

        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(builder.labels[0], "builder_initial")
        self.assertTrue(any(label.startswith("builder_resume_verify_repair_") for label in builder.labels))
        self.assertEqual(state["current_task_attempts"], 1)
        self.assertEqual(state["test_results"], [])
        self.assertTrue(state["verification_ref"].startswith("attestations/"))

    def test_resumed_sol_rejection_routes_to_agy_repair_and_preserves_reviews(self):
        roles, builder = FakeRoles(reject_first=True), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        original_review = engine._review

        with patch.object(engine, "_review", side_effect=KeyboardInterrupt("review interruption")):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)

        with patch.object(engine, "_review", wraps=original_review) as resumed_review:
            state = engine.resume(identifier)

        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertGreaterEqual(resumed_review.call_count, 2)
        self.assertTrue(any(label.startswith("builder_review_rework_resume_") for label in builder.labels))
        review_files = sorted(self.state_root.joinpath(identifier).glob("sol_review_*.json"))
        self.assertGreaterEqual(len(review_files), 2)
        self.assertEqual(len({path.name for path in review_files}), len(review_files))

    def test_resumed_orphan_sol_rejection_is_honored_before_any_re_review(self):
        roles, builder = FakeRoles(reject_first=True), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        original_review = engine._review
        interrupted = {"value": False}

        def reject_then_interrupt(*args, **kwargs):
            review = original_review(*args, **kwargs)
            if not interrupted["value"]:
                interrupted["value"] = True
                raise KeyboardInterrupt("crash after Sol rejection artifact")
            return review

        with patch.object(engine, "_review", side_effect=reject_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)

        run_dir = self.state_root / identifier
        interrupted_state = engine.status(identifier)
        self.assertEqual(interrupted_state["phase"], "reviewing")
        self.assertIsNone(interrupted_state.get("review_ref"))
        self.assertTrue(list(run_dir.glob("sol_review_*.json")))

        state = engine.resume(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertTrue(any(label.startswith("builder_review_rework_resume_") for label in builder.labels))
        self.assertEqual(len(roles.review_hashes), 4)

    def test_failed_test_routes_through_agy_then_retests_without_luna(self):
        roles, builder = FakeRoles(), FakeBuilder(initial_bad=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertIn("builder_debug_1", builder.labels)
        self.assertEqual(state["test_results"], [])
        self.assertTrue(state["verification_ref"].startswith("attestations/"))
        self.assertEqual(roles.luna_invocation_count, 0)
        self.assertNotIn("Luna", roles.role_calls)
        self.assertNotIn("Luna Debugger", roles.role_calls)

    def test_rejection_invalidates_hash_reworks_retests_and_reviews_again(self):
        roles, builder = FakeRoles(reject_first=True), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        attempts_seen_at_finding_recheck = []
        original_review = engine._review

        def observe_review(*args, **kwargs):
            if kwargs.get("review_mode") == "FINDING_ONLY_RECHECK":
                durable = json.loads(
                    (self.state_root / identifier / "run_state.json").read_text(encoding="utf-8")
                )
                attempts_seen_at_finding_recheck.append(durable["current_task_attempts"])
            return original_review(*args, **kwargs)

        with patch.object(engine, "_review", side_effect=observe_review):
            state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertGreaterEqual(state["review_cycles"], 2)
        self.assertGreaterEqual(len(roles.review_hashes), 2)
        self.assertNotEqual(roles.review_hashes[0], roles.review_hashes[1])
        self.assertEqual(state["test_results"], [])
        self.assertIn("builder_review_rework_1", builder.labels)
        self.assertEqual(attempts_seen_at_finding_recheck[:1], [2])
        first_review = json.loads(
            (self.state_root / identifier / "sol_review_1.json").read_text(encoding="utf-8")
        )
        second_review = json.loads(
            (self.state_root / identifier / "sol_review_2.json").read_text(encoding="utf-8")
        )
        self.assertEqual(first_review["review_mode"], "LARGE_STEP_REVIEW")
        self.assertEqual(first_review["target_finding_ids"], [])
        self.assertEqual(second_review["review_mode"], "FINDING_ONLY_RECHECK")
        self.assertEqual(second_review["predecessor_review_ref"], "sol_review_1.json")
        self.assertEqual(
            second_review["target_finding_ids"],
            [record["finding_id"] for record in first_review["finding_records"]],
        )

    def test_m2_checkpoint_repair_recheck_keeps_astra_out_of_ordinary_repair(self):
        roles, builder = FakeRoles(reject_first=True), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(roles.luna_invocation_count, 0)
        self.assertEqual(state["current_task_attempts"], 1)
        self.assertEqual(
            [payload["review_mode"] for payload in (
                json.loads(prompt.split("Input:\n", 1)[1]) for prompt in roles.reviewer_prompts[:2]
            )],
            ["LARGE_STEP_REVIEW", "FINDING_ONLY_RECHECK"],
        )

    def test_m2_checkpoint_repair_replan_resume_is_deterministic(self):
        roles = FakeRoles(replan_code="ASSUMPTION_DISPROVED")
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=FakeBuilder())
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 2)
        self.assertEqual(roles.luna_invocation_count, 0)
        self.assertEqual(len(state["replan_history"]), 1)
        self.assertEqual([item["task_id"] for item in state["completed_commits"]], ["T1", "T2", "T3"])

    def test_verified_active_task_replan_replaces_contract_without_resetting_attempts(self):
        roles = ActiveTaskReplacementRoles(replan_code="ASSUMPTION_DISPROVED")
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=FakeBuilder())
        identifier = engine.plan(self.config())
        planning_snapshots = []
        original_planning = engine._perform_planning

        def observe_replan(*args, **kwargs):
            planning_snapshots.append(dict(args[1]))
            return original_planning(*args, **kwargs)

        with patch.object(engine, "_perform_planning", side_effect=observe_replan):
            state = engine.execute(identifier)

        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 2)
        self.assertEqual(len(planning_snapshots), 1)
        self.assertEqual(planning_snapshots[0]["current_task_id"], "T1")
        self.assertEqual(planning_snapshots[0]["current_task_attempts"], 1)
        plan = json.loads(
            (self.state_root / identifier / state["master_plan_ref"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            master_plan_tasks(plan)[0]["objective"],
            "implement the revised active contract",
        )
        self.assertEqual(
            plan["global_criteria"][0]["statement"],
            "the revised active requirement passes",
        )
        self.assertEqual([item["task_id"] for item in state["completed_commits"]], ["T1", "T2", "T3"])

    def test_normal_no_patch_recovers_through_capsule_without_extra_planning(self):
        roles = TargetPlanRoles()
        builder = NoPatchThenCapsuleBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(roles.luna_invocation_count, 0)
        self.assertEqual(len(state["completed_commits"]), 3)
        self.assertEqual(
            [kind for _, kind in builder.calls],
            ["normal", "python_capsule"] * 3,
        )
        self.assertEqual(state["current_task_attempts"], 2)
        self.assertNotIn("Sol Planner", roles.role_calls)

    def test_explicit_token_budget_failure_advances_navigation_recovery(self):
        roles = TargetPlanRoles()
        builder = NoPatchThenCapsuleBuilder(normal_failure_code="agy_token_budget_exhausted")
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(roles.luna_invocation_count, 0)
        self.assertEqual(
            [kind for _, kind in builder.calls],
            ["normal", "python_capsule"] * 3,
        )

    def test_scope_violation_fails_without_commit(self):
        roles, builder = FakeRoles(), FakeBuilder(violate_scope=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        base = cmd(["git", "rev-parse", "HEAD"], self.repo)
        with self.assertRaisesRegex(FactoryError, "scope violation"):
            engine.execute(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "failed")
        self.assertEqual(state["error_category"], "scope")
        self.assertEqual(cmd(["git", "rev-parse", "HEAD"], self.repo), base)

    def test_symlink_replacement_after_builder_is_rejected(self):
        engine = FactoryEngine(
            state_root=self.state_root,
            role_client=FakeRoles(),
            builder=FakeBuilder(replace_with_symlink=True),
        )
        identifier = engine.plan(self.config())
        with self.assertRaisesRegex(FactoryError, "allowed path may not be a symlink"):
            engine.execute(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "failed")
        self.assertNotIn("commit", state)

    def test_wrong_review_hash_fails_without_commit(self):
        roles, builder = FakeRoles(bad_hash=True), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        with self.assertRaisesRegex(FactoryError, "hash"):
            engine.execute(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "failed")
        self.assertEqual(state["error_category"], "hash")

    def test_failed_reviewer_rework_routes_back_through_agy_without_luna(self):
        roles = FakeRoles(reject_first=True)
        builder = FakeBuilder(review_rework_bad=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertIn("builder_review_debug_1_1", builder.labels)
        self.assertEqual(state["test_results"], [])
        self.assertGreaterEqual(state["review_cycles"], 2)
        self.assertEqual(roles.luna_invocation_count, 0)
        self.assertNotIn("Luna", roles.role_calls)
        self.assertNotIn("Luna Debugger", roles.role_calls)

    def test_luna_review_route_is_rejected_by_the_v1_contract(self):
        with self.assertRaisesRegex(FactoryError, "none or builder"):
            validate_review(
                {
                    "decision": "REJECT",
                    "reviewed_diff_sha256": "a" * 64,
                    "base_commit": "b" * 40,
                    "candidate_id": "c" * 40,
                    "criteria": [],
                    "findings": ["ambiguous"],
                    "required_changes": ["repair the failure"],
                    "route": "luna",
                },
                "a" * 64,
                "b" * 40,
                "c" * 40,
            )

    def test_approve_rejects_failed_criteria(self):
        with self.assertRaisesRegex(FactoryError, "every supplied criterion to pass"):
            validate_review(
                {
                    "decision": "APPROVE",
                    "reviewed_diff_sha256": "a" * 64,
                    "base_commit": "b" * 40,
                    "candidate_id": "c" * 40,
                    "criteria": [{"criterion": "G1", "passed": False}],
                    "findings": [],
                    "required_changes": [],
                    "route": "none",
                },
                "a" * 64,
                "b" * 40,
                "c" * 40,
                ["G1"],
            )

    def test_review_rejects_duplicate_criteria(self):
        with self.assertRaisesRegex(FactoryError, "duplicate identifiers"):
            validate_review(
                {
                    "decision": "APPROVE",
                    "reviewed_diff_sha256": "a" * 64,
                    "base_commit": "b" * 40,
                    "candidate_id": "c" * 40,
                    "criteria": [
                        {"criterion": "G1", "passed": True},
                        {"criterion": "G1", "passed": True},
                    ],
                    "findings": [],
                    "required_changes": [],
                    "route": "none",
                },
                "a" * 64,
                "b" * 40,
                "c" * 40,
                ["G1"],
            )

    def test_master_plan_rejects_cross_category_identifier_collision(self):
        plan = {
            "schema_version": 1,
            "request_ref": "request.json",
            "objective": "identity safety",
            "global_criteria": [{"id": "G1", "statement": "global"}],
            "architecture_invariants": [{"id": "G1", "statement": "invariant"}],
            "assumptions": [{"id": "AS1", "statement": "known", "critical": True}],
            "non_goals": [],
            "milestones": [{
                "id": "M1",
                "objective": "implement",
                "tasks": [{
                    "id": "T1",
                    "objective": "change",
                    "depends_on": [],
                    "editable_scope": ["calc.py"],
                    "acceptance_criteria": [{"id": "T1.AC1", "statement": "works"}],
                    "verification_commands": ["python3 -m unittest -q"],
                    "preservation_constraints": [],
                    "global_criteria": ["G1"],
                }],
            }],
        }
        with self.assertRaisesRegex(FactoryError, "globally unique"):
            validate_master_plan(plan, ["calc.py"])

    def test_master_plan_rejects_duplicate_global_criterion_reference(self):
        plan = {
            "schema_version": 1,
            "request_ref": "request.json",
            "objective": "reference safety",
            "global_criteria": [{"id": "G1", "statement": "global"}],
            "architecture_invariants": [{"id": "A1", "statement": "safe"}],
            "assumptions": [{"id": "AS1", "statement": "known", "critical": True}],
            "non_goals": [],
            "milestones": [{
                "id": "M1",
                "objective": "implement",
                "tasks": [{
                    "id": "T1",
                    "objective": "change",
                    "depends_on": [],
                    "editable_scope": ["calc.py"],
                    "acceptance_criteria": [{"id": "T1.AC1", "statement": "works"}],
                    "verification_commands": ["python3 -m unittest -q"],
                    "preservation_constraints": [],
                    "global_criteria": ["G1", "G1"],
                }],
            }],
        }
        with self.assertRaisesRegex(FactoryError, "duplicate global criterion"):
            validate_master_plan(plan, ["calc.py"])

    def test_overlapping_later_task_invalidates_prior_global_evidence(self):
        state = {
            "criterion_evidence": {
                "G1": {
                    "status": "PASS",
                    "task_id": "T1",
                    "commit": "a" * 40,
                    "task_scope": ["calc.py"],
                }
            },
            "completed_commits": [{"task_id": "T1", "commit": "a" * 40}],
        }
        FactoryEngine._invalidate_affected_criteria(
            state,
            {"id": "T2", "editable_scope": ["calc.py"], "global_criteria": []},
        )
        self.assertEqual(state["criterion_evidence"]["G1"]["status"], "UNVERIFIED")
        self.assertNotIn("commit", state["criterion_evidence"]["G1"])
        self.assertEqual(
            FactoryEngine._remaining_master_plan_gaps(
                {"global_criteria": [{"id": "G1", "statement": "global"}]}, state
            ),
            ["G1"],
        )

    def test_distributed_criteria_preserve_unaffected_evidence_and_complete_once(self):
        roles, builder = DistributedRoles(), DistributedBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.requested_files = ["f1.py", "f2.py", "f3.py"]
        config.test_command = f'"{sys.executable}" -c "pass"'
        for name in config.requested_files:
            (self.repo / name).write_text("def slice_value():\n    return 0\n", encoding="utf-8")
        subprocess.run(["git", "add", *config.requested_files], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add distributed slice fixtures"], cwd=self.repo, check=True)
        identifier = engine.plan(config)
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(builder.labels, ["builder_initial"] * 3)
        self.assertEqual(
            {key: value["status"] for key, value in state["criterion_evidence"].items()},
            {"G1": "PASS", "G2": "PASS", "G3": "PASS"},
        )

    def test_overlapping_distributed_criteria_refresh_affected_evidence_without_replan(self):
        roles, builder = DistributedRoles(overlap=True), DistributedBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.requested_files = ["f1.py", "f2.py", "f3.py"]
        config.test_command = f'"{sys.executable}" -c "pass"'
        for name in config.requested_files:
            (self.repo / name).write_text("def slice_value():\n    return 0\n", encoding="utf-8")
        subprocess.run(["git", "add", *config.requested_files], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add overlapping slice fixtures"], cwd=self.repo, check=True)
        identifier = engine.plan(config)
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(
            {key: value["status"] for key, value in state["criterion_evidence"].items()},
            {"G1": "PASS", "G2": "PASS", "G3": "PASS"},
        )

    def test_replan_exhaustion_is_durable_blocked_without_refilling_astra_budget(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        with patch.object(FactoryEngine, "_record_approved_criteria", return_value=None):
            with self.assertRaisesRegex(FactoryError, "cannot produce a ready task"):
                engine.execute(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["error_category"], "blocked")
        self.assertTrue((self.state_root / identifier / "replan_blocked.json").is_file())
        astra_count = roles.astra_invocation_count
        with self.assertRaisesRegex(FactoryError, "blocked run"):
            engine.execute(identifier)
        self.assertEqual(roles.astra_invocation_count, astra_count)

    def test_replan_reason_contract_accepts_only_typed_verified_triggers(self):
        codes = {
            "ASSUMPTION_DISPROVED",
            "REQUIRED_GAP_UNCOVERED",
            "ARCHITECTURE_DEPENDENCY_CONFLICT",
            "PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE",
            "USER_OBJECTIVE_OR_SCOPE_CHANGE",
        }
        for code in codes:
            with self.subTest(code=code):
                self.assertEqual(
                    validate_replan_reason(
                        {
                            "code": code,
                            "evidence": {
                                "artifact_ref": "verified",
                                "kind": {
                                    "ASSUMPTION_DISPROVED": "assumption",
                                    "REQUIRED_GAP_UNCOVERED": "gap",
                                    "ARCHITECTURE_DEPENDENCY_CONFLICT": "dependency_conflict",
                                    "PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE": "completion_gap",
                                    "USER_OBJECTIVE_OR_SCOPE_CHANGE": "user_change",
                                }[code],
                                "verified": True,
                            },
                        }
                    )["code"],
                    code,
                )
        with self.assertRaisesRegex(FactoryError, "unsupported code"):
            validate_replan_reason({"code": "plan", "evidence": {"artifact_ref": "unknown", "kind": "gap", "verified": True}})
        with self.assertRaisesRegex(FactoryError, "exactly code and evidence"):
            validate_replan_reason({"code": "ASSUMPTION_DISPROVED", "evidence": {}, "extra": True})

    def test_explicit_replan_trigger_routes_to_astra_with_durable_reason(self):
        for code in (
            "ASSUMPTION_DISPROVED",
            "REQUIRED_GAP_UNCOVERED",
            "ARCHITECTURE_DEPENDENCY_CONFLICT",
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = make_repo(root)
                roles = FakeRoles(replan_code=code)
                engine = FactoryEngine(state_root=root / "state", role_client=roles, builder=FakeBuilder())
                config = self.config()
                config.repo = str(repo)
                identifier = engine.plan(config)
                state = engine.execute(identifier)
                self.assertEqual(state["phase"], "complete")
                self.assertEqual(roles.astra_invocation_count, 2)
                history = state["replan_history"]
                self.assertEqual(len(history), 1)
                reason_value = json.loads(
                    (root / "state" / identifier / history[0]["record_ref"]).read_text(encoding="utf-8")
                )
                self.assertEqual(reason_value["code"], code)
                if code == "ASSUMPTION_DISPROVED":
                    review_path = root / "state" / identifier / reason_value["evidence"]["artifact_ref"]
                    review_path.write_text(review_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(FactoryError, "terminal state"):
                        engine.status(identifier)

    def test_assumption_and_dependency_replan_triggers_use_code_specific_evidence(self):
        for code in ("ASSUMPTION_DISPROVED", "ARCHITECTURE_DEPENDENCY_CONFLICT"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = make_repo(root)
                roles = FakeRoles(replan_code=code)
                engine = FactoryEngine(state_root=root / "state", role_client=roles, builder=FakeBuilder())
                config = self.config()
                config.repo = str(repo)
                identifier = engine.plan(config)
                state = engine.execute(identifier)
                self.assertEqual(state["phase"], "complete")
                self.assertEqual(roles.astra_invocation_count, 2)

    def test_fabricated_replan_artifact_cannot_invoke_astra(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        run_dir = self.state_root / identifier
        atomic_json(
            run_dir / "fabricated.json",
            {
                "replan_code": "ASSUMPTION_DISPROVED",
                "kind": "assumption",
                "verified": True,
                "producer": "Runner",
                "assumption_id": "AS1",
            },
        )
        reason = {
            "code": "ASSUMPTION_DISPROVED",
            "evidence": {"artifact_ref": "fabricated.json", "kind": "assumption", "verified": True},
        }
        with self.assertRaisesRegex(FactoryError, "bounded host artifact"):
            engine.request_replan(identifier, reason)
        self.assertEqual(roles.astra_invocation_count, 1)

    def test_generic_sol_replan_reason_is_blocked_without_astra(self):
        roles, builder = FakeRoles(replan_code="ASSUMPTION_DISPROVED", generic_replan=True), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        with self.assertRaisesRegex(FactoryError, "replan evidence Sol reason identity is inconsistent"):
            engine.execute(identifier)
        self.assertEqual(roles.astra_invocation_count, 1)

    def test_complete_replan_history_revalidates_an_earlier_sol_artifact(self):
        roles, builder = FakeRoles(
            replan_codes=["ASSUMPTION_DISPROVED", "ASSUMPTION_DISPROVED"]
        ), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        history = state["replan_history"]
        self.assertEqual(len(history), 2)
        first_reason = json.loads(
            (self.state_root / identifier / history[0]["record_ref"]).read_text(encoding="utf-8")
        )
        first_review = self.state_root / identifier / first_reason["evidence"]["artifact_ref"]
        first_review.write_text(first_review.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.status(identifier)
        self.assertEqual(roles.astra_invocation_count, 3)

    def test_multi_replan_history_survives_user_replacement_and_blocks_earlier_tamper(self):
        roles = MultiReplanRoles(replan_codes=["ASSUMPTION_DISPROVED"])
        builder = ScopeChangingBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.requested_files = ["calc.py", "test_calc.py", "new.py"]
        config.test_command = f'"{sys.executable}" -c "pass"'
        (self.repo / "new.py").write_text("replacement = 0\n", encoding="utf-8")
        subprocess.run(["git", "add", "new.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add replacement fixture"], cwd=self.repo, check=True)
        identifier = engine.plan(config)
        original_execute_one = engine._execute_one_task
        interrupted = {"value": False}

        def stop_after_first_commit(*args, **kwargs):
            state = original_execute_one(*args, **kwargs)
            if not interrupted["value"] and len(state.get("completed_commits", [])) == 1:
                interrupted["value"] = True
                raise KeyboardInterrupt("pause before user replacement replan")
            return state

        with patch.object(engine, "_execute_one_task", side_effect=stop_after_first_commit):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
        paused = engine.status(identifier)
        self.assertEqual(len(paused["completed_commits"]), 1)
        self.assertEqual(len(paused["replan_history"]), 1)

        completed = engine.request_replan(
            identifier,
            {
                "code": "USER_OBJECTIVE_OR_SCOPE_CHANGE",
                "evidence": {"artifact_ref": "user-supplied.json", "kind": "user_change", "verified": True},
            },
            objective="Implement the replacement user objective",
            requested_files=["calc.py", "test_calc.py", "new.py"],
        )
        self.assertEqual(completed["phase"], "complete")
        self.assertEqual(len(completed["replan_history"]), 2)
        self.assertTrue(completed["request_ref"].startswith("requests/"))
        self.assertEqual(roles.astra_invocation_count, 3)
        first_record = json.loads(
            (self.state_root / identifier / completed["replan_history"][0]["record_ref"]).read_text(encoding="utf-8")
        )
        first_review = self.state_root / identifier / first_record["evidence"]["artifact_ref"]
        first_review.write_text(first_review.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.status(identifier)
        self.assertEqual(roles.astra_invocation_count, 3)

    def test_multi_replan_history_revalidates_earlier_hermes_evidence(self):
        roles = HermesThenUserRoles()
        builder = ScopeChangingBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.requested_files = ["calc.py", "test_calc.py", "new.py"]
        config.test_command = f'"{sys.executable}" -c "pass"'
        (self.repo / "new.py").write_text("replacement = 0\n", encoding="utf-8")
        subprocess.run(["git", "add", "new.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add replacement fixture"], cwd=self.repo, check=True)
        identifier = engine.plan(config)
        original_execute_one = engine._execute_one_task
        pause_target = {"completed": 1}

        def pause_after_commit(*args, **kwargs):
            state = original_execute_one(*args, **kwargs)
            if len(state.get("completed_commits", [])) == pause_target["completed"]:
                pause_target["completed"] = 2
                raise KeyboardInterrupt("pause for Hermes replan evidence")
            return state

        with patch.object(engine, "_execute_one_task", side_effect=pause_after_commit):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
        paused = engine.status(identifier)
        plan = json.loads((self.state_root / identifier / paused["master_plan_ref"]).read_text(encoding="utf-8"))
        completed_ids = sorted(item["task_id"] for item in paused["completed_commits"])
        pending_ids = sorted(task["id"] for task in master_plan_tasks(plan) if task["id"] not in completed_ids)
        evidence_ref = "replan_evidence_1.json"
        atomic_json(
            self.state_root / identifier / evidence_ref,
            {
                "artifact_type": "hermes_replan_evidence_v1",
                "replan_code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
                "kind": "dependency_conflict",
                "verified": True,
                "producer": "Hermes",
                "run_id": identifier,
                "master_plan_ref": paused["master_plan_ref"],
                "request_ref": paused["request_ref"],
                "request_sha256": paused["request_sha256"],
                "base_commit": paused["base_commit"],
                "task_id": paused["current_task_id"],
                "candidate_id": paused["candidate_id"],
                "sequence": 1,
                "remaining_gaps": [],
                "completed_task_ids": completed_ids,
                "blocked_task_ids": pending_ids,
                "dependency": next(
                    f"{dependency}->{item['id']}"
                    for item in master_plan_tasks(plan)
                    for dependency in item.get("depends_on", [])
                ),
            },
        )
        reason = {
            "code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
            "evidence": {"artifact_ref": evidence_ref, "kind": "dependency_conflict", "verified": True},
        }
        with patch.object(engine, "_execute_one_task", side_effect=pause_after_commit):
            with self.assertRaises(KeyboardInterrupt):
                engine.request_replan(identifier, reason)
        paused_again = engine.status(identifier)
        self.assertEqual(len(paused_again["replan_history"]), 1)
        pause_target["completed"] = 99
        completed = engine.request_replan(
            identifier,
            {
                "code": "USER_OBJECTIVE_OR_SCOPE_CHANGE",
                "evidence": {"artifact_ref": "user-supplied.json", "kind": "user_change", "verified": True},
            },
            objective="Implement the replacement user objective",
            requested_files=["calc.py", "test_calc.py", "new.py"],
        )
        self.assertEqual(completed["phase"], "complete")
        self.assertEqual(len(completed["replan_history"]), 2)
        first_record = json.loads(
            (self.state_root / identifier / completed["replan_history"][0]["record_ref"]).read_text(encoding="utf-8")
        )
        hermes_evidence = self.state_root / identifier / first_record["evidence"]["artifact_ref"]
        hermes_value = json.loads(hermes_evidence.read_text(encoding="utf-8"))
        hermes_value["base_commit"] = completed["source_head_before"]
        hermes_value["candidate_id"] = "f" * 40
        atomic_json(hermes_evidence, hermes_value)
        first_record["evidence"]["artifact_sha256"] = hashlib.sha256(hermes_evidence.read_bytes()).hexdigest()
        temporary_record = self.state_root / identifier / "rehashed-hermes-record.json"
        atomic_json(temporary_record, first_record)
        rehashed_sha = hashlib.sha256(temporary_record.read_bytes()).hexdigest()
        rehashed_ref = f"replan_history/{rehashed_sha}.json"
        temporary_record.replace(self.state_root / identifier / rehashed_ref)
        state_path = self.state_root / identifier / "run_state.json"
        durable_state = json.loads(state_path.read_text(encoding="utf-8"))
        durable_state["replan_history"][0] = {
            "sequence": 1,
            "record_ref": rehashed_ref,
            "record_sha256": rehashed_sha,
            "code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
        }
        atomic_json(state_path, durable_state)
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.status(identifier)
        self.assertEqual(roles.astra_invocation_count, 3)

    def test_rehashed_fabricated_historical_hermes_record_is_rejected(self):
        roles = HermesThenUserRoles()
        builder = ScopeChangingBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.requested_files = ["calc.py", "test_calc.py", "new.py"]
        config.test_command = f'"{sys.executable}" -c "pass"'
        (self.repo / "new.py").write_text("replacement = 0\n", encoding="utf-8")
        subprocess.run(["git", "add", "new.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add replacement fixture"], cwd=self.repo, check=True)
        identifier = engine.plan(config)
        original_execute_one = engine._execute_one_task
        pause_target = {"completed": 1}

        def pause_after_commit(*args, **kwargs):
            state = original_execute_one(*args, **kwargs)
            if len(state.get("completed_commits", [])) == pause_target["completed"]:
                pause_target["completed"] = 2
                raise KeyboardInterrupt("pause for Hermes replan evidence")
            return state

        with patch.object(engine, "_execute_one_task", side_effect=pause_after_commit):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
        paused = engine.status(identifier)
        plan = json.loads((self.state_root / identifier / paused["master_plan_ref"]).read_text(encoding="utf-8"))
        completed_ids = sorted(item["task_id"] for item in paused["completed_commits"])
        pending_ids = sorted(task["id"] for task in master_plan_tasks(plan) if task["id"] not in completed_ids)
        evidence_ref = "replan_evidence_1.json"
        atomic_json(
            self.state_root / identifier / evidence_ref,
            {
                "artifact_type": "hermes_replan_evidence_v1",
                "replan_code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
                "kind": "dependency_conflict",
                "verified": True,
                "producer": "Hermes",
                "run_id": identifier,
                "master_plan_ref": paused["master_plan_ref"],
                "request_ref": paused["request_ref"],
                "request_sha256": paused["request_sha256"],
                "base_commit": paused["base_commit"],
                "task_id": paused["current_task_id"],
                "candidate_id": paused["candidate_id"],
                "sequence": 1,
                "remaining_gaps": [],
                "completed_task_ids": completed_ids,
                "blocked_task_ids": pending_ids,
                "dependency": next(
                    f"{dependency}->{item['id']}"
                    for item in master_plan_tasks(plan)
                    for dependency in item.get("depends_on", [])
                ),
            },
        )
        with patch.object(engine, "_execute_one_task", side_effect=pause_after_commit):
            with self.assertRaises(KeyboardInterrupt):
                engine.request_replan(
                    identifier,
                    {
                        "code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
                        "evidence": {"artifact_ref": evidence_ref, "kind": "dependency_conflict", "verified": True},
                    },
                )
        self.assertEqual(len(engine.status(identifier)["replan_history"]), 1)
        pause_target["completed"] = 99
        state = engine.request_replan(
            identifier,
            {
                "code": "USER_OBJECTIVE_OR_SCOPE_CHANGE",
                "evidence": {"artifact_ref": "user-supplied.json", "kind": "user_change", "verified": True},
            },
            objective="Implement the replacement user objective",
            requested_files=["calc.py", "test_calc.py", "new.py"],
        )
        self.assertEqual(state["phase"], "complete")
        history = state["replan_history"]
        record_path = self.state_root / identifier / history[0]["record_ref"]
        record = json.loads(record_path.read_text(encoding="utf-8"))
        evidence_path = self.state_root / identifier / record["evidence"]["artifact_ref"]
        fabricated = json.loads(evidence_path.read_text(encoding="utf-8"))
        fabricated.update(
            {
                "artifact_type": "attacker_artifact",
                "replan_code": "ASSUMPTION_DISPROVED",
                "kind": "assumption",
                "verified": False,
                "producer": "Attacker",
                "sequence": 987654,
                "extra": True,
            }
        )
        atomic_json(evidence_path, fabricated)
        record["evidence"]["artifact_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        temporary_record = self.state_root / identifier / "rewritten-record.json"
        atomic_json(temporary_record, record)
        rewritten_sha = hashlib.sha256(temporary_record.read_bytes()).hexdigest()
        rewritten_ref = f"replan_history/{rewritten_sha}.json"
        temporary_record.replace(self.state_root / identifier / rewritten_ref)
        state_path = self.state_root / identifier / "run_state.json"
        durable_state = json.loads(state_path.read_text(encoding="utf-8"))
        durable_state["replan_history"][0] = {
            "sequence": 1,
            "record_ref": rewritten_ref,
            "record_sha256": rewritten_sha,
            "code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
        }
        atomic_json(state_path, durable_state)
        with self.assertRaisesRegex(FactoryError, "terminal state|historical Hermes"):
            engine.status(identifier)
        self.assertEqual(roles.astra_invocation_count, 3)

    def test_multi_replan_history_tamper_matrix_blocks_without_new_dispatch(self):
        targets = (
            "reason_record",
            "request_artifact",
            "request_digest",
            "replacement_request",
            "sol_review",
            "verification",
            "candidate",
            "base",
            "plan_request_pair",
        )
        operations = ("execute", "resume", "status")
        for index, target in enumerate(targets):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = make_repo(root)
                roles = MultiReplanRoles(replan_codes=["ASSUMPTION_DISPROVED"])
                engine = FactoryEngine(state_root=root / "state", role_client=roles, builder=ScopeChangingBuilder())
                config = self.config()
                config.repo = str(repo)
                config.requested_files = ["calc.py", "test_calc.py", "new.py"]
                config.test_command = f'"{sys.executable}" -c "pass"'
                (repo / "new.py").write_text("replacement = 0\n", encoding="utf-8")
                subprocess.run(["git", "add", "new.py"], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-qm", "add replacement fixture"], cwd=repo, check=True)
                identifier = engine.plan(config)
                original_execute_one = engine._execute_one_task
                interrupted = {"value": False}

                def stop_after_first_commit(*args, **kwargs):
                    state = original_execute_one(*args, **kwargs)
                    if not interrupted["value"] and len(state.get("completed_commits", [])) == 1:
                        interrupted["value"] = True
                        raise KeyboardInterrupt("pause before user replacement replan")
                    return state

                with patch.object(engine, "_execute_one_task", side_effect=stop_after_first_commit):
                    with self.assertRaises(KeyboardInterrupt):
                        engine.execute(identifier)
                engine.request_replan(
                    identifier,
                    {
                        "code": "USER_OBJECTIVE_OR_SCOPE_CHANGE",
                        "evidence": {"artifact_ref": "user-supplied.json", "kind": "user_change", "verified": True},
                    },
                    objective="Implement the replacement user objective",
                    requested_files=["calc.py", "test_calc.py", "new.py"],
                )
                completed = engine.status(identifier)
                history = completed["replan_history"]
                first_record_path = root / "state" / identifier / history[0]["record_ref"]
                first_record = json.loads(first_record_path.read_text(encoding="utf-8"))
                first_evidence = first_record["evidence"]
                if target == "reason_record":
                    first_record["sequence"] = 987654
                    first_record_path.write_text(json.dumps(first_record), encoding="utf-8")
                elif target == "request_artifact":
                    request_path = root / "state" / identifier / first_evidence["request_ref"]
                    request_path.write_text(
                        request_path.read_text(encoding="utf-8").replace(
                            "Make value return two", "tampered historical request"
                        ),
                        encoding="utf-8",
                    )
                    first_record["evidence"]["request_sha256"] = hashlib.sha256(
                        request_path.read_bytes()
                    ).hexdigest()
                    rewritten = root / "state" / identifier / "request-record.json"
                    atomic_json(rewritten, first_record)
                    rewritten_sha = hashlib.sha256(rewritten.read_bytes()).hexdigest()
                    rewritten_ref = f"replan_history/{rewritten_sha}.json"
                    rewritten.replace(root / "state" / identifier / rewritten_ref)
                    state_path = root / "state" / identifier / "run_state.json"
                    durable_state = json.loads(state_path.read_text(encoding="utf-8"))
                    durable_state["replan_history"][0] = {
                        "sequence": 1,
                        "record_ref": rewritten_ref,
                        "record_sha256": rewritten_sha,
                        "code": "ASSUMPTION_DISPROVED",
                    }
                    atomic_json(state_path, durable_state)
                elif target == "request_digest":
                    state_path = root / "state" / identifier / "run_state.json"
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    state["replan_history"][0]["record_sha256"] = "0" * 64
                    atomic_json(state_path, state)
                elif target == "replacement_request":
                    replacement_path = root / "state" / identifier / completed["request_ref"]
                    replacement = json.loads(replacement_path.read_text(encoding="utf-8"))
                    replacement["request"] = "tampered replacement"
                    replacement_path.write_text(json.dumps(replacement), encoding="utf-8")
                elif target == "sol_review":
                    review_path = root / "state" / identifier / first_evidence["artifact_ref"]
                    review_path.write_text(review_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                elif target == "verification":
                    attestation_path = root / "state" / identifier / first_evidence["verification_ref"]
                    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
                    attestation["command"] = "tampered verification"
                    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
                elif target in {"candidate", "base"}:
                    candidate_path = root / "state" / identifier / first_evidence["candidate_ref"]
                    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                    candidate["candidate_id" if target == "candidate" else "base_commit"] = "0" * 40
                    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
                elif target == "plan_request_pair":
                    first_record["evidence"]["master_plan_ref"] = completed["master_plan_ref"]
                    rewritten = root / "state" / identifier / "pair-record.json"
                    atomic_json(rewritten, first_record)
                    rewritten_sha = hashlib.sha256(rewritten.read_bytes()).hexdigest()
                    rewritten_ref = f"replan_history/{rewritten_sha}.json"
                    rewritten.replace(root / "state" / identifier / rewritten_ref)
                    state_path = root / "state" / identifier / "run_state.json"
                    durable_state = json.loads(state_path.read_text(encoding="utf-8"))
                    durable_state["replan_history"][0] = {
                        "sequence": 1,
                        "record_ref": rewritten_ref,
                        "record_sha256": rewritten_sha,
                        "code": "ASSUMPTION_DISPROVED",
                    }
                    atomic_json(state_path, durable_state)
                operation = getattr(engine, operations[index % len(operations)])
                with self.assertRaisesRegex(FactoryError, "terminal state|replan|verification|candidate"):
                    operation(identifier)
                blocked = engine.status(identifier)
                self.assertEqual(blocked["phase"], "blocked")
                self.assertEqual(len(blocked["completed_commits"]), len(completed["completed_commits"]))
                self.assertEqual(roles.astra_invocation_count, 3)

    def test_user_scope_replan_accepts_authoritative_replacement_scope(self):
        roles = ScopeChangingRoles(plan_files=["calc.py", "test_calc.py", "new.py"])
        builder = ScopeChangingBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.requested_files = ["calc.py", "test_calc.py", "new.py"]
        config.test_command = f'"{sys.executable}" -c "pass"'
        identifier = engine.plan(config)
        reason = {
            "code": "USER_OBJECTIVE_OR_SCOPE_CHANGE",
            "evidence": {"artifact_ref": "authorized-user-change", "kind": "user_change", "verified": True},
        }
        state = engine.request_replan(
            identifier,
            reason,
            objective="Implement the replacement objective",
            requested_files=["new.py"],
        )
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 2)
        self.assertEqual(state["config"]["requested_files"], ["new.py"])
        self.assertTrue((self.state_root / identifier / state["request_change_ref"]).is_file())
        self.assertEqual(state["request_ref"], state["request_change_ref"])
        request_path = self.state_root / identifier / state["request_ref"]
        request_value = json.loads(request_path.read_text(encoding="utf-8"))
        request_value["request"] = "tampered replacement objective"
        request_path.write_text(json.dumps(request_value), encoding="utf-8")
        with self.assertRaisesRegex(FactoryError, "terminal state"):
            engine.status(identifier)

    def test_replan_rejects_rewriting_completed_task_contract(self):
        roles, builder = RewritingAstraRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        with patch.object(FactoryEngine, "_record_approved_criteria", return_value=None):
            with self.assertRaisesRegex(FactoryError, "immutable completed planning history"):
                engine.execute(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "blocked")
        self.assertTrue(state["replan_block_evidence"].startswith("replan_rejected_"))

    def test_replan_budget_survives_crash_between_reason_persistence_and_astra(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        original_planning = engine._perform_planning
        crashed = {"value": False}

        def crash_first_replan(*args, **kwargs):
            if kwargs.get("replan_reason") and not crashed["value"]:
                crashed["value"] = True
                raise KeyboardInterrupt("crash after replan reservation")
            return original_planning(*args, **kwargs)

        with patch.object(FactoryEngine, "_record_approved_criteria", return_value=None), patch.object(
            engine, "_perform_planning", side_effect=crash_first_replan
        ):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
        self.assertEqual(engine.status(identifier)["phase"], "planning")
        self.assertEqual(len(engine.status(identifier).get("replan_history", [])), 1)
        before_resume_astra = roles.astra_invocation_count
        with patch.object(FactoryEngine, "_record_approved_criteria", return_value=None):
            with self.assertRaisesRegex(FactoryError, "cannot produce a ready task"):
                engine.execute(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(roles.astra_invocation_count, before_resume_astra + 2)
        self.assertEqual(len(engine.status(identifier).get("replan_history", [])), 2)
        with self.assertRaisesRegex(FactoryError, "blocked run"):
            engine.resume(identifier)
        self.assertEqual(roles.astra_invocation_count, before_resume_astra + 2)

    def test_replan_budget_survives_two_crashes_after_astra_responses(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        original_planning = engine._perform_planning
        crashed = {"count": 0}

        def plan_then_crash(*args, **kwargs):
            result = original_planning(*args, **kwargs)
            if kwargs.get("replan_reason") and crashed["count"] < 2:
                crashed["count"] += 1
                raise KeyboardInterrupt("crash after Astra response")
            return result

        with patch.object(FactoryEngine, "_record_approved_criteria", return_value=None), patch.object(
            engine, "_perform_planning", side_effect=plan_then_crash
        ):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
            self.assertEqual(engine.status(identifier)["phase"], "planned")
            self.assertTrue((self.state_root / identifier / "replan_dispatch_1.json").is_file())
            with self.assertRaises(KeyboardInterrupt):
                engine.execute(identifier)
        self.assertEqual(crashed["count"], 2)
        self.assertTrue((self.state_root / identifier / "replan_dispatch_2.json").is_file())
        before_third_execute = roles.astra_invocation_count
        with patch.object(FactoryEngine, "_record_approved_criteria", return_value=None):
            with self.assertRaisesRegex(FactoryError, "replan budget exhausted"):
                engine.execute(identifier)
        self.assertEqual(roles.astra_invocation_count, before_third_execute)
        self.assertEqual(engine.status(identifier)["phase"], "blocked")
        with self.assertRaisesRegex(FactoryError, "blocked run"):
            engine.execute(identifier)
        self.assertEqual(roles.astra_invocation_count, before_third_execute)

    def test_repeated_ambiguous_failure_blocks_without_luna_dispatch(self):
        roles, builder = FakeRoles(), FakeBuilder(always_bad=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.max_debug_attempts = 2
        identifier = "ambiguous-repair"
        run_dir = self.state_root / identifier
        run_dir.mkdir(parents=True)
        base = cmd(["git", "rev-parse", "HEAD"], self.repo)
        atomic_json(
            run_dir / "run_state.json",
            {
                "schema_version": 3,
                "run_config_version": 2,
                "builder_backend": "agy",
                "builder_contract_version": 1,
                "run_id": identifier,
                "phase": "planned",
                "config": asdict(config),
                "base_commit": base,
                "source_head_before": base,
                "source_guard_paths": ["calc.py", "test_calc.py"],
                "source_allowed_status_before": "",
                "objective_class": "capability_growth",
            },
        )
        plan = {
            "objective": "make value return two",
            "allowed_files": ["calc.py", "test_calc.py"],
            "implementation_steps": ["Change value to return two"],
            "acceptance_criteria": ["The unit test passes"],
        }
        with self.assertRaisesRegex(FactoryError, "made no progress|AGY repair budget"):
            engine._execute_one_task(
                identifier,
                plan,
                None,
                perform_preflight=False,
                finalize_run=True,
            )

        state = engine.status(identifier)
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["error_category"], "blocked")
        self.assertEqual(state["luna_invocation_count"], 0)
        self.assertEqual(roles.luna_invocation_count, 0)
        self.assertNotIn("Luna", roles.role_calls)
        self.assertNotIn("Luna Debugger", roles.role_calls)
        blocked = json.loads((self.state_root / identifier / "repair_blocked.json").read_text())
        self.assertIn("made no progress", blocked["reason"])
        self.assertGreaterEqual(len(blocked["attempts"]), 2)
        self.assertEqual(blocked["luna_invocation_count"], 0)

    def test_exhausted_agy_attempt_budget_blocks_without_astra_or_luna_rescue(self):
        roles, builder = FakeRoles(reject_always=True), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.max_review_cycles = 0
        identifier = engine.plan(config)
        with self.assertRaisesRegex(FactoryError, "task attempt budget exhausted"):
            engine.execute(identifier)

        state = engine.status(identifier)
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["error_category"], "blocked")
        self.assertEqual(state["astra_invocation_count"], 1)
        self.assertEqual(state["luna_invocation_count"], 0)
        self.assertEqual(state["current_task_attempts"], 12)
        self.assertGreaterEqual(len(roles.review_hashes), 4)
        self.assertTrue((self.state_root / identifier / "repair_blocked.json").is_file())

    def test_progressing_sol_rejections_are_allowed_until_agy_attempt_budget(self):
        roles = FakeRoles(reject_always=True)
        builder = ProgressingReviewBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        config = self.config()
        config.max_task_attempts = 5
        identifier = engine.plan(config)
        with self.assertRaisesRegex(FactoryError, "task attempt budget exhausted"):
            engine.execute(identifier)
        state = engine.status(identifier)
        self.assertEqual(state["phase"], "blocked")
        self.assertEqual(state["current_task_attempts"], 5)
        self.assertGreaterEqual(len(roles.review_hashes), 4)
        self.assertEqual(roles.astra_invocation_count, 1)
        self.assertEqual(roles.luna_invocation_count, 0)

    def test_resume_replans_same_run_after_planning_preflight_recovers(self):
        roles = RecoveringRoles()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=FakeBuilder())
        with self.assertRaisesRegex(FactoryError, "Sol temporarily unavailable"):
            engine.plan(self.config())
        run_dirs = [path for path in self.state_root.iterdir() if path.is_dir()]
        self.assertEqual(len(run_dirs), 1)
        identifier = run_dirs[0].name
        self.assertFalse((run_dirs[0] / "master_plan.json").exists())

        roles.sol_available = True
        state = engine.resume(identifier)
        self.assertEqual(state["run_id"], identifier)
        self.assertEqual(state["phase"], "complete")

    def test_sol_cannot_expand_user_file_boundary(self):
        roles = FakeRoles(plan_files=["calc.py", "outside.py"])
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=FakeBuilder())
        with self.assertRaisesRegex(FactoryError, "expanded beyond user"):
            engine.plan(self.config())
        states = list(self.state_root.glob("*/run_state.json"))
        self.assertEqual(len(states), 1)
        self.assertEqual(json.loads(states[0].read_text())["error_category"], "scope")

    def test_symlink_allowed_file_is_rejected_before_planning(self):
        external = self.root / "external.py"
        external.write_text("secret = True\n", encoding="utf-8")
        (self.repo / "link.py").symlink_to(external)
        config = self.config()
        config.requested_files = ["link.py"]
        roles = FakeRoles(plan_files=["link.py"])
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=FakeBuilder())
        with self.assertRaisesRegex(FactoryError, "symlink"):
            engine.plan(config)
        self.assertEqual(external.read_text(encoding="utf-8"), "secret = True\n")

    def test_role_process_is_fresh_safe_and_toolless(self):
        role = HermesRoleClient("/fake/hermes")
        run_dir = self.root / "role"
        run_dir.mkdir()
        usage = run_dir / "usage.json"
        output = run_dir / "output.txt"

        def fake_command(argv, **kwargs):
            atomic_json(
                usage,
                {"model": "openai/gpt-5.6-sol", "provider": "openrouter", "completed": True, "failed": False},
            )
            return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")

        with patch("hermes_factory_v2.command", side_effect=fake_command) as invoked:
            self.assertEqual(
                role.call(
                    role="Sol",
                    provider="openrouter",
                    model="openai/gpt-5.6-sol",
                    prompt="test",
                    usage_path=usage,
                    output_path=output,
                    timeout=30,
                ),
                {"ok": True},
            )
        argv = invoked.call_args.args[0]
        self.assertIn("--safe-mode", argv)
        self.assertEqual(argv[argv.index("--toolsets") + 1], "bot_room")
        self.assertEqual(invoked.call_args.kwargs["cwd"], run_dir)

    def test_planning_reads_committed_head_and_preserves_dirty_checkout(self):
        (self.repo / "calc.py").write_text("def value():\n    return 99\n", encoding="utf-8")
        roles = FakeRoles()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=FakeBuilder())
        identifier = engine.plan(self.config())
        context = json.loads((self.state_root / identifier / "repo_context.json").read_text())
        self.assertEqual(context["source"], "committed HEAD tree")
        self.assertIn("return 1", context["file_excerpts"]["calc.py"])
        self.assertNotIn("return 99", roles.planner_prompt)
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertIn("candidate_source_context", roles.reviewer_prompts[0])
        self.assertIn("return 2", roles.reviewer_prompts[0])
        self.assertNotIn("return 99", roles.reviewer_prompts[0])
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), "def value():\n    return 99\n")

    def test_unrelated_active_checkout_edit_does_not_block_task(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        unrelated = self.repo / "notes.txt"
        unrelated.write_text("user work in progress\n", encoding="utf-8")
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "user work in progress\n")

    def test_file_tree_skeleton_index_in_planner_context(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        context = json.loads((self.state_root / identifier / "repo_context.json").read_text())
        self.assertIn("file_tree_skeleton", context)
        skeleton = context["file_tree_skeleton"]
        self.assertIn("calc.py", skeleton)
        self.assertIn("test_calc.py", skeleton)

    def test_file_tree_skeleton_handles_special_characters_without_stripping(self):
        # Commit a file with special characters (Unicode, quotes, tabs in git)
        special_file = self.repo / "my_dir" / "tést_special#1.py"
        special_file.parent.mkdir(parents=True, exist_ok=True)
        special_file.write_text("# special\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "add special file"], cwd=self.repo, check=True)

        from hermes_factory_v2 import build_file_tree_skeleton
        skeleton = build_file_tree_skeleton(self.repo)
        self.assertIn("my_dir", skeleton)
        self.assertIn("tést_special#1.py", skeleton)

    def test_review_source_context_budget_is_soft_for_affected_files(self):
        self.repo.joinpath("calc.py").write_text("# context\n" + ("value = 2\n" * 7_001), encoding="utf-8")
        self.repo.joinpath("a.py").write_text("a = 1\n", encoding="utf-8")
        self.repo.joinpath("z.py").write_text("z = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "calc.py", "a.py", "z.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "large affected fixture"], cwd=self.repo, check=True)
        run_dir = self.state_root / "context"
        run_dir.mkdir(parents=True)
        candidate_id = cmd(["git", "rev-parse", "HEAD^{tree}"], self.repo)
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())
        context = engine._candidate_source_context(
            self.repo,
            ["calc.py", "a.py", "z.py"],
            ["calc.py"],
            candidate_id,
            run_dir,
            1,
        )
        self.assertGreater(context["context_chars"], context["preferred_context_budget_chars"])
        self.assertTrue(context["soft_budget_exceeded"])
        self.assertFalse(context["files"]["calc.py"]["truncated"])
        self.assertEqual(context["omitted_paths"], ["a.py", "z.py"])
        self.assertTrue(context["files"]["z.py"]["omitted"])

    def test_evidence_packet_generated_for_reviewer_and_agy_repair(self):
        roles, builder = FakeRoles(), FakeBuilder(initial_bad=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(roles.astra_invocation_count, 1)
        run_dir = self.state_root / identifier
        repair_evidence = json.loads((run_dir / "repair_evidence.json").read_text())
        self.assertEqual(repair_evidence["luna_invocation_count"], 0)
        self.assertEqual(len(repair_evidence["attempts"]), 1)
        review_pkt_path = run_dir / "evidence_packet_review_1.json"
        self.assertTrue(review_pkt_path.is_file())
        review_pkt = json.loads(review_pkt_path.read_text())
        self.assertEqual(review_pkt["packet_type"], "review_evidence")
        self.assertTrue(review_pkt["scope_boundary"]["is_confined"])

    def test_artifact_warm_start_and_safe_rollback(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertIn("checkpoints", state)
        self.assertIn("initial", state["checkpoints"])

        # Test safe rollback logic
        worktree = self.state_root / identifier / "rollback_test_wt"
        cmd(["git", "worktree", "add", str(worktree), "HEAD"], self.repo)
        cp = engine._create_checkpoint(worktree, self.state_root / identifier, "test_cp")
        (worktree / "calc.py").write_text("def corrupted(): pass\n", encoding="utf-8")
        self.assertIn("def corrupted", (worktree / "calc.py").read_text(encoding="utf-8"))
        engine._safe_rollback(worktree, cp, self.state_root / identifier)
        self.assertNotIn("def corrupted", (worktree / "calc.py").read_text(encoding="utf-8"))
        cmd(["git", "worktree", "remove", "--force", str(worktree)], self.repo)

    def test_deterministic_pre_review_gate_blocks_syntax_error(self):
        roles = FakeRoles()
        builder = FakeBuilder(syntax_error=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        cfg = self.config()
        cfg.test_command = f'"{sys.executable}" -c "exit(0)"'
        identifier = engine.plan(cfg)
        with self.assertRaisesRegex(FactoryError, "syntax error in calc.py"):
            engine.execute(identifier)
        self.assertEqual(len(roles.reviewer_prompts), 0)

    def test_deterministic_pre_review_gate_blocks_conflict_markers(self):
        roles = FakeRoles()
        builder = FakeBuilder(conflict_marker=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        cfg = self.config()
        cfg.test_command = f'"{sys.executable}" -c "exit(0)"'
        identifier = engine.plan(cfg)
        with self.assertRaisesRegex(FactoryError, "merge conflict markers"):
            engine.execute(identifier)
        self.assertEqual(len(roles.reviewer_prompts), 0)

    def test_classifier_growth_vs_repair_and_mixed_policy(self):
        pure_repair = classify_objective("Fix calculation bug in calc.py")
        self.assertEqual(pure_repair["classification"], "repair")
        self.assertEqual(pure_repair["policy"], "pure_repair")

        pure_growth = classify_objective("Add multiplication feature to calc.py")
        self.assertEqual(pure_growth["classification"], "capability_growth")
        self.assertEqual(pure_growth["policy"], "pure_growth")

        mixed = classify_objective("Fix division error and add exponentiation feature")
        self.assertEqual(mixed["classification"], "capability_growth")
        self.assertEqual(mixed["policy"], "mixed_growth_precedence")
        self.assertIn("error", mixed["repair_signals"])
        self.assertIn("add", mixed["growth_signals"])

        default_growth = classify_objective("Make value return two")
        self.assertEqual(default_growth["classification"], "capability_growth")
        self.assertEqual(default_growth["policy"], "default_forward_progress")

    def test_issue_ledger_and_trajectory_created_on_run(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")

        ledger_dir = self.state_root / identifier / "ledger"
        self.assertTrue((ledger_dir / "issue_ledger.json").is_file())
        self.assertTrue((ledger_dir / "trajectory.json").is_file())

        ledger = json.loads((ledger_dir / "issue_ledger.json").read_text())
        trajectory = json.loads((ledger_dir / "trajectory.json").read_text())

        self.assertEqual(ledger["run_id"], identifier)
        self.assertEqual(trajectory["run_id"], identifier)
        self.assertEqual(ledger["sync_seq"], trajectory["sync_seq"])
        self.assertEqual(ledger["root_objective_class"], "capability_growth")

        phases = [ev["phase"] for ev in trajectory["events"]]
        self.assertIn("preflight", phases)
        self.assertIn("planning", phases)
        self.assertIn("build", phases)
        self.assertIn("test", phases)
        self.assertIn("review", phases)
        self.assertIn("commit", phases)

    def test_issue_lifecycle_deduplication_and_no_premature_closing(self):
        roles, builder = FakeRoles(), FakeBuilder(initial_bad=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)
        self.assertEqual(state["phase"], "complete")

        ledger_dir = self.state_root / identifier / "ledger"
        ledger = json.loads((ledger_dir / "issue_ledger.json").read_text())

        # Issues should have been recorded for test failure and then resolved upon test pass
        self.assertGreater(ledger["summary"]["total"], 0)
        self.assertEqual(ledger["summary"]["open"], 0)
        self.assertEqual(ledger["summary"]["resolved"], ledger["summary"]["total"])

        for issue in ledger["issues"]:
            self.assertEqual(issue["status"], "resolved")
            self.assertIsNotNone(issue["resolution_evidence"])
            self.assertTrue(issue["resolution_evidence"]["passed"])

    def test_snapshot_mismatch_detected(self):
        roles, builder = FakeRoles(), FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        state = engine.execute(identifier)

        ledger_dir = self.state_root / identifier / "ledger"
        traj_path = ledger_dir / "trajectory.json"
        traj_data = json.loads(traj_path.read_text())
        traj_data["sync_seq"] = 99999
        traj_path.write_text(json.dumps(traj_data))

        consistent, reason = MemoryLedger.check_snapshot_consistency(ledger_dir)
        self.assertFalse(consistent)
        self.assertIn("snapshot sequence mismatch", reason)

    def test_ledger_and_trajectory_preserved_on_failed_or_blocked_run(self):
        roles, builder = FakeRoles(), FakeBuilder(violate_scope=True)
        engine = FactoryEngine(state_root=self.state_root, role_client=roles, builder=builder)
        identifier = engine.plan(self.config())
        with self.assertRaisesRegex(FactoryError, "scope violation"):
            engine.execute(identifier)

        ledger_dir = self.state_root / identifier / "ledger"
        self.assertTrue((ledger_dir / "issue_ledger.json").is_file())
        self.assertTrue((ledger_dir / "trajectory.json").is_file())

        trajectory = json.loads((ledger_dir / "trajectory.json").read_text())
        last_event = trajectory["events"][-1]
        self.assertEqual(last_event["phase"], "failed")
        self.assertEqual(last_event["result"], "scope")

    def test_prior_run_validation_errors(self):
        engine = FactoryEngine(state_root=self.state_root, role_client=FakeRoles(), builder=FakeBuilder())

        # 1. Non-existent prior run
        cfg_nonexistent = self.config()
        cfg_nonexistent.prior_run = "nonexistent-run-99"
        with self.assertRaisesRegex(FactoryError, "directory does not exist"):
            engine.plan(cfg_nonexistent)

        # 2. Unsafe prior run path
        cfg_unsafe = self.config()
        cfg_unsafe.prior_run = "../escaped_dir"
        with self.assertRaisesRegex(FactoryError, "invalid prior run id"):
            engine.plan(cfg_unsafe)

        # 3. Mismatched repo
        id1 = engine.plan(self.config())
        state_file = self.state_root / id1 / "run_state.json"
        state_data = json.loads(state_file.read_text())
        state_data["config"]["repo"] = str(self.root / "other_repo")
        state_file.write_text(json.dumps(state_data))

        cfg_diff_repo = self.config()
        cfg_diff_repo.prior_run = id1
        with self.assertRaisesRegex(FactoryError, "repository mismatch"):
            engine.plan(cfg_diff_repo)

    def test_prior_run_progressive_disclosure_context_passed_to_planner(self):
        roles1 = FakeRoles(reject_first=True)
        builder1 = FakeBuilder()
        engine = FactoryEngine(state_root=self.state_root, role_client=roles1, builder=builder1)
        id1 = engine.plan(self.config())
        engine.execute(id1)

        # Ensure ledger has issues recorded in run 1
        ledger_dir1 = self.state_root / id1 / "ledger"
        ledger1 = json.loads((ledger_dir1 / "issue_ledger.json").read_text())
        self.assertGreater(len(ledger1["issues"]), 0)

        # Run 2 referencing prior run id1
        roles2 = FakeRoles()
        engine2 = FactoryEngine(state_root=self.state_root, role_client=roles2, builder=builder1)
        cfg2 = self.config()
        cfg2.prior_run = id1
        cfg2.request = "Add documentation comments to calc.py"
        id2 = engine2.plan(cfg2)

        # Planner in Run 2 should receive prior_run_context
        self.assertIn("prior_run_context", roles2.planner_prompt)
        self.assertIn(id1, roles2.planner_prompt)
        self.assertIn("Historical context only", roles2.planner_prompt)
        self.assertIn("CAPABILITY_GROWTH", roles2.planner_prompt)

        # Seed a second distinct issue in prior run to test truncation
        run1_ledger = MemoryLedger(self.state_root / id1, id1, str(self.repo), "capability_growth")
        run1_ledger.record_or_update_issue(
            source="Test Runner",
            title="Second issue for truncation test",
            description="Additional issue to trigger truncation",
            status="open",
        )

        # Test truncation when issues exceed limit
        ctx = load_prior_run_context(self.state_root, self.repo, id1, max_issues=1)
        self.assertTrue(ctx["truncated"])
        self.assertIsNotNone(ctx["truncation_notice"])
        self.assertEqual(len(ctx["selected_issues"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
