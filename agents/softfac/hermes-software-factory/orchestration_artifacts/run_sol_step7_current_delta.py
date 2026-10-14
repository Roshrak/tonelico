"""Run the single bounded Step 7 DELTA_ONLY_RECHECK for the latest repair."""

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
PRIOR_REVIEW = Path(r"C:\Users\HH18\sol_softfac_v2_final_verdict.json")
PRIOR_TREE = "1f67da791e2aad41a529f32c0f2464b1975d33d9"
RAW = Path(r"C:\Users\HH18\sol_softfac_v2_current_delta.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_softfac_v2_current_delta.stderr.txt")
USAGE = Path(r"C:\Users\HH18\sol_softfac_v2_current_delta_usage.json")
VERDICT = Path(r"C:\Users\HH18\sol_softfac_v2_current_delta_verdict.json")
VALIDATOR = Path(r"C:\Users\HH18\validate_sol_review_protocol.py")
TARGETS = ["STEP7-F002", "STEP7-F013", "STEP7-F015", "STEP7-F016"]


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


def staged_blob_hash(path: str) -> str:
    return hashlib.sha256(
        subprocess.check_output(["git", "-C", str(WORKTREE), "cat-file", "blob", f":{path}"])
    ).hexdigest()


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
    if prior.get("step") != 7 or prior.get("review_type") != "STEP_CONFORMANCE_REVIEW":
        raise SystemExit("latest Step 7 full review is unavailable")
    prior_ids = {item.get("finding_id") for item in prior.get("blocking_findings", [])}
    if not set(TARGETS).issubset(prior_ids):
        raise SystemExit("target findings are not present in the latest review")

    tree_oid = git("write-tree").strip()
    diff_bytes = subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", "--cached", "--binary", "--no-ext-diff"]
    )
    diff_sha = hashlib.sha256(diff_bytes).hexdigest()
    delta_bytes = subprocess.check_output(
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
        "diff_sha256": diff_sha,
        "staged_paths": git("diff", "--cached", "--name-status"),
        "staged_file_hashes": {
            path: staged_blob_hash(path)
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
        "git_diff_cached_check": git("diff", "--cached", "--check") == "",
        "bytecode_in_tree": [
            path
            for path in git("ls-tree", "-r", "--name-only", tree_oid).splitlines()
            if "/__pycache__/" in path or path.endswith(".pyc")
        ],
    }
    delta_text = delta_bytes.decode("utf-8", errors="replace")
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), an independent fail-closed gatekeeper.

review_type = DELTA_ONLY_RECHECK
step = 7
target_findings = {', '.join(TARGETS)}

The latest Step 7 STEP_CONFORMANCE_REVIEW is complete. This is exactly one
bounded delta recheck, limited to the four target findings above and concrete
regression evidence caused by this repair. Do not perform a new full review.
Do not reopen any currently RESOLVED finding unless this exact repair provides
concrete regression evidence. Preserve all other PASS and RESOLVED decisions
as frozen. APPROVE only if all four target findings are resolved.

AUTHORITATIVE PLAN
{plan_text}

SOL CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

LATEST FULL STEP 7 REVIEW
{json.dumps(prior, indent=2, ensure_ascii=False)}

CURRENT EXACT STAGED CANDIDATE PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

PREVIOUS REVIEWED STAGED TREE = {PRIOR_TREE}
CURRENT STAGED TREE = {tree_oid}
REPAIR DELTA SHA-256 = {hashlib.sha256(delta_bytes).hexdigest()}
REPAIR DELTA START
{delta_text}
REPAIR DELTA END

Verify only these requirements:
1. STEP7-F002: synchronization rejects or preserves same-target concurrent
   host mutation through replacement completion; the candidate cannot silently
   lose host work.
2. STEP7-F013: criterion freshness is affected-lineage aware; unaffected
   distributed criteria remain valid and a normal valid N-task run completes
   with exactly one actual Astra planner-model invocation.
3. STEP7-F015: failed, malformed, or otherwise non-accepted AGY attempts do
   not synchronize mirror edits into the host candidate.
4. STEP7-F016: replan exhaustion durably persists BLOCKED and a later execute
   or resume cannot refill its budget or invoke Astra again.

Return ONLY one compact JSON object with exactly this top-level shape:
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
correction_class. Do not emit prose, markdown, or any text outside JSON.
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
    USAGE.write_text(
        json.dumps(
            {
                "role": "Sol Reviewer",
                "model": "gpt-5.6-sol",
                "review_type": "DELTA_ONLY_RECHECK",
                "step": 7,
                "target_findings": TARGETS,
                "exit_code": result.returncode,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode or 1
    raw = (result.stdout or "").strip()
    try:
        verdict = json.loads(raw)
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
