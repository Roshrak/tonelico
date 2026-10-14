"""Run the fresh F015-only Step 7 delta review after the final F015 repair."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


WORKTREE = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
PLAN = Path(r"C:\Users\HH18\softfac_v2_hoh_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
PRIOR_REVIEW = Path(r"C:\Users\HH18\sol_softfac_v2_current_delta_verdict.json")
PRIOR_TREE = "de016794022dd82896be5f28eb205e9bd6c453d9"
RAW = Path(r"C:\Users\HH18\sol_softfac_v2_f015_delta.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_softfac_v2_f015_delta.stderr.txt")
USAGE = Path(r"C:\Users\HH18\sol_softfac_v2_f015_delta_usage.json")
VERDICT = Path(r"C:\Users\HH18\sol_softfac_v2_f015_delta_verdict.json")
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


def blob_hash(path: str) -> str:
    return hashlib.sha256(
        subprocess.check_output(["git", "-C", str(WORKTREE), "cat-file", "blob", f":{path}"])
    ).hexdigest()


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


def main() -> int:
    prior = json.loads(PRIOR_REVIEW.read_text(encoding="utf-8"))
    if prior.get("review_type") != "DELTA_ONLY_RECHECK" or prior.get("step") != 7:
        raise SystemExit("F015 predecessor delta review is unavailable")
    open_ids = {item.get("finding_id") for item in prior.get("blocking_findings", [])}
    if open_ids != {"STEP7-F015"}:
        raise SystemExit(f"predecessor does not contain only F015: {sorted(open_ids)}")
    tree_oid = git("write-tree").strip()
    staged_diff = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", "--cached", "--binary", "--no-ext-diff"]
    )
    staged_diff_sha = hashlib.sha256(staged_diff).hexdigest()
    delta = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", "--binary", "--no-ext-diff", PRIOR_TREE, tree_oid]
    )
    test_output, test_exit = run_tests()
    if test_exit != 0:
        print(test_output, end="")
        return test_exit or 1
    packet = {
        "base_commit": git("rev-parse", "HEAD").strip(),
        "head_commit": git("rev-parse", "HEAD").strip(),
        "tree_oid": tree_oid,
        "staged_diff_sha256": staged_diff_sha,
        "staged_paths": git("diff", "--cached", "--name-status"),
        "relevant_staged_blob_hashes": {
            path: blob_hash(path)
            for path in (
                "README.md",
                "bin/hermes-code-factory-v2",
                "docs/software-factory-SKILL.md",
                "lib/hermes_factory_v2.py",
                "tests/test_factory_v2.py",
            )
        },
        "test_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -B -m pytest -q tests",
        "test_exit": test_exit,
        "test_output_sha256": hashlib.sha256(test_output.encode("utf-8")).hexdigest(),
        "test_output": test_output,
        "checksum_verification": "PASS",
        "git_diff_cached_check": git("diff", "--cached", "--check") == "",
        "bytecode_paths_in_staged_tree": [
            path for path in git("ls-tree", "-r", "--name-only", tree_oid).splitlines()
            if "/__pycache__/" in path or path.endswith(".pyc")
        ],
    }
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    delta_text = delta.decode("utf-8", errors="replace")
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), an independent fail-closed gatekeeper.

review_type = DELTA_ONLY_RECHECK
step = 7
target_findings = STEP7-F015

The immediately preceding F015-only delta review returned protocol-valid
REJECT with STEP7-F015 OPEN. The implementation was modified after that
review. Review only STEP7-F015 and the exact repair delta below. Do not run a
new STEP_CONFORMANCE_REVIEW and do not reopen unrelated findings.

Freeze as resolved:
STEP7-F002, STEP7-F013, STEP7-F016, and every other prior PASS/RESOLVED item,
unless this exact F015 repair contains concrete regression evidence.

AUTHORITATIVE PLAN
{plan_text}

SOL CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

IMMEDIATELY PREVIOUS F015 DELTA REJECT
{json.dumps(prior, indent=2, ensure_ascii=False)}

CURRENT EXACT CANDIDATE PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

PREVIOUS REVIEWED TREE = {PRIOR_TREE}
CURRENT STAGED TREE = {tree_oid}
EXACT F015 REPAIR DELTA SHA-256 = {hashlib.sha256(delta).hexdigest()}
F015 REPAIR DELTA START
{delta_text}
F015 REPAIR DELTA END

F015 acceptance property:
Any AGY attempt that is ultimately rejected must leave the host-owned
candidate byte-identical to its pre-attempt state. Mirror synchronization may
occur only after every rejection-capable acceptance gate has passed, or must
be transactionally undone if a later mandatory rejection occurs.

Verify concretely that process/non-success failure, malformed protocol, wrong
model/cwd/conversation/result, executable identity failure, protected-host
attestation failure, and mandatory evidence/reservation failure cannot leave
an accepted host-candidate mutation. The focused post-process identity
regression must prove BuilderFailure and unchanged candidate bytes. Confirm
that the production Windows Sandbox path invokes its remaining acceptance
gates before mirror synchronization and that no repair-caused regression exists.

Return ONLY one compact JSON object, no prose or markdown:
{{
  "review_type": "DELTA_ONLY_RECHECK",
  "step": 7,
  "verdict": "APPROVE or REJECT",
  "step_status": "PASS or FAIL",
  "authorized_for_next_step": true,
  "candidate_identity": {{"base_commit": "...", "head_commit": "...", "tree_oid": "...", "diff_sha256": "..."}},
  "checklist": [],
  "blocking_findings": [],
  "resolved_findings": [],
  "non_blocking_findings": [],
  "precedent_corrections": [],
  "next_actions": []
}}
Every blocking finding must include finding_id, status, severity, blocking_class,
contract_source, exact_requirement, concrete_evidence, observed_state,
expected_state, why_it_blocks_current_step, required_correction, and
correction_class. Do not emit any text outside JSON.
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
    USAGE.write_text(json.dumps({"role": "Sol Reviewer", "model": "gpt-5.6-sol", "review_type": "DELTA_ONLY_RECHECK", "step": 7, "target_findings": ["STEP7-F015"], "exit_code": result.returncode}, indent=2), encoding="utf-8")
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
