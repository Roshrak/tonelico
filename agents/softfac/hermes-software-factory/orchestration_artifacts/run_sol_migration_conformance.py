import subprocess
import json
import sys
import time
from pathlib import Path

REPO_DIR = Path(r"C:\Users\HH18\Downloads\hermes-software-factory-v2-hoh\hermes-software-factory-v2")
sys.path.insert(0, str(REPO_DIR))

from lib.hermes_factory_v2 import CodexRoleClient, Config

ASTRA_PLAN_FILE = Path(r"C:\Users\HH18\astra_plan.md")
PROMPT_OUT_FILE = Path(r"C:\Users\HH18\sol_migration_conformance_prompt.txt")
RAW_OUTPUT_FILE = Path(r"C:\Users\HH18\sol_migration_conformance.raw_output.txt")
VERDICT_FILE = Path(r"C:\Users\HH18\sol_migration_conformance_verdict.json")
USAGE_FILE = Path(r"C:\Users\HH18\sol_migration_conformance_usage.json")

def get_git_info():
    head_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout
    diff_main = subprocess.run(["git", "diff", "main..HEAD"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout
    log_commits = subprocess.run(["git", "log", "main..HEAD", "--oneline"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout
    return head_hash, status, diff_main, log_commits

SOL_CONFORMANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVE", "REJECT"]},
        "overall_state": {
            "type": "string",
            "enum": ["NOT_READY", "IMPLEMENTATION_IN_PROGRESS", "READY_FOR_FINAL_ACCEPTANCE"]
        },
        "actual_current_step_reached": {"type": "integer"},
        "earliest_blocking_step": {"type": "integer"},
        "do_not_proceed_beyond_step": {"type": "integer"},
        "plan_conformance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "integer"},
                    "step_title": {"type": "string"},
                    "status": {"type": "string", "enum": ["PASS", "PARTIAL", "FAIL", "NOT_STARTED"]},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "missing_or_wrong": {"type": "array", "items": {"type": "string"}},
                    "blocking": {"type": "boolean"}
                },
                "required": ["step", "status", "evidence", "missing_or_wrong", "blocking"]
            }
        },
        "final_checklist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "status": {"type": "string", "enum": ["PASS", "FAIL", "UNPROVEN"]},
                    "evidence": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["requirement", "status", "evidence"]
            }
        },
        "prior_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string", "enum": ["RESOLVED", "STILL_OPEN", "REGRESSED", "SUPERSEDED"]},
                    "evidence": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["id", "status", "evidence"]
            }
        },
        "blocking_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM"]},
                    "plan_step": {"type": "integer"},
                    "invariant": {"type": "string"},
                    "evidence": {"type": "string"},
                    "required_correction": {"type": "string"}
                },
                "required": ["severity", "plan_step", "invariant", "evidence", "required_correction"]
            }
        },
        "next_required_work": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "priority": {"type": "integer"},
                    "plan_step": {"type": "integer"},
                    "objective": {"type": "string"},
                    "why_now": {"type": "string"},
                    "acceptance_evidence_required": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["priority", "plan_step", "objective", "why_now", "acceptance_evidence_required"]
            }
        },
        "summary": {"type": "string"}
    },
    "required": [
        "verdict",
        "overall_state",
        "actual_current_step_reached",
        "earliest_blocking_step",
        "do_not_proceed_beyond_step",
        "plan_conformance",
        "final_checklist",
        "prior_findings",
        "blocking_findings",
        "next_required_work",
        "summary"
    ]
}

def build_review_prompt(head_hash, status, diff_main, log_commits, astra_plan_text):
    prompt = f"""You are Sol High (gpt-5.6-sol), the authoritative, independent reviewer and quality gate for the Hermes Software Factory v2 (HOH Architecture).

AUTHORITATIVE CONTRACT:
You are conducting a strict MIGRATION PLAN CONFORMANCE REVIEW of the ongoing Aider -> AGY CLI migration.
The AUTHORITATIVE ACCEPTANCE CONTRACT for this entire migration is the full Astra Migration Plan (`C:\\Users\\HH18\\astra_plan.md`).
The Astra migration plan outranks any prior partial reviews or shortcuts. If a prior Sol review guidance contradicts the Astra plan, issue a PRECEDENT_CORRECTION and follow the Astra plan.

YOUR MANDATE:
1. You must compare the implementation against EVERY migration step in the Astra plan, Step 1 through Step 14, as well as the Final Release Checklist (Section 4).
2. You must detect:
   - skipped steps;
   - partially implemented steps;
   - work performed out of required order (e.g. implementing Step 7 builder/preflight before Step 2 execution isolation contract is proven);
   - implementation that contradicts the plan;
   - obsolete compatibility behavior that the plan requires removing;
   - safety prerequisites that were bypassed;
   - missing tests or evidence (distinguish mocks from live proof);
   - premature production cutover or premature claims of completion.
3. DO NOT assume current mechanisms are sufficient simply because Hermes presents them:
   - Does `--sandbox`, `--dangerously-skip-permissions`, `cwd=worktree`, `--add-dir`, `_assert_source_unchanged`, and git worktree checks actually satisfy the execution-isolation contract defined by Astra Step 2 and Step 6? Prove it from code and live/fixture evidence.
   - Astra Step 9 requires runtime state to live outside candidate and warns against solving safety by broadly ignoring/deleting artifacts. Compare the current cleanup design to Step 9.
4. DETERMINE THE ACTUAL ACHIEVED STEP BOUNDARY INDEPENDENTLY:
   - Do NOT assume Hermes is at Step 13 or Step 14.
   - If AgyBuilder was coded but Step 2 execution isolation is unproven, you must report that functional implementation progressed ahead of its safety prerequisites.
   - Output `do_not_proceed_beyond_step` representing the earliest unapproved/blocking prerequisite.
5. ORDERED REMEDIATION:
   - When verdict is REJECT, provide an ordered list in `next_required_work` strictly mapped to Astra plan step numbers, addressing the earliest violated prerequisite first.

---
AUTHORITATIVE ASTRA MIGRATION PLAN (C:\\Users\\HH18\\astra_plan.md):
{astra_plan_text}

---
CURRENT REPOSITORY CANDIDATE STATE:
Target Repo: C:\\Users\\HH18\\Downloads\\hermes-software-factory-v2-hoh\\hermes-software-factory-v2
Branch: hermes/replace-aider-with-agy
HEAD Commit: {head_hash}
Git Porcelain Status:
{status if status.strip() else '(clean working tree)'}

Commits ahead of main:
{log_commits}

FULL GIT DIFF (main..HEAD):
```diff
{diff_main}
```

---
INSTRUCTIONS FOR OUTPUT:
Evaluate every single step from Step 1 to Step 14 against the plan text.
Evaluate each of the 15 items in the Final Release Checklist.
Evaluate prior findings (isolation breach, cache cleanup destruction, SHA256SUMS, documentation).
Return ONLY a valid JSON object matching the requested schema.
"""
    return prompt

def main():
    print("Reading authoritative Astra Migration Plan...")
    if not ASTRA_PLAN_FILE.exists():
        print(f"Error: {ASTRA_PLAN_FILE} not found!")
        sys.exit(1)
    astra_plan_text = ASTRA_PLAN_FILE.read_text(encoding="utf-8")

    print("Gathering repository Git info...")
    head_hash, status, diff_main, log_commits = get_git_info()
    print(f"HEAD commit: {head_hash}")
    print(f"Diff length: {len(diff_main)} characters")

    prompt = build_review_prompt(head_hash, status, diff_main, log_commits, astra_plan_text)
    PROMPT_OUT_FILE.write_text(prompt, encoding="utf-8")
    print(f"Wrote complete prompt ({len(prompt)} chars) to {PROMPT_OUT_FILE}")

    config = Config(
        repo=str(REPO_DIR),
        request="Astra Migration Plan Conformance Review",
        requested_files=None,
        test_command=None,
        sol_model="gpt-5.6-sol",
        role_timeout=1500,
    )

    client = CodexRoleClient()
    print("Invoking Sol High via CodexRoleClient (timeout=1500s)...")
    t0 = time.time()
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

    raw_text = getattr(result, "raw_output", "") or str(result)
    RAW_OUTPUT_FILE.write_text(raw_text, encoding="utf-8")

    if hasattr(result, "payload") and result.payload:
        verdict_data = result.payload
    elif isinstance(result, dict):
        verdict_data = result
    else:
        try:
            verdict_data = json.loads(raw_text)
        except Exception:
            verdict_data = {"raw_output": raw_text}

    VERDICT_FILE.write_text(json.dumps(verdict_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote verdict to {VERDICT_FILE}")

    usage_data = getattr(result, "usage", {})
    if usage_data:
        USAGE_FILE.write_text(json.dumps(usage_data, indent=2), encoding="utf-8")

    print("\n" + "="*50)
    print(f"VERDICT: {verdict_data.get('verdict')}")
    print(f"OVERALL STATE: {verdict_data.get('overall_state')}")
    print(f"ACTUAL CURRENT STEP REACHED: {verdict_data.get('actual_current_step_reached')}")
    print(f"EARLIEST BLOCKING STEP: {verdict_data.get('earliest_blocking_step')}")
    print(f"DO NOT PROCEED BEYOND STEP: {verdict_data.get('do_not_proceed_beyond_step')}")
    print("="*50)

if __name__ == "__main__":
    main()
