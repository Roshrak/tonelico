"""Run the one final finding-only recheck for FINAL-F001 and FINAL-F002."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
BASE = "400ec160f4e9cdf12cc986079fd64db7c12676ab"
PLAN = Path(r"C:\Users\HH18\softfac_v2_hoh_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
PREDECESSOR = Path(r"C:\Users\HH18\sol_final_delta_f001_f002_verdict.json")
RAW = Path(r"C:\Users\HH18\sol_final_delta_f001_f002.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_final_delta_f001_f002.stderr.txt")
VERDICT = Path(r"C:\Users\HH18\sol_final_delta_f001_f002_verdict.json")
TEST_TRANSCRIPT = Path(r"C:\Users\HH18\sol_final_delta_f001_f002_tests.txt")
VALIDATOR = Path(r"C:\Users\HH18\validate_sol_review_protocol.py")
TARGETS = {"FINAL-F001", "FINAL-F002"}


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(WORKTREE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(WORKTREE), *args])


def candidate() -> tuple[str, str, str, list[dict[str, str]]]:
    if git("rev-parse", "HEAD").stdout.strip() != BASE:
        raise SystemExit("final delta base changed")
    if git("diff", "--quiet").returncode != 0:
        raise SystemExit("final delta has unstaged changes")
    untracked = [
        path for path in git("ls-files", "--others", "--exclude-standard").stdout.splitlines() if path
    ]
    if untracked:
        raise SystemExit(f"final delta has untracked paths: {untracked}")
    changed = sorted(
        path.replace("\\", "/")
        for path in git("diff", "--cached", "--name-only").stdout.splitlines()
        if path
    )
    expected_paths = sorted(
        [
            "SHA256SUMS",
            "docs/agy-migration-acceptance.md",
            "lib/hermes_factory_v2.py",
            "tests/test_factory_resume_contract.py",
            "tests/test_factory_v2.py",
        ]
    )
    if changed != expected_paths:
        raise SystemExit(f"final delta paths differ: {changed}")
    if git("diff", "--cached", "--check").returncode != 0:
        raise SystemExit("git diff --cached --check failed")

    manifest = git_bytes("show", ":SHA256SUMS").decode("utf-8")
    mismatches = []
    for line in manifest.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise SystemExit(f"invalid checksum manifest line: {line!r}")
        expected, path = match.groups()
        actual = hashlib.sha256(git_bytes("show", f":{path}")).hexdigest()
        if actual != expected:
            mismatches.append((path, expected, actual))
    if mismatches:
        raise SystemExit(f"index checksum mismatch: {mismatches}")

    tree = git("write-tree").stdout.strip()
    diff_bytes = git_bytes("diff", "--cached", "--binary", "--no-ext-diff")
    files = [
        {"path": path, "sha256": hashlib.sha256(git_bytes("show", f":{path}")).hexdigest()}
        for path in changed
    ]
    return tree, hashlib.sha256(diff_bytes).hexdigest(), diff_bytes.decode("utf-8", errors="replace"), files


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
        ["uv", "run", "pytest", "tests", "-q"],
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


def compact_predecessor() -> dict[str, object]:
    value = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("predecessor review is not an object")
    return {
        "review_type": value.get("review_type"),
        "step": value.get("step"),
        "verdict": value.get("verdict"),
        "step_status": value.get("step_status"),
        "authorized_for_next_step": value.get("authorized_for_next_step"),
        "release_status": value.get("release_status"),
        "authorized_for_release": value.get("authorized_for_release"),
        "candidate_identity": value.get("candidate_identity"),
        "checklist": value.get("checklist"),
        "blocking_findings": value.get("blocking_findings"),
        "resolved_finding_ids": [
            item.get("finding_id")
            for item in value.get("resolved_findings", [])
            if isinstance(item, dict)
        ],
    }


def main() -> int:
    tree, diff_sha, diff_text, staged_files = candidate()
    test_output, test_exit = run_tests()
    if test_exit != 0:
        print(test_output, end="")
        return test_exit or 1
    tracked_bytecode = [
        path
        for path in git("ls-files").stdout.splitlines()
        if path.endswith(".pyc") or "/__pycache__/" in path
    ]
    filesystem_bytecode = []
    for root, directories, filenames in os.walk(WORKTREE):
        directories[:] = [directory for directory in directories if directory != ".git"]
        filesystem_bytecode.extend(
            str(Path(root, filename))
            for filename in filenames
            if filename.endswith(".pyc")
        )
    if tracked_bytecode or filesystem_bytecode:
        raise SystemExit(f"bytecode gate failed: {tracked_bytecode}, {filesystem_bytecode}")

    packet = {
        "review_type": "DELTA_ONLY_RECHECK",
        "step": 7,
        "target_findings": sorted(TARGETS),
        "base_commit": BASE,
        "head_commit": BASE,
        "tree_oid": tree,
        "diff_sha256": diff_sha,
        "staged_files": staged_files,
        "test_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 uv run pytest tests -q",
        "test_exit_code": test_exit,
        "test_output_sha256": hashlib.sha256(test_output.encode("utf-8")).hexdigest(),
        "test_output": test_output,
        "checksum_manifest": "index-to-index",
        "tracked_bytecode": tracked_bytecode,
        "filesystem_bytecode": filesystem_bytecode,
        "predecessor": compact_predecessor(),
    }
    prompt = f"""You are Sol, the independent fail-closed final reviewer for SoftFac v2.

This is exactly one finding-only recheck:
review_type = DELTA_ONLY_RECHECK
step = 7
target_findings = [FINAL-F001, FINAL-F002]

The predecessor is the protocol-valid FINAL-F001/FINAL-F002
DELTA_ONLY_RECHECK immediately before this bounded repair. It had exactly
FINAL-F001 and FINAL-F002 OPEN; all other requirements and resolved findings
are frozen. Review only whether those two findings are closed by the current
exact staged delta. Do not perform another integrated review, do not reopen
resolved findings without concrete regression evidence, and do not demand
unrelated architecture, external audit infrastructure, Git trailers,
signatures, Luna, deployment, or a new runtime version.

FINAL-F001 required correction:
Allow a verified exceptional replan to replace the active task contract under
the same stable task_id when the active assumption is disproved. Compare
immutable task fields only for completed tasks; preserve current_task_attempts
and completed history. The current candidate adds a deterministic integration
test for this exact path.

FINAL-F002 required correction:
Close the check-then-git-commit TOCTOU in normal and pending reconciliation
paths. Form the commit from the recorded candidate tree and approved parent,
never from mutable index contents, and advance the candidate ref with an
expected-old-value CAS. Detect an index/base mutation before ref advancement
and fail closed without creating or advancing to an unapproved commit. The
current candidate uses commit-tree plus update-ref CAS, holds Git's standard
index lock across the final validation/ref update transaction, and adds normal
and resume injected races at both commit-tree and update-ref boundaries.

AUTHORITATIVE REPLACEMENT PLAN
{PLAN.read_text(encoding="utf-8")}

SOL CONSTITUTION
{CONSTITUTION.read_text(encoding="utf-8")}

PREDECESSOR REVIEW SUMMARY
{json.dumps(packet["predecessor"], indent=2, ensure_ascii=False)}

CURRENT EXACT PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

CURRENT COMPLETE STAGED DELTA
{diff_text}

The exact candidate is the staged tree at:
{WORKTREE}
The staged identity above is authoritative. The complete committed product is
also available for inspection at HEAD in that worktree.

Return only one strict JSON object and no prose or markdown:
{{
  "review_type": "DELTA_ONLY_RECHECK",
  "step": 7,
  "verdict": "APPROVE or REJECT",
  "step_status": "PASS or FAIL",
  "authorized_for_next_step": true,
  "release_status": "PASS or FAIL",
  "authorized_for_release": true,
  "candidate_identity": {{"base_commit":"...","head_commit":"...","tree_oid":"...","diff_sha256":"..."}},
  "checklist": [],
  "blocking_findings": [],
  "resolved_findings": [],
  "non_blocking_findings": [],
  "precedent_corrections": [],
  "next_actions": []
}}

An APPROVE must have no blocking findings, PASS status, authorized_for_next_step
true, release_status PASS, and authorized_for_release true. A REJECT must be
FAIL/unauthorized and may contain blocking findings only for FINAL-F001 or
FINAL-F002, with all code-specific fields required by protocol.
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
        [sys.executable, str(VALIDATOR), "--step", "7"],
        input=json.dumps(verdict, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if protocol.returncode != 0:
        print(protocol.stdout or protocol.stderr, file=sys.stderr)
        return protocol.returncode or 1
    identity = verdict.get("candidate_identity", {})
    if (
        verdict.get("review_type") != "DELTA_ONLY_RECHECK"
        or verdict.get("step") != 7
        or identity.get("base_commit") != BASE
        or identity.get("head_commit") != BASE
        or identity.get("tree_oid") != tree
        or identity.get("diff_sha256") != diff_sha
    ):
        raise SystemExit("final delta Sol candidate identity mismatch")
    if verdict["verdict"] == "APPROVE":
        if (
            verdict["step_status"] != "PASS"
            or verdict["authorized_for_next_step"] is not True
            or verdict.get("release_status") != "PASS"
            or verdict.get("authorized_for_release") is not True
            or verdict["blocking_findings"]
        ):
            raise SystemExit("contradictory final delta APPROVE")
    elif verdict["verdict"] == "REJECT":
        if verdict["step_status"] != "FAIL" or verdict["authorized_for_next_step"] is not False:
            raise SystemExit("contradictory final delta REJECT")
        finding_ids = {finding.get("finding_id") for finding in verdict["blocking_findings"]}
        if not finding_ids or not finding_ids.issubset(TARGETS):
            raise SystemExit(f"unexpected final delta finding IDs: {finding_ids}")
    else:
        raise SystemExit("invalid final delta verdict")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
