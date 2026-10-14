"""Run the single M3 LARGE_STEP_REVIEW for the exact staged candidate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
BASE = "190596c4fe74fba8a1e477a01e3ac1130e7ae65b"
PLAN = Path(r"C:\Users\HH18\softfac_v2_hoh_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
M2_APPROVAL = Path(r"C:\Users\HH18\sol_m2_core_finding_recheck_verdict.json")
STEP7_APPROVAL = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta10_retry3_verdict.json")
RAW = Path(r"C:\Users\HH18\sol_m3_large_review.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_m3_large_review.stderr.txt")
VERDICT = Path(r"C:\Users\HH18\sol_m3_large_review_verdict.json")
TEST_TRANSCRIPT = Path(r"C:\Users\HH18\sol_m3_large_review_tests.txt")
VALIDATOR = Path(r"C:\Users\HH18\validate_sol_review_protocol.py")

ALLOWED = sorted(
    {
        "README.md",
        "SHA256SUMS",
        "docs/agy-builder-contract.md",
        "docs/agy-migration-acceptance.md",
        "docs/software-factory-SKILL.md",
        "lib/hermes_factory_v2.py",
        "tests/fixtures/agy/1.2.2/preflight_evidence.json",
        "tests/test_factory_preflight.py",
    }
)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(WORKTREE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def checked_output(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(WORKTREE), *args])


def validate_candidate() -> tuple[str, str, str, list[dict[str, str]]]:
    if git("rev-parse", "HEAD").stdout.strip() != BASE:
        raise SystemExit("M3 candidate base changed")
    if git("diff", "--quiet").returncode != 0:
        raise SystemExit("M3 candidate has unstaged changes")
    untracked = [
        path for path in git("ls-files", "--others", "--exclude-standard").stdout.splitlines() if path
    ]
    if untracked:
        raise SystemExit(f"M3 candidate has untracked files: {untracked}")
    changed = sorted(
        path.replace("\\", "/")
        for path in git("diff", "--cached", "--name-only").stdout.splitlines()
        if path
    )
    if changed != ALLOWED:
        raise SystemExit(f"M3 changed paths differ: {changed}")
    diff_check = git("diff", "--cached", "--check")
    if diff_check.returncode != 0:
        raise SystemExit(diff_check.stderr or diff_check.stdout)

    manifest = checked_output("show", ":SHA256SUMS").decode("utf-8")
    mismatches: list[dict[str, str]] = []
    for line in manifest.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise SystemExit(f"invalid index checksum manifest line: {line!r}")
        expected, path = match.groups()
        actual = hashlib.sha256(checked_output("show", f":{path}")).hexdigest()
        if actual != expected:
            mismatches.append({"path": path, "expected": expected, "actual": actual})
    if mismatches:
        raise SystemExit(f"index checksum verification failed: {mismatches}")

    tree = git("write-tree").stdout.strip()
    diff_bytes = checked_output("diff", "--cached", "--binary", "--no-ext-diff")
    diff_sha = hashlib.sha256(diff_bytes).hexdigest()
    files: list[dict[str, str]] = []
    for path in changed:
        data = checked_output("show", f":{path}")
        files.append({"path": path, "sha256": hashlib.sha256(data).hexdigest()})
    return tree, diff_sha, diff_bytes.decode("utf-8", errors="replace"), files


def run_tests() -> tuple[str, int]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "tests", "-q"],
        cwd=WORKTREE,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    TEST_TRANSCRIPT.write_text(output, encoding="utf-8")
    return output, result.returncode


def main() -> int:
    tree, diff_sha, diff_text, staged_files = validate_candidate()
    test_output, test_exit = run_tests()
    if test_exit != 0:
        print(test_output, end="")
        return test_exit or 1

    tracked_bytecode = [
        path
        for path in git("ls-files").stdout.splitlines()
        if path.endswith(".pyc") or "/__pycache__/" in path
    ]
    filesystem_bytecode: list[str] = []
    for root, directories, filenames in os.walk(WORKTREE):
        directories[:] = [directory for directory in directories if directory != ".git"]
        for filename in filenames:
            if filename.endswith(".pyc") or filename == "__pycache__":
                filesystem_bytecode.append(str(Path(root, filename)))
    if tracked_bytecode or filesystem_bytecode:
        raise SystemExit(
            f"bytecode gate failed: tracked={tracked_bytecode}, filesystem={filesystem_bytecode}"
        )

    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    prior = {
        "m2_core": json.loads(M2_APPROVAL.read_text(encoding="utf-8")),
        "step7": json.loads(STEP7_APPROVAL.read_text(encoding="utf-8")),
    }
    packet = {
        "review_type": "LARGE_STEP_REVIEW",
        "milestone": "M3",
        "step": 14,
        "base_commit": BASE,
        "head_commit": BASE,
        "tree_oid": tree,
        "diff_sha256": diff_sha,
        "staged_files": staged_files,
        "test_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -B -m pytest tests -q",
        "test_exit_code": test_exit,
        "test_output_sha256": hashlib.sha256(test_output.encode("utf-8")).hexdigest(),
        "test_output": test_output,
        "checksum_manifest": "index-to-index",
        "tracked_bytecode": tracked_bytecode,
        "filesystem_bytecode": filesystem_bytecode,
        "active_runtime": {
            "version": "1.2.2",
            "sha256": "80a029a8f22dccc123fd39453bd4d51c93d6384d4f365993a3d5accfa4af4b47",
            "model": "gemini-3.8-flash-high",
            "boundary": "Windows Sandbox",
        },
        "approved_prior_boundaries": prior,
    }
    prompt = f"""You are Sol, the independent senior reviewer for SoftFac v2.

Review exactly one implementation boundary:
review_type = LARGE_STEP_REVIEW
milestone = M3
step = 14

This candidate is the bounded M3 runtime/release increment after the approved
M2-Core and frozen Step 7 boundaries. Evaluate only this delta and its direct
release consequences. Do not reopen M2-Core or Step 7 without concrete,
reproducible regression evidence in this candidate. Do not demand a new
scheduler, provenance/audit platform, Git trailer, signing/HMAC/TPM, external
trust anchor, Luna runtime, deployment, or an AGY version other than the
verified installed 1.2.2 identity.

M3 change intent:
1. Promote the host-verified AGY 1.2.2 executable and exact SHA-256 as the
   active preflight pin; the old 1.2.0 fixture directory remains historical.
2. Keep the direct AGY command, candidate isolation, exact
   {{base_commit,candidate_id=git write-tree}} authority, no-Luna runtime path,
   and Hermes-only commit authority unchanged.
3. Record checked-in sanitized 1.2.2 Windows Sandbox preflight evidence and
   bind it with a deterministic test to the source pin.
4. Update only active runtime documentation and release checksum metadata;
   deployment remains separately authorized.

The candidate must be judged on code quality, correctness, safety, evidence
fidelity, documentation accuracy, regression safety, exact staged identity,
and whether the release gates are sufficient for this M3 increment. Treat
host-local AGY OAuth credentials as trusted runtime setup; no credential is in
the candidate.

AUTHORITATIVE REPLACEMENT PLAN
{plan_text}

SOL CONSTITUTION
{constitution_text}

EXACT PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

COMPLETE STAGED DIFF
{diff_text}

Return only one strict JSON object and no prose or markdown:
{{
  "review_type": "LARGE_STEP_REVIEW",
  "milestone": "M3",
  "step": 14,
  "verdict": "APPROVE or REJECT",
  "step_status": "PASS or FAIL",
  "authorized_for_next_step": true,
  "candidate_identity": {{"base_commit":"...","head_commit":"...","tree_oid":"...","diff_sha256":"..."}},
  "checklist": [],
  "blocking_findings": [],
  "resolved_findings": [],
  "non_blocking_findings": [],
  "next_actions": []
}}

Every blocking finding must include stable finding_id, status, severity,
blocking_class, contract_source, exact_requirement, concrete_evidence,
observed_state, expected_state, why_it_blocks_current_step,
required_correction, and correction_class. An APPROVE must have no blocking
findings, PASS status, and authorized_for_next_step=true. A REJECT must target
M3 only and be FAIL/unauthorized.
"""
    result = subprocess.run(
        [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "-m",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="high"',
            "-",
        ],
        cwd=Path(r"C:\Users\HH18"),
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
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
    protocol = subprocess.run(
        [sys.executable, str(VALIDATOR), "--step", "14"],
        input=json.dumps(verdict),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if protocol.returncode != 0:
        print(protocol.stdout or protocol.stderr, file=sys.stderr)
        return protocol.returncode or 1
    required = {
        "review_type",
        "milestone",
        "step",
        "verdict",
        "step_status",
        "authorized_for_next_step",
        "candidate_identity",
        "checklist",
        "blocking_findings",
        "resolved_findings",
        "non_blocking_findings",
        "next_actions",
    }
    if set(verdict) != required:
        raise SystemExit(f"M3 Sol schema mismatch: {sorted(set(verdict) ^ required)}")
    if (
        verdict["review_type"] != "LARGE_STEP_REVIEW"
        or verdict["milestone"] != "M3"
        or verdict["step"] != 14
    ):
        raise SystemExit("M3 Sol identity mismatch")
    identity = verdict["candidate_identity"]
    if (
        identity.get("base_commit") != BASE
        or identity.get("head_commit") != BASE
        or identity.get("tree_oid") != tree
        or identity.get("diff_sha256") != diff_sha
    ):
        raise SystemExit("M3 Sol candidate identity mismatch")
    if verdict["verdict"] == "APPROVE":
        if verdict["step_status"] != "PASS" or verdict["authorized_for_next_step"] is not True or verdict["blocking_findings"]:
            raise SystemExit("contradictory M3 APPROVE")
    elif verdict["verdict"] == "REJECT":
        if verdict["step_status"] != "FAIL" or verdict["authorized_for_next_step"] is not False:
            raise SystemExit("contradictory M3 REJECT")
    else:
        raise SystemExit("invalid M3 verdict")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
