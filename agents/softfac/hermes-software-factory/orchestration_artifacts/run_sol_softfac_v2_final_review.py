"""Review the exact staged SoftFac v2 continuation candidate with a fresh Sol process."""

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
RAW = Path(r"C:\Users\HH18\sol_softfac_v2_final.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_softfac_v2_final.stderr.txt")
VERDICT = Path(r"C:\Users\HH18\sol_softfac_v2_final_verdict.json")
USAGE = Path(r"C:\Users\HH18\sol_softfac_v2_final_usage.json")
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
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def staged_diff() -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(WORKTREE), "diff", "--cached", "--binary", "--no-ext-diff"]
    )


def staged_files() -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "-C", str(WORKTREE), "diff", "--cached", "--name-status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    files = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        entry = {"status": status, "path": path.replace("\\", "/")}
        if status[0] != "D":
            staged_bytes = subprocess.check_output(
                ["git", "-C", str(WORKTREE), "show", f":{path}"]
            )
            entry["sha256"] = hashlib.sha256(staged_bytes).hexdigest()
        files.append(entry)
    return files


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
        [sys.executable, "-B", "-m", "pytest", "tests", "-q", "--disable-warnings"],
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
    base_commit = git("rev-parse", "HEAD").strip()
    tree_oid = git("write-tree").strip()
    diff_bytes = staged_diff()
    diff_text = diff_bytes.decode("utf-8", errors="replace")
    diff_sha = hashlib.sha256(diff_bytes).hexdigest()
    files = staged_files()
    test_output, test_exit = run_tests()
    test_output_sha = hashlib.sha256(test_output.encode("utf-8")).hexdigest()
    import re

    passed_match = re.search(r"(\d+) passed", test_output)
    subtests_match = re.search(r"(\d+) subtests?", test_output)
    test_counts = {
        "exit_code": test_exit,
        "passed": int(passed_match.group(1)) if passed_match else 0,
        "subtests": int(subtests_match.group(1)) if subtests_match else 0,
        "status": "PASS" if test_exit == 0 and passed_match else "FAIL",
    }
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    prior = json.loads(PRIOR_REVIEW.read_text(encoding="utf-8")) if PRIOR_REVIEW.is_file() else {}
    identity = {
        "base_commit": base_commit,
        "head_commit": base_commit,
        "tree_oid": tree_oid,
        "diff_sha256": diff_sha,
    }
    packet = {
        "worktree": str(WORKTREE).replace("\\", "/"),
        "base_commit": base_commit,
        "tree_oid": tree_oid,
        "diff_sha256": diff_sha,
        "staged_files": files,
        "test_command": f"{sys.executable} -B -m pytest tests -q --disable-warnings",
        "test_counts": test_counts,
        "test_output_sha256": test_output_sha,
        "test_output": test_output,
        "worktree_status": git("status", "--short"),
    }
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), an independent fail-closed senior reviewer.

review_type = STEP_CONFORMANCE_REVIEW
step = 7

Review the exact staged SoftFac v2 implementation candidate below. This is an
implementation review after a prior Step 7 review; do not edit, stage, commit,
clean, or repair anything. Do not reopen historical PASS findings without
concrete regression evidence. Review the current candidate's implementation,
tests, state semantics, source safety, and release correctness.

AUTHORITATIVE CURRENT PLAN
{plan_text}

SOL CONSTITUTION
{constitution_text}

PRIOR STEP 7 REVIEW (diagnostic/history; do not assume it approves this tree)
{json.dumps(prior, indent=2, ensure_ascii=False)}

EXACT CURRENT CANDIDATE PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

EXACT STAGED DIFF SHA256 = {diff_sha}
EXACT STAGED TREE OID = {tree_oid}
BASE COMMIT = {base_commit}
DIFF START
{diff_text}
DIFF END

Required checks:
1. M1: Step 2/6 boundary is preserved; F001/F002 are concretely resolved;
   complete delta/scope checks protect source, Git, trusted state, and
   unrelated roots; no generated bytecode is silently included.
2. V1 route semantics: Astra makes the initial master plan only; Hermes
   selects ready tasks; Runner FAIL and Sol REJECT go to AGY; stagnation or
   exhausted repair becomes BLOCKED; no production Luna dispatch exists.
3. M2: public execute consumes one validated master plan, runs normal T1/T2/T3
   in stable dependency order, and Astra invocation count remains one without
   plan invalidation. Routine resume/commit/repair must not call Astra.
4. M3: candidate_id is git write-tree, Sol approval binds exactly
   {{base_commit,candidate_id}}, post-approval mutation is rejected, Hermes is
   the only committer, and pending commit recovery cannot duplicate or guess.
5. COMPLETE is not reported with missing global criteria, unresolved blocking
   evidence, pending candidates, or ambiguous commits.
6. Legacy Aider/bridge production surface is removed or explicitly outside the
   active path, documentation matches the code, and checksums match release
   files.
7. Previously approved Steps 1-6 and resolved Step 7 findings are preserved;
   future/deferred work is not a blocker unless the plan makes it current.

Return ONLY one compact JSON object, with no prose or markdown fences:
{{
  "review_type": "STEP_CONFORMANCE_REVIEW",
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

Every blocking finding must include the full constitution-required fields.
Before returning, validate each blocking finding mechanically: every item must
include finding_id, status (OPEN or REGRESSED), severity, blocking_class,
contract_source, exact_requirement, concrete_evidence, observed_state,
expected_state, why_it_blocks_current_step, required_correction, and
correction_class. Do not omit status from any item, including newly discovered
findings.
If all current requirements pass, return APPROVE/PASS/true with an empty
blocking_findings array.
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
                "review_type": "STEP_CONFORMANCE_REVIEW",
                "step": 7,
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
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[7:-3].strip()
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError as exc:
        VERDICT.write_text(json.dumps({"protocol_error": str(exc), "raw_sha256": hashlib.sha256((result.stdout or "").encode("utf-8")).hexdigest()}, indent=2), encoding="utf-8")
        print(f"Sol returned invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(verdict, dict):
        print("Sol verdict is not an object", file=sys.stderr)
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
