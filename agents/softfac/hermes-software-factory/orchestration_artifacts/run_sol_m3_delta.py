"""Run the one M3 finding-only recheck after the bounded evidence repair."""

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
PREDECESSOR = Path(r"C:\Users\HH18\sol_m3_large_review_verdict.json")
RAW = Path(r"C:\Users\HH18\sol_m3_delta.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_m3_delta.stderr.txt")
VERDICT = Path(r"C:\Users\HH18\sol_m3_delta_verdict.json")
TEST_TRANSCRIPT = Path(r"C:\Users\HH18\sol_m3_delta_tests.txt")
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


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(WORKTREE), *args])


def candidate_packet() -> tuple[str, str, str, list[dict[str, str]]]:
    if git("rev-parse", "HEAD").stdout.strip() != BASE:
        raise SystemExit("M3 delta base changed")
    if git("diff", "--quiet").returncode != 0:
        raise SystemExit("M3 delta has unstaged changes")
    untracked = [
        path for path in git("ls-files", "--others", "--exclude-standard").stdout.splitlines() if path
    ]
    if untracked:
        raise SystemExit(f"M3 delta has untracked files: {untracked}")
    changed = sorted(
        path.replace("\\", "/")
        for path in git("diff", "--cached", "--name-only").stdout.splitlines()
        if path
    )
    if changed != ALLOWED:
        raise SystemExit(f"M3 delta changed paths differ: {changed}")
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


def run_full_suite() -> tuple[str, int]:
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


def main() -> int:
    tree, diff_sha, diff_text, staged_files = candidate_packet()
    test_output, test_exit = run_full_suite()
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
        "milestone": "M3",
        "step": 14,
        "target_findings": ["M3-S14-F001"],
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
        "predecessor": json.loads(PREDECESSOR.read_text(encoding="utf-8")),
    }
    prompt = f"""You are Sol, the independent senior reviewer for SoftFac v2.

This is exactly one finding-only review:
review_type = DELTA_ONLY_RECHECK
milestone = M3
step = 14
target_findings = [M3-S14-F001]

The predecessor is the protocol-valid M3 LARGE_STEP_REVIEW immediately before
this bounded repair. It had exactly one blocking finding, M3-S14-F001, and all
other checklist requirements PASS. Review only whether that finding is
resolved by the current exact staged candidate. Preserve every predecessor
PASS and resolved/frozen boundary unless this delta contains concrete,
reproducible regression evidence. Do not perform another full M3 review.

The bounded repair changed only:
1. the inaccurate --mode declaration in the checked-in 1.2.2 preflight
   evidence fixture, to match the exact pinned executable; and
2. the acceptance record's whitespace command to the staged form.

Do not demand Git trailers, signatures, HMAC/TPM, external trust anchors,
audit ledgers, a new provenance framework, deployment, Luna, or any unrelated
architecture. Evaluate evidence fidelity, deterministic binding, candidate
identity, regression safety, and the exact target finding under the trusted
local v1 threat model.

AUTHORITATIVE REPLACEMENT PLAN
{PLAN.read_text(encoding="utf-8")}

SOL CONSTITUTION
{CONSTITUTION.read_text(encoding="utf-8")}

PREDECESSOR REVIEW
{json.dumps(packet["predecessor"], indent=2, ensure_ascii=False)}

CURRENT EXACT PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

CURRENT COMPLETE STAGED DIFF
{diff_text}

Return only one strict JSON object and no prose or markdown:
{{
  "review_type": "DELTA_ONLY_RECHECK",
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

An APPROVE must have no blocking findings, PASS status, and
authorized_for_next_step=true. A REJECT must target only M3-S14-F001 and be
FAIL/unauthorized. Every blocking finding must include all code-specific
fields required by the review protocol.
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
    identity = verdict.get("candidate_identity", {})
    if (
        verdict.get("review_type") != "DELTA_ONLY_RECHECK"
        or verdict.get("milestone") != "M3"
        or verdict.get("step") != 14
        or identity.get("base_commit") != BASE
        or identity.get("head_commit") != BASE
        or identity.get("tree_oid") != tree
        or identity.get("diff_sha256") != diff_sha
    ):
        raise SystemExit("M3 delta Sol identity mismatch")
    if verdict["verdict"] == "APPROVE":
        if verdict["step_status"] != "PASS" or verdict["authorized_for_next_step"] is not True or verdict["blocking_findings"]:
            raise SystemExit("contradictory M3 delta APPROVE")
    elif verdict["verdict"] == "REJECT":
        if verdict["step_status"] != "FAIL" or verdict["authorized_for_next_step"] is not False:
            raise SystemExit("contradictory M3 delta REJECT")
        finding_ids = {finding.get("finding_id") for finding in verdict["blocking_findings"]}
        if finding_ids != {"M3-S14-F001"}:
            raise SystemExit(f"unexpected M3 delta finding IDs: {finding_ids}")
    else:
        raise SystemExit("invalid M3 delta verdict")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
