"""Run exactly one bounded final delta recheck for FINAL-F005 and FINAL-F007."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
PREVIOUS_HEAD = "bbfe7a8410e79fc1460be0d92908c67776af4e1f"
PREVIOUS_TREE = "d8f425f136d7a9e010bfaf0fd494506d0cb13682"
PRIOR = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta4_verdict.json")
PLAN = Path(r"C:\Users\HH18\softfac_v2_hoh_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
RAW = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta5.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta5.stderr.txt")
USAGE = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta5_usage.json")
VERDICT = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta5_verdict.json")
VALIDATOR = Path(r"C:\Users\HH18\validate_sol_review_protocol.py")
TARGETS = ["FINAL-F005", "FINAL-F007"]


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


def staged_blob(path: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(WORKTREE), "cat-file", "blob", f":{path}"])


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
        timeout=900,
        check=False,
    )
    return (result.stdout or "") + ("\n" + result.stderr if result.stderr else ""), result.returncode


def main() -> int:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    if prior.get("review_type") != "DELTA_ONLY_RECHECK" or prior.get("step") != 7:
        raise SystemExit("previous final delta4 review is unavailable")
    if {item.get("finding_id") for item in prior.get("blocking_findings", [])} != set(TARGETS):
        raise SystemExit("previous final delta4 does not contain exactly the two remaining targets")
    if git("rev-parse", "HEAD").strip() != PREVIOUS_HEAD:
        raise SystemExit("candidate HEAD changed before final delta5")

    tree = git("write-tree").strip()
    if tree == PREVIOUS_TREE:
        raise SystemExit("final delta5 has no new candidate")
    staged_diff = subprocess.check_output(["git", "-C", str(WORKTREE), "diff", "--cached", "--binary", "--no-ext-diff"])
    repair_delta = subprocess.check_output(["git", "-C", str(WORKTREE), "diff", "--binary", "--no-ext-diff", PREVIOUS_TREE, tree])
    test_output, test_exit = run_tests()
    if test_exit != 0:
        print(test_output, end="")
        return test_exit or 1

    manifest: dict[str, str] = {}
    for line in git("show", ":SHA256SUMS").splitlines():
        if line.strip():
            digest, path = line.split(None, 1)
            manifest[path] = digest
    file_hashes = {path: hashlib.sha256(staged_blob(path)).hexdigest() for path in manifest}
    checksum_mismatches = [
        {"path": path, "expected": expected, "actual": file_hashes[path]}
        for path, expected in manifest.items()
        if file_hashes[path] != expected
    ]
    bytecode_paths = [
        path
        for path in git("ls-tree", "-r", "--name-only", tree).splitlines()
        if "/__pycache__/" in path or path.endswith(".pyc")
    ]
    diff_check = git("diff", "--cached", "--check")
    packet = {
        "review_type": "DELTA_ONLY_RECHECK",
        "step": 7,
        "target_findings": TARGETS,
        "previous_head": PREVIOUS_HEAD,
        "previous_tree": PREVIOUS_TREE,
        "head_commit": git("rev-parse", "HEAD").strip(),
        "tree_oid": tree,
        "changed_paths": [path for path in git("diff", "--cached", "--name-only").splitlines() if path],
        "staged_diff_sha256": hashlib.sha256(staged_diff).hexdigest(),
        "repair_delta_sha256": hashlib.sha256(repair_delta).hexdigest(),
        "repair_delta_length": len(repair_delta),
        "test_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -B -m pytest -q tests",
        "test_exit_code": test_exit,
        "test_output_sha256": hashlib.sha256(test_output.encode("utf-8")).hexdigest(),
        "test_output": test_output,
        "file_hashes": file_hashes,
        "checksum_entries": len(manifest),
        "checksum_mismatches": checksum_mismatches,
        "git_diff_cached_check": not diff_check,
        "bytecode_paths": bytecode_paths,
    }
    if checksum_mismatches or bytecode_paths or diff_check:
        raise SystemExit(f"candidate integrity failed: {packet}")

    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), an independent fail-closed gatekeeper.

review_type = DELTA_ONLY_RECHECK
step = 7
target_findings = FINAL-F005, FINAL-F007

The previous final review and all prior delta reviews are complete. Review only
this exact repair delta and affected evidence for FINAL-F005 and FINAL-F007.
Do not run another FINAL_INTEGRATED_REVIEW. Freeze FINAL-F001, FINAL-F002,
FINAL-F003, FINAL-F004, FINAL-F006, STEP7-F015, and every other resolved
finding unless this delta provides concrete regression evidence.

AUTHORITATIVE REPLACEMENT PLAN
{plan_text}

SOL CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

PREVIOUS FINAL DELTA4 REVIEW
{json.dumps(prior, indent=2, ensure_ascii=False)}

CURRENT PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

EXACT REPAIR DELTA ({PREVIOUS_TREE}..{tree})
{repair_delta.decode("utf-8", errors="replace")}

Verify only:
FINAL-F005: Runner result sequence, passed status, return code, normalized
command, result artifact hash, log reference and log hash are independently
bound to the exact candidate before Sol approval and before Hermes commit.
The Sol approval must copy the complete verification contract exactly. Fresh
execute, resume, and status terminal paths must reject tampered result fields,
sequence, command, log contents, artifact hashes, or review verification.
FINAL-F007: non-user replans resolve only bounded host-produced Sol/Hermes
artifacts with exact code-appropriate schemas and current run, plan, request,
base, candidate, and freshness identity. Fabricated arbitrary artifacts are
rejected without Astra invocation. USER_OBJECTIVE_OR_SCOPE_CHANGE creates and
binds a new immutable request artifact, and execute/resume/status reject its
tampering. All five trigger types remain covered; ordinary failures remain
AGY repair or BLOCKED, never Luna.

Return ONLY one compact JSON object and no prose or markdown:
{{
  "review_type": "DELTA_ONLY_RECHECK",
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
Every blocker must include all constitution-required fields, including status
and correction_class. Do not emit any text outside JSON.
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
        timeout=1500,
        check=False,
    )
    RAW.write_text(result.stdout or "", encoding="utf-8")
    STDERR.write_text(result.stderr or "", encoding="utf-8")
    USAGE.write_text(
        json.dumps(
            {"role": "Sol Reviewer", "model": "gpt-5.6-sol", "review_type": "DELTA_ONLY_RECHECK", "step": 7, "target_findings": TARGETS, "exit_code": result.returncode},
            indent=2,
        ),
        encoding="utf-8",
    )
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
