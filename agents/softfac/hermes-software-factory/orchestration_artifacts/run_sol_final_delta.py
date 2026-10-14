"""Run the only allowed final-review delta recheck for FINAL-F001..F007."""

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
PLAN = Path(r"C:\Users\HH18\softfac_v2_hoh_plan.md")
CONSTITUTION = Path(r"C:\Users\HH18\sol_reviewer_constitution.md")
PRIOR = Path(r"C:\Users\HH18\sol_softfac_v2_final_integrated_verdict.json")
FREEZE = Path(r"C:\Users\HH18\softfac_v2_step7_freeze.json")
RAW = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta.raw_output.txt")
STDERR = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta.stderr.txt")
USAGE = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta_usage.json")
VERDICT = Path(r"C:\Users\HH18\sol_softfac_v2_final_delta_verdict.json")
VALIDATOR = Path(r"C:\Users\HH18\validate_sol_review_protocol.py")
TARGETS = [f"FINAL-F00{i}" for i in range(1, 8)]


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


def main() -> int:
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    if prior.get("review_type") != "FINAL_INTEGRATED_REVIEW" or prior.get("verdict") != "REJECT":
        raise SystemExit("final integrated predecessor is unavailable")
    prior_ids = {item.get("finding_id") for item in prior.get("blocking_findings", [])}
    if prior_ids != set(TARGETS):
        raise SystemExit(f"unexpected final finding set: {sorted(prior_ids)}")
    head = git("rev-parse", "HEAD").strip()
    if head != PREVIOUS_HEAD:
        raise SystemExit(f"unexpected predecessor HEAD: {head}")
    tree = git("write-tree").strip()
    diff = subprocess.check_output(["git", "-C", str(WORKTREE), "diff", "--cached", "--binary", "--no-ext-diff"])
    repair_delta = subprocess.check_output(["git", "-C", str(WORKTREE), "diff", "--binary", "--no-ext-diff", PREVIOUS_HEAD, tree])
    test_output, test_exit = run_tests()
    if test_exit != 0:
        print(test_output, end="")
        return test_exit or 1
    manifest: dict[str, str] = {}
    for line in git("show", f":SHA256SUMS").splitlines():
        if line.strip():
            digest, path = line.split(None, 1)
            manifest[path] = digest
    checksum_mismatches = []
    for path, expected in manifest.items():
        actual = hashlib.sha256(subprocess.check_output(["git", "cat-file", "blob", f":{path}"])).hexdigest()
        if actual != expected:
            checksum_mismatches.append({"path": path, "expected": expected, "actual": actual})
    bytecode_paths = [
        path for path in git("ls-tree", "-r", "--name-only", tree).splitlines()
        if "/__pycache__/" in path or path.endswith(".pyc")
    ]
    packet = {
        "review_type": "DELTA_ONLY_RECHECK",
        "final_review_delta": True,
        "target_findings": TARGETS,
        "previous_head": PREVIOUS_HEAD,
        "current_head": head,
        "current_tree": tree,
        "current_staged_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "repair_delta_sha256": hashlib.sha256(repair_delta).hexdigest(),
        "repair_delta_length": len(repair_delta),
        "test_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -B -m pytest -q tests",
        "test_exit_code": test_exit,
        "test_output_sha256": hashlib.sha256(test_output.encode("utf-8")).hexdigest(),
        "test_output": test_output,
        "checksum_entries": len(manifest),
        "checksum_mismatches": checksum_mismatches,
        "git_diff_cached_check": git("diff", "--cached", "--check") == "",
        "bytecode_paths": bytecode_paths,
        "freeze_before_repair": json.loads(FREEZE.read_text(encoding="utf-8")),
    }
    plan_text = PLAN.read_text(encoding="utf-8")
    constitution_text = CONSTITUTION.read_text(encoding="utf-8")
    constitution_sha = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), an independent fail-closed gatekeeper.

review_type = DELTA_ONLY_RECHECK
target_findings = {', '.join(TARGETS)}

The one FINAL_INTEGRATED_REVIEW already completed with protocol-valid REJECT.
The implementation was repaired after that review. This is the only permitted
follow-up review: inspect only FINAL-F001 through FINAL-F007, the exact repair
delta, and affected evidence. Do not run another FINAL_INTEGRATED_REVIEW and
do not reopen unrelated findings. Preserve all prior RESOLVED/PASS findings
unless this repair provides concrete regression evidence.

AUTHORITATIVE REPLACEMENT PLAN
{plan_text}

SOL CONSTITUTION
Version: 1.0.0
SHA-256: {constitution_sha}
{constitution_text}

PREVIOUS FINAL INTEGRATED REVIEW
{json.dumps(prior, indent=2, ensure_ascii=False)}

CURRENT CANDIDATE PACKET
{json.dumps(packet, indent=2, ensure_ascii=False)}

EXACT REPAIR DELTA ({PREVIOUS_HEAD}..{tree})
{repair_delta.decode("utf-8", errors="replace")}

Verify only the seven repaired findings:
FINAL-F001: valid overlapping-scope plans preserve/refresh affected criterion
evidence and complete with Astra invoked exactly once.
FINAL-F002: authorized new files synchronize atomically and reject creation
races without losing host work.
FINAL-F003: exceptional replan budget and reason history survive crashes and
cannot be refilled.
FINAL-F004: completed task contracts and global criteria cannot be rewritten or
removed by a replan.
FINAL-F005: complete/committed terminal state is revalidated fail-closed,
including referenced review and verification evidence.
FINAL-F006: active docs and Builder prompt match Astra -> Hermes -> AGY ->
Runner -> Sol, with Luna outside v1; historical docs are clearly superseded.
FINAL-F007: all five typed verified exceptional-replan triggers are supported,
while ordinary test/review failure remains AGY repair or BLOCKED.

Return ONLY one compact JSON object, no prose or markdown:
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
    USAGE.write_text(json.dumps({"role": "Sol Reviewer", "model": "gpt-5.6-sol", "review_type": "DELTA_ONLY_RECHECK", "target_findings": TARGETS, "exit_code": result.returncode}, indent=2), encoding="utf-8")
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
    validation = subprocess.run([sys.executable, "-B", str(VALIDATOR), "--step", "7"], input=json.dumps(verdict, ensure_ascii=False), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(validation.stdout, end="")
    return validation.returncode


if __name__ == "__main__":
    raise SystemExit(main())
