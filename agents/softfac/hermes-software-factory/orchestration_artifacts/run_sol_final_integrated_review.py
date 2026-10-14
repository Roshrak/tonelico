"""Run the single final integrated SoftFac v2 review after Step 7 freeze."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
BASELINE = "066e885966420b14d470dc159f0ff39acf2099a9"
PLAN = Path(r"C:\Users\HH18\softfac_v2_hoh_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
FREEZE = Path(r"C:\Users\HH18\softfac_v2_step7_freeze.json")
F015_REVIEW = Path(r"C:\Users\HH18\sol_softfac_v2_f015_delta_verdict.json")
STEP7_FULL_REVIEW = Path(r"C:\Users\HH18\sol_softfac_v2_final_verdict.json")
M2_APPROVAL = Path(r"C:\Users\HH18\sol_m2_core_finding_recheck_verdict.json")
M3_LARGE_REVIEW = Path(r"C:\Users\HH18\sol_m3_large_review_verdict.json")
M3_DELTA_REVIEW = Path(r"C:\Users\HH18\sol_m3_delta_verdict.json")
RAW = Path(r"C:\Users\HH18\sol_softfac_v2_final_integrated.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_softfac_v2_final_integrated.stderr.txt")
USAGE = Path(r"C:\Users\HH18\sol_softfac_v2_final_integrated_usage.json")
VERDICT = Path(r"C:\Users\HH18\sol_softfac_v2_final_integrated_verdict.json")
VALIDATOR = Path(r"C:\Users\HH18\validate_sol_review_protocol.py")


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(WORKTREE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def run_tests() -> tuple[str, int]:
    env = os.environ.copy()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "tests"],
        cwd=WORKTREE,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    return (result.stdout or "") + ("\n" + result.stderr if result.stderr else ""), result.returncode


def compact_review(path: Path) -> dict[str, object]:
    """Retain approval identity and finding history without duplicating raw packets."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"review artifact is not an object: {path}")
    checklist = data.get("checklist", [])
    checklist_summary = [
        {
            "requirement": item.get("requirement"),
            "status": item.get("status"),
            "finding_ids": item.get("finding_ids", []),
            "resolved_finding_ids": item.get("resolved_finding_ids", []),
        }
        for item in checklist
        if isinstance(item, dict)
    ]
    return {
        "artifact": str(path),
        "review_type": data.get("review_type"),
        "milestone": data.get("milestone"),
        "step": data.get("step"),
        "verdict": data.get("verdict"),
        "step_status": data.get("step_status"),
        "authorized_for_next_step": data.get("authorized_for_next_step"),
        "release_status": data.get("release_status"),
        "authorized_for_release": data.get("authorized_for_release"),
        "candidate_identity": data.get("candidate_identity"),
        "checklist": checklist_summary,
        "blocking_finding_ids": [
            item.get("finding_id")
            for item in data.get("blocking_findings", [])
            if isinstance(item, dict)
        ],
        "resolved_finding_ids": [
            item.get("finding_id")
            for item in data.get("resolved_findings", [])
            if isinstance(item, dict)
        ],
    }


def main() -> int:
    if git("status", "--porcelain"):
        raise SystemExit("frozen worktree is not clean")
    head = git("rev-parse", "HEAD").strip()
    tree = git("rev-parse", "HEAD^{tree}").strip()
    full_diff = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", "--binary", "--no-ext-diff", BASELINE, head]
    )
    test_output, test_exit = run_tests()
    if test_exit != 0:
        print(test_output, end="")
        return test_exit or 1
    manifest_text = git("show", f"{head}:SHA256SUMS")
    manifest: dict[str, str] = {}
    for line in manifest_text.splitlines():
        if line.strip():
            digest, path = line.split(None, 1)
            manifest[path] = digest
    mismatches = []
    for path, expected in manifest.items():
        actual = hashlib.sha256(
            subprocess.check_output(
                ["git", "-C", str(WORKTREE), "cat-file", "blob", f"{head}:{path}"]
            )
        ).hexdigest()
        if actual != expected:
            mismatches.append({"path": path, "expected": expected, "actual": actual})
    bytecode_paths = [
        path for path in git("ls-tree", "-r", "--name-only", head).splitlines()
        if "/__pycache__/" in path or path.endswith(".pyc")
    ]
    packet = {
        "review_type": "FINAL_INTEGRATED_REVIEW",
        "baseline_commit": BASELINE,
        "head_commit": head,
        "tree_oid": tree,
        "full_diff_sha256": hashlib.sha256(full_diff).hexdigest(),
        "full_diff_length": len(full_diff),
        "worktree_status": git("status", "--porcelain"),
        "test_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -B -m pytest -q tests",
        "test_exit_code": test_exit,
        "test_output_sha256": hashlib.sha256(test_output.encode("utf-8")).hexdigest(),
        "test_output": test_output,
        "checksum_manifest_entries": len(manifest),
        "checksum_mismatches": mismatches,
        "git_diff_check": git("diff", "--check", BASELINE, head) == "",
        "bytecode_paths": bytecode_paths,
        "freeze_artifact": compact_review(FREEZE),
        "f015_approval": compact_review(F015_REVIEW),
        "step7_full_review_history": compact_review(STEP7_FULL_REVIEW),
        "m2_core_approval": compact_review(M2_APPROVAL),
        "m3_large_review": compact_review(M3_LARGE_REVIEW),
        "m3_delta_recheck": compact_review(M3_DELTA_REVIEW),
    }
    if mismatches or bytecode_paths or not packet["git_diff_check"]:
        raise SystemExit(f"final integrated packet integrity gate failed: {packet}")
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), the independent fail-closed final gatekeeper for SoftFac v2.

review_type = FINAL_INTEGRATED_REVIEW
step = 7

Step 7 is approved and frozen, M2-Core is approved, and M3 has passed its
LARGE_STEP_REVIEW plus one targeted DELTA_ONLY_RECHECK. This is the one and
only final integrated review. Evaluate the exact committed product end-to-end
against the authoritative replacement plan and approved baseline. Do not
perform another step-conformance or milestone review. Do not reopen resolved
Step 7, M2, or M3 findings without concrete regression evidence. Do not reject
for speculative future features or architecture outside the current plan.

AUTHORITATIVE REPLACEMENT PLAN
{plan_text}

SOL CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

EXACT FINAL PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

APPROVED BASELINE -> FROZEN FINAL CANDIDATE
BASELINE = {BASELINE}
HEAD = {head}
TREE = {tree}
DIFF SHA-256 = {hashlib.sha256(full_diff).hexdigest()}
The complete exact diff is intentionally not duplicated into this prompt due
to the Codex input limit. Inspect it directly before deciding:
git -C "{WORKTREE}" diff --binary --no-ext-diff {BASELINE} {head}
and inspect the exact committed tree with:
git -C "{WORKTREE}" ls-tree -r --name-only {head}
git -C "{WORKTREE}" show {head}:<path>
The packet's full_diff_sha256 and full_diff_length bind the bytes that the
launcher computed from those exact commits. Do not substitute another checkout
or a working-tree diff.

Final integrated checks:
1. Hermes owns execution orchestration; Astra produces the initial master plan,
   normal execution uses exactly one Astra planner invocation, and Hermes
   selects ready tasks deterministically without routine Astra calls.
2. AGY is the implementation/repair writer; Runner verification and Sol
   independent judgment sequence correctly; Runner FAIL and Sol REJECT route
   to AGY repair; stagnation/exhaustion becomes durable BLOCKED; Luna is absent
   from the production route.
3. AGY receives only the disposable non-Git mirror; source, Git metadata,
   trusted run state, credentials/config discovery, and unrelated roots remain
   protected. Concurrent candidate writes cannot be silently lost.
4. Candidate identity is exact {{base_commit,candidate_id}}, candidate_id is
   git write-tree, Sol approval and Hermes commit bind the same tree, and only
   Hermes commits.
5. Failed or malformed AGY attempts cannot synchronize rejected output; resume
   preserves progress, review rejection authority, attempt budgets, and exact
   pending-commit reconciliation.
6. COMPLETE requires all planned tasks committed, current global-criterion
   evidence, no unresolved blocking findings, and no ambiguous candidate or
   commit. Criterion freshness and distributed criteria are correct.
7. Checksum/tree identity, bytecode removal, active runtime documentation,
   legacy Aider/bridge removal, AGY 1.2.2 pin evidence, and the full
   deterministic evidence are factually correct.

Return only one compact JSON object, with no prose or markdown:
{{
  "review_type": "FINAL_INTEGRATED_REVIEW",
  "step": 7,
  "verdict": "APPROVE or REJECT",
  "step_status": "PASS or FAIL",
  "authorized_for_next_step": true,
  "release_status": "PASS or FAIL",
  "authorized_for_release": true,
  "candidate_identity": {{"base_commit": "...", "head_commit": "...", "tree_oid": "...", "diff_sha256": "..."}},
  "checklist": [],
  "blocking_findings": [],
  "resolved_findings": [],
  "non_blocking_findings": [],
  "precedent_corrections": [],
  "next_actions": []
}}
For each blocking finding include finding_id (use FINAL-F001 etc.), status,
severity, blocking_class, contract_source, exact_requirement,
concrete_evidence, observed_state, expected_state, why_it_blocks_current_step,
required_correction, and correction_class. Collect compatible final findings;
do not emit any text outside JSON.
"""
    codex = shutil.which("codex") or "codex"
    result = subprocess.run(
        [codex, "exec", "--ephemeral", "--skip-git-repo-check", "-m", "gpt-5.6-sol", "-c", 'model_reasoning_effort="high"', "-"],
        cwd=Path(r"C:\Users\HH18"),
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1200,
        check=False,
    )
    RAW.write_text(result.stdout or "", encoding="utf-8")
    STDERR.write_text(result.stderr or "", encoding="utf-8")
    USAGE.write_text(json.dumps({"role": "Sol Reviewer", "model": "gpt-5.6-sol", "review_type": "FINAL_INTEGRATED_REVIEW", "step": 7, "exit_code": result.returncode}, indent=2), encoding="utf-8")
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
    validation = subprocess.run(
        [sys.executable, "-B", str(VALIDATOR), "--step", "7"],
        input=json.dumps(verdict, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(validation.stdout, end="")
    return validation.returncode


if __name__ == "__main__":
    raise SystemExit(main())
