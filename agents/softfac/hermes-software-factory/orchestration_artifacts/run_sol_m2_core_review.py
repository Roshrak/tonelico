"""Run the single M2-Core LARGE_STEP_REVIEW after deterministic gates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
BASE = "0a2e4ef97e22acdddbd11515353c66c09169b5b4"
ALLOWED = [
    "lib/hermes_factory_v2.py",
    "tests/test_factory_config.py",
    "tests/test_factory_resume_contract.py",
    "tests/test_factory_v2.py",
]
RAW = Path(r"C:\Users\HH18\sol_m2_core.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_m2_core.stderr.txt")
VERDICT = Path(r"C:\Users\HH18\sol_m2_core_verdict.json")
TEST_TRANSCRIPT = Path(r"C:\Users\HH18\sol_m2_core_tests.txt")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(WORKTREE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def main() -> int:
    if git("rev-parse", "HEAD").stdout.strip() != BASE:
        raise SystemExit("M2 candidate base changed")
    if git("diff", "--quiet").returncode != 0:
        raise SystemExit("M2 candidate has unstaged changes")
    untracked = [p for p in git("ls-files", "--others", "--exclude-standard").stdout.splitlines() if p]
    if untracked:
        raise SystemExit(f"M2 candidate has untracked files: {untracked}")
    changed = [p for p in git("diff", "--cached", "--name-only").stdout.splitlines() if p]
    if changed != ALLOWED:
        raise SystemExit(f"M2 changed paths differ: {changed}")
    diff_check = git("diff", "--cached", "--check")
    if diff_check.returncode != 0:
        raise SystemExit(diff_check.stderr or diff_check.stdout)
    tree = git("write-tree").stdout.strip()
    staged_diff = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", "--cached", "--binary", "--no-ext-diff"]
    )
    diff_sha = hashlib.sha256(staged_diff).hexdigest()
    env = os.environ.copy()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    tests = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "tests"],
        cwd=WORKTREE,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    transcript = (tests.stdout or "") + ("\n" + tests.stderr if tests.stderr else "")
    TEST_TRANSCRIPT.write_text(transcript, encoding="utf-8")
    if tests.returncode != 0:
        print(transcript, end="")
        return tests.returncode or 1
    packet = {
        "review_type": "LARGE_STEP_REVIEW",
        "milestone": "M2-Core",
        "step": 8,
        "target": "Astra-once master plan plus Hermes routine execution",
        "base_commit": BASE,
        "head_commit": git("rev-parse", "HEAD").stdout.strip(),
        "tree_oid": tree,
        "diff_sha256": diff_sha,
        "changed_paths": changed,
        "test_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -B -m pytest -q tests",
        "test_exit_code": tests.returncode,
        "test_output_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
        "test_output": transcript,
        "deterministic_checkpoints": [
            {
                "id": "M2-CP1",
                "name": "plan+execute",
                "tests": [
                    "FactoryIntegrationTests.test_success_commits_reviewed_hash_and_preserves_checkout",
                ],
                "property": "Astra exactly once and stable T1,T2,T3 order",
            },
            {
                "id": "M2-CP2",
                "name": "repair+replan+resume",
                "tests": [
                    "FactoryIntegrationTests.test_m2_checkpoint_repair_recheck_keeps_astra_out_of_ordinary_repair",
                    "FactoryIntegrationTests.test_m2_checkpoint_repair_replan_resume_is_deterministic",
                ],
                "property": "ordinary repair/replan uses AGY or the existing exceptional trigger; Sol recheck does not consume AGY attempt",
            },
            {
                "id": "M2-CP3",
                "name": "candidate+commit+crash reconciliation",
                "tests": [
                    "ResumeContractTests.test_resume_reconciles_an_interrupted_exact_pending_commit",
                ],
                "property": "the shared commit gate reconciles exact parent/tree without duplicate commit",
            },
        ],
        "candidate_authority": "{base_commit, candidate_id=host git write-tree}; reviewed_diff_sha256 is diagnostic only",
        "release_checksum_note": "SHA256SUMS update is intentionally deferred to M3 release packaging; it is not an M2 runtime authority.",
    }
    prompt = f"""You are Sol, the independent senior reviewer for SoftFac v2.

Review exactly one implementation boundary:
review_type = LARGE_STEP_REVIEW
milestone = M2-Core
step = 8

Step 7 is frozen and approved at commit 0a2e4ef97e22acdddbd11515353c66c09169b5b4, tree cd135d1a157e98e79d9ce3e8b63e1df8684c65db. Do not reopen Step 7 or its resolved findings without concrete regression evidence.

M2-Core implements the approved four corrections:
1. three deterministic internal checkpoints (plan+execute, repair+replan+resume, candidate+commit+crash reconciliation) without additional Sol calls;
2. max_task_attempts default 12/configurable, counting only AGY dispatches; Sol finding-only rechecks do not consume it; stagnation remains the deterministic brake;
3. source context budgets are soft prompt-shaping preferences, with affected evidence prioritized and no hard truncation invariant;
4. reviewed_diff_sha256 is diagnostic evidence only; the sole candidate authority is the host-verified {{base_commit, candidate_id=git write-tree}} pair.

Review code quality, behavior, regression safety and the exact M2 contract. Do not demand Git trailers, transition snapshots, audit ledgers, enterprise security, new scheduler infrastructure, or Luna. Do not require release checksum updates in M2.

CURRENT PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

COMPLETE STAGED DIFF
{staged_diff.decode('utf-8', errors='replace')}

Return only one JSON object and no prose/markdown:
{{
  "review_type": "LARGE_STEP_REVIEW",
  "milestone": "M2-Core",
  "step": 8,
  "verdict": "APPROVE or REJECT",
  "step_status": "PASS or FAIL",
  "authorized_for_next_step": true,
  "candidate_identity": {{"base_commit":"...","tree_oid":"...","diff_sha256":"..."}},
  "checklist": [],
  "blocking_findings": [],
  "resolved_findings": [],
  "non_blocking_findings": [],
  "next_actions": []
}}

Every blocking finding must have a stable finding_id, status, severity, correction_class, concrete evidence, required_correction, and exact affected path/symbol. If rejecting, target only M2-Core. If approving, freeze M2 and authorize M3.
"""
    result = subprocess.run(
        ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "-m", "gpt-5.6-sol", "-c", 'model_reasoning_effort="high"', "-"],
        cwd=Path(r"C:\Users\HH18"),
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1500,
        check=False,
    )
    RAW.write_text(result.stdout or "", encoding="utf-8")
    STDERR.write_text(result.stderr or "", encoding="utf-8")
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode or 1
    try:
        verdict = json.loads((result.stdout or "").strip())
    except json.JSONDecodeError as exc:
        VERDICT.write_text(json.dumps({"protocol_error": str(exc)}, indent=2), encoding="utf-8")
        print(f"Sol returned invalid JSON: {exc}", file=sys.stderr)
        return 1
    VERDICT.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    required = {"review_type", "milestone", "step", "verdict", "step_status", "authorized_for_next_step", "candidate_identity", "checklist", "blocking_findings", "resolved_findings", "non_blocking_findings", "next_actions"}
    if set(verdict) != required:
        raise SystemExit(f"M2 Sol schema mismatch: {sorted(set(verdict) ^ required)}")
    if verdict["review_type"] != "LARGE_STEP_REVIEW" or verdict["milestone"] != "M2-Core" or verdict["step"] != 8:
        raise SystemExit("M2 Sol identity mismatch")
    identity = verdict["candidate_identity"]
    if identity.get("base_commit") != BASE or identity.get("tree_oid") != tree or identity.get("diff_sha256") != diff_sha:
        raise SystemExit("M2 Sol candidate identity mismatch")
    if verdict["verdict"] == "APPROVE":
        if verdict["step_status"] != "PASS" or verdict["authorized_for_next_step"] is not True or verdict["blocking_findings"]:
            raise SystemExit("contradictory M2 APPROVE")
    elif verdict["verdict"] == "REJECT":
        for finding in verdict["blocking_findings"]:
            for key in ("finding_id", "status", "severity", "correction_class", "concrete_evidence", "required_correction"):
                if not finding.get(key):
                    raise SystemExit(f"incomplete M2 finding: {finding}")
    else:
        raise SystemExit("invalid M2 verdict")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
