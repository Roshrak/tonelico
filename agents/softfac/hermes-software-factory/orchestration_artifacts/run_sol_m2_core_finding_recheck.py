"""Run the M2-Core finding-only recheck for the three Sol findings."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
BASE = "0a2e4ef97e22acdddbd11515353c66c09169b5b4"
PREVIOUS_TREE = "1bd19cfa43afdefa25032dba2c62f320e9335188"
PRIOR = Path(r"C:\Users\HH18\sol_m2_core_verdict.json")
RAW = Path(r"C:\Users\HH18\sol_m2_core_finding_recheck.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_m2_core_finding_recheck.stderr.txt")
VERDICT = Path(r"C:\Users\HH18\sol_m2_core_finding_recheck_verdict.json")
TEST_TRANSCRIPT = Path(r"C:\Users\HH18\sol_m2_core_finding_recheck_tests.txt")
ALLOWED = [
    "lib/hermes_factory_v2.py",
    "tests/test_factory_config.py",
    "tests/test_factory_resume_contract.py",
    "tests/test_factory_v2.py",
]
TARGETS = {"M2-S8-F001", "M2-S8-F002", "M2-S8-F003"}


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
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    if prior.get("review_type") != "LARGE_STEP_REVIEW" or prior.get("milestone") != "M2-Core":
        raise SystemExit("M2 large review predecessor is unavailable")
    if {item.get("finding_id") for item in prior.get("blocking_findings", [])} != TARGETS:
        raise SystemExit("M2 predecessor does not contain exactly the three target findings")
    if git("rev-parse", "HEAD").stdout.strip() != BASE:
        raise SystemExit("M2 base changed before finding recheck")
    if git("diff", "--quiet").returncode != 0:
        raise SystemExit("M2 finding recheck candidate has unstaged changes")
    changed = [p for p in git("diff", "--cached", "--name-only").stdout.splitlines() if p]
    if changed != ALLOWED:
        raise SystemExit(f"M2 finding recheck paths differ: {changed}")
    check = git("diff", "--cached", "--check")
    if check.returncode != 0:
        raise SystemExit(check.stderr or check.stdout)
    tree = git("write-tree").stdout.strip()
    if tree == PREVIOUS_TREE:
        raise SystemExit("M2 finding recheck has no repair delta")
    staged_diff = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", "--cached", "--binary", "--no-ext-diff"]
    )
    repair_delta = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", PREVIOUS_TREE, tree, "--binary", "--no-ext-diff"]
    )
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
        "review_type": "FINDING_ONLY_RECHECK",
        "milestone": "M2-Core",
        "step": 8,
        "target_findings": sorted(TARGETS),
        "predecessor_review": prior,
        "base_commit": BASE,
        "tree_oid": tree,
        "repair_delta_sha256": hashlib.sha256(repair_delta).hexdigest(),
        "repair_delta_length": len(repair_delta),
        "staged_diff_sha256": hashlib.sha256(staged_diff).hexdigest(),
        "changed_paths": changed,
        "test_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -B -m pytest -q tests",
        "test_exit_code": tests.returncode,
        "test_output_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
        "test_output": transcript,
        "closure_evidence": {
            "M2-S8-F001": "Progressing Sol rejections are allowed until max_task_attempts or deterministic review stagnation; review cycles no longer cap AGY repair.",
            "M2-S8-F002": "Affected source files are fully retained; preferred context budget is advisory and overflow is reported.",
            "M2-S8-F003": "Predecessor/status/evidence/target binding is enforced; AGY corrections come only from target finding records and recheck context is narrowed.",
        },
        "candidate_authority": "{base_commit, candidate_id=host git write-tree}; reviewed_diff_sha256 is diagnostic only",
    }
    prompt = f"""You are Sol, the independent senior reviewer for SoftFac v2.

review_type = FINDING_ONLY_RECHECK
milestone = M2-Core
step = 8
target_findings = M2-S8-F001, M2-S8-F002, M2-S8-F003

The M2-Core LARGE_STEP_REVIEW already happened exactly once. Recheck only those three predecessor findings, this exact repair delta, and affected deterministic evidence. Do not perform another large review. Step 7 and all other resolved findings are frozen.

F001 requires no effective max_review_cycles cap: progressing Sol rejections may continue until the AGY dispatch budget or deterministic stagnation; Sol calls do not consume AGY attempts.
F002 requires an advisory context budget: affected evidence must not be silently hard-truncated at 48,000 characters, and omission/truncation must be explicit.
F003 requires predecessor-bound finding status/evidence, concrete evidence for REGRESSED, corrections bound to target records, and a narrow finding-only packet.

The only candidate authority is {{base_commit, candidate_id from host git write-tree}}. reviewed_diff_sha256 is diagnostic evidence only.

PREDECESSOR LARGE REVIEW
{json.dumps(prior, indent=2, ensure_ascii=False)}

CURRENT PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

EXACT REPAIR DELTA ({PREVIOUS_TREE}..{tree})
{repair_delta.decode('utf-8', errors='replace')}

Return only one JSON object and no prose/markdown:
{{
  "review_type": "FINDING_ONLY_RECHECK",
  "milestone": "M2-Core",
  "step": 8,
  "target_findings": ["M2-S8-F001", "M2-S8-F002", "M2-S8-F003"],
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

APPROVE requires all three target findings resolved and no blocker. REJECT may contain only those target IDs and each blocker must include stable ID, status, severity, correction_class, concrete evidence, required_correction, affected path and affected symbol. Do not invent infrastructure or reopen Step 7.
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
    required = {"review_type", "milestone", "step", "target_findings", "verdict", "step_status", "authorized_for_next_step", "candidate_identity", "checklist", "blocking_findings", "resolved_findings", "non_blocking_findings", "next_actions"}
    if set(verdict) != required:
        raise SystemExit(f"M2 finding recheck schema mismatch: {sorted(set(verdict) ^ required)}")
    if verdict["review_type"] != "FINDING_ONLY_RECHECK" or verdict["milestone"] != "M2-Core" or verdict["step"] != 8 or set(verdict["target_findings"]) != TARGETS:
        raise SystemExit("M2 finding recheck identity mismatch")
    identity = verdict["candidate_identity"]
    if identity.get("base_commit") != BASE or identity.get("tree_oid") != tree:
        raise SystemExit("M2 finding recheck candidate identity mismatch")
    blocker_ids = {item.get("finding_id") for item in verdict["blocking_findings"]}
    if not blocker_ids.issubset(TARGETS):
        raise SystemExit(f"unexpected M2 finding blocker: {sorted(blocker_ids - TARGETS)}")
    if verdict["verdict"] == "APPROVE":
        resolved_ids = {item.get("finding_id") for item in verdict["resolved_findings"]}
        if verdict["step_status"] != "PASS" or verdict["authorized_for_next_step"] is not True or blocker_ids or not TARGETS.issubset(resolved_ids):
            raise SystemExit("contradictory M2 finding APPROVE")
    elif verdict["verdict"] == "REJECT":
        for finding in verdict["blocking_findings"]:
            required_fields = ("finding_id", "status", "severity", "correction_class", "concrete_evidence", "required_correction", "affected_path", "affected_symbol")
            if any(not finding.get(key) for key in required_fields):
                raise SystemExit(f"incomplete M2 finding: {finding}")
    else:
        raise SystemExit("invalid M2 finding verdict")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
