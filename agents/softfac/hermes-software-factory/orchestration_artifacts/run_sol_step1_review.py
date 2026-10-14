import json
import subprocess
import time
import os
import hashlib
from pathlib import Path
import sys

WORKTREE_DIR = Path(r"C:\Users\HH18\Downloads\hermes-software-factory-v2-hoh\migration-worktree")
sys.path.insert(0, str(WORKTREE_DIR / "lib"))

from hermes_factory_v2 import Config, CodexRoleClient, FactoryError

ASTRA_PLAN_FILE = Path(r"C:/Users/HH18/astra_plan.md")
CONSTITUTION_FILE = Path(r"C:/Users/HH18/sol_reviewer_constitution.md")
PROMPT_FILE = Path(r"C:\Users\HH18\sol_step1_prompt.txt")
RAW_OUTPUT_FILE = Path(r"C:\Users\HH18\sol_step1.raw_output.txt")
USAGE_FILE = Path(r"C:\Users\HH18\sol_step1_usage.json")
VERDICT_FILE = Path(r"C:\Users\HH18\sol_step1_verdict.json")

def git(*args, cwd=WORKTREE_DIR) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def main():
    print("Verifying Step 1 deterministic invariants before submission...")
    res = subprocess.run([sys.executable, "C:/Users/HH18/verify_baseline_inventory.py"], capture_output=True, text=True)
    if res.returncode != 0 or "100%" not in res.stdout:
        print("Pre-submission check failed:", res.stdout, res.stderr)
        sys.exit(1)

    print("Generating comprehensive Step 1 review packet...")
    packet_proc = subprocess.run([sys.executable, "C:/Users/HH18/generate_step1_packet.py"], capture_output=True, text=True)
    if packet_proc.returncode != 0:
        print("Failed to generate packet:", packet_proc.stderr)
        sys.exit(1)
    packet_json_str = packet_proc.stdout.strip()
    packet = json.loads(packet_json_str)
    packet_path = Path(r"C:/Users/HH18/step1_packet.json")
    packet_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    print(f"Persisted current Step 1 packet to {packet_path}")

    base_commit = packet["base_commit"]
    head_commit = packet["head_commit"]
    git_diff = git("diff", base_commit)
    git_status = git("status")

    constitution_text = CONSTITUTION_FILE.read_text(encoding="utf-8")
    constitution_sha256 = hashlib.sha256(constitution_text.encode("utf-8")).hexdigest()
    constitution_version = "1.0.0"
    astra_plan_text = ASTRA_PLAN_FILE.read_text(encoding="utf-8")

    prior_review = packet.get("prior_review", {})
    prior_raw_path = Path(prior_review.get("raw_output_path", ""))
    prior_raw = prior_raw_path.read_text(encoding="utf-8", errors="replace") if prior_raw_path.exists() else ""
    prior_raw_sha = hashlib.sha256(prior_raw.encode("utf-8")).hexdigest() if prior_raw else prior_review.get("raw_output_sha256", "")

    prompt = f"""You are Sol Reviewer (gpt-5.6-sol), the authoritative, independent gatekeeper for the Human-Out-of-the-Loop (HOH) Software Factory v2.
You are conducting a DELTA_ONLY_RECHECK of Astra Migration Step 1.

AUTHORITATIVE ASTRA PLAN (read from disk at C:/Users/HH18/astra_plan.md):
{astra_plan_text}

SOL REVIEWER CONSTITUTION (canonical, immutable for this review cycle):
Version: {constitution_version}
SHA-256: {constitution_sha256}
{constitution_text}

This is a bounded recheck of stable findings SOL-S1-001, SOL-S1-002, SOL-S1-003, and SOL-S1-004 from the prior protocol-invalid review. The prior raw response is diagnostic evidence only; do not treat its verdict as accepted because local semantic validation failed. Verify each stable finding as RESOLVED, OPEN, REGRESSED, or SUPERSEDED. Do not broaden the review. Do not begin Step 2. Do not require future-step implementation. Any new blocker must satisfy the constitution's blocking policy and include status OPEN plus all required fields.

PRIOR RAW REVIEW EVIDENCE
- path: {prior_review.get('raw_output_path')}
- sha256: {prior_raw_sha}
- prior candidate HEAD: {prior_review.get('candidate_head')}
- prior candidate tree: {prior_review.get('candidate_tree_oid')}
- prior candidate diff SHA-256: {prior_review.get('candidate_diff_sha256')}

CURRENT DETERMINISTIC PACKET
{packet_json_str}

CURRENT COMPLETE DIFF (against {base_commit})
```diff
{git_diff}
```

Return ONLY one compact JSON object and no prose, commentary, analysis, markdown fences, or text inside JSON values that refers to this instruction. Do not echo the constitution or prompt. Do not include commentary between JSON properties. Every blocking finding MUST include status OPEN or REGRESSED. Resolved findings MUST use status RESOLVED in resolved_findings. Candidate identity must exactly match the current packet. Keep evidence strings concise.
"""

    PROMPT_FILE.write_text(prompt, encoding="utf-8")
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    print(f"Wrote Step 1 review prompt ({len(prompt)} chars) to {PROMPT_FILE}")
    print(f"Step 1 review prompt SHA-256: {prompt_sha256}")

    config = Config(
        repo=str(WORKTREE_DIR),
        request="Astra Migration Plan Step 1 Conformance Review",
        requested_files=None,
        test_command=None,
        sol_model="gpt-5.6-sol",
        role_timeout=1200,
    )

    client = CodexRoleClient()
    print("Invoking Sol High via CodexRoleClient (timeout=1200s)...")
    t0 = time.time()
    try:
        verdict_data = client.call(
            role="sol_reviewer",
            provider=config.sol_provider,
            model=config.sol_model,
            prompt=prompt,
            usage_path=USAGE_FILE,
            output_path=RAW_OUTPUT_FILE,
            timeout=config.role_timeout,
            reasoning="high",
        )
        elapsed = time.time() - t0
        print(f"Sol High completed in {elapsed:.1f}s")
    except Exception as e:
        print(f"Sol High invocation error: {e}")
        sys.exit(1)

    # Parse JSON verdict robustly
    from parse_sol_verdict import parse_sol_verdict
    raw_text = RAW_OUTPUT_FILE.read_text(encoding="utf-8", errors="replace")
    parse_status, verdict_json, raw_sha256 = parse_sol_verdict(raw_text)

    # Save parsing metadata and immutable verdict
    meta = {
        "parsing_status": parse_status,
        "raw_output_sha256": raw_sha256,
        "raw_output_path": str(RAW_OUTPUT_FILE),
        "constitution_version": constitution_version,
        "constitution_sha256": constitution_sha256,
        "review_mode": "DELTA_ONLY_RECHECK",
        "verdict": verdict_json,
    }
    VERDICT_FILE.write_text(json.dumps(meta if parse_status != "SUCCESS" else verdict_json, indent=2), encoding="utf-8")
    
    if parse_status != "SUCCESS":
        print("REVIEW_PROTOCOL_FAILURE: Unable to extract valid, unanimous Sol verdict object.")
        sys.exit(1)

    protocol_proc = subprocess.run(
        [sys.executable, "C:/Users/HH18/validate_sol_review_protocol.py"],
        input=json.dumps(verdict_json), capture_output=True, text=True
    )
    if protocol_proc.returncode != 0:
        print("REVIEW_PROTOCOL_FAILURE: semantic review schema/policy validation failed")
        print(protocol_proc.stdout)
        sys.exit(1)

    print(f"Successfully extracted and wrote Step 1 verdict to {VERDICT_FILE}")
    print("Verdict:", verdict_json.get("verdict"))
    print("Step 1 Status:", verdict_json.get("step_1_status") or verdict_json.get("step_status"))
    print("Authorized for Step 2:", verdict_json.get("authorized_for_step_2"))

if __name__ == "__main__":
    main()
