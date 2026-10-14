import json
import urllib.request
import os

diff_path = "C:/Users/HH18/sol_review_full.diff"
with open(diff_path, "r", encoding="utf-8") as f:
    diff_text = f.read()

prompt = f"""You are Sol Reviewer, the final acceptance reviewer of SoftFac v2 candidate changes.
We have addressed all previous feedback regarding:
1. Strict editable_files scoping per step (now supporting structured implementation steps with explicit `editable_files` and deduped file targeting).
2. Broad natural language step contracts in `extract_step_contract` covering exact, minimums, maximums, and ranges.
3. Authoritative `non_resumable` state tracking for truncated Builder executions independent of leftover filesystem artifacts.
4. MemoryLedger dual-ledger crash resilience (accommodating ±1 sequence skew between ledger and trajectory snapshots).
5. Robust OS-level kernel file locking (`SingleWriterLock`) preventing ABA races.
6. Aider builder disabling repo-map (`--map-tokens 0` and config file) and stateless per-slice chat history.

Please perform a rigorous, independent code review of the following candidate diff against base commit 78feff8:

Candidate diff:
```diff
{diff_text}
```

Return ONLY strict valid JSON with the following structure:
{{
  "decision": "APPROVE" or "REJECT",
  "summary": "<one paragraph high level assessment>",
  "blockers": ["<blocking architectural or functional defect, if any>"],
  "findings": ["<non-blocking suggestions or observations>"]
}}
"""

payload = {
    "model": "gpt-5.6-sol",
    "messages": [
        {"role": "user", "content": prompt}
    ],
    "temperature": 0.2,
    "max_tokens": 4096
}

print("Dispatching review request to Sol Reviewer (gpt-5.6-sol on port 13844)...")
req = urllib.request.Request(
    "http://localhost:13844/v1/chat/completions",
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer agt_codex_N0ogpcmP85D728nGpWbVU5YRbdLpCtrA"
    },
    data=json.dumps(payload).encode("utf-8")
)

try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        sol_out = res_data["choices"][0]["message"]["content"]
        with open("C:/Users/HH18/sol_eval_out.txt", "w", encoding="utf-8") as out_f:
            out_f.write(sol_out)
        print("Sol Review completed successfully.")
except Exception as e:
    print(f"Error calling Sol: {e}")
    sys.exit(1)
