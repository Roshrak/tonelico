import urllib.request, json

findings = [
    "High: MemoryLedger._flush() atomically replaces each JSON file independently, but does not atomically publish issue_ledger.json and trajectory.json as one snapshot. A crash between writes exposes mismatched generations. Worse, _load_or_init() does not validate consistency: it combines the maximum sync_seq with data from potentially different snapshots, and if either file is missing or corrupt it silently initializes and flushes an empty ledger, destroying recoverable history. check_snapshot_consistency() only detects a mismatch after the fact and therefore does not provide the planned atomic snapshot consistency.",
    "High: Final Sol rejection findings are not persisted to issue_ledger.json. When review_sequence exceeds max_review_cycles, the code records only a trajectory event and raises before the loop that calls record_or_update_issue(). Since load_prior_run_context() discloses ledger issues rather than trajectory events, the terminal unresolved feedback is unavailable to the next run, undermining continual improvement.",
    "Medium: load_prior_run_context() does not strictly enforce max_total_chars. It counts only the serialized selected issue objects, excluding the enclosing context, truncation notice, safety note, ledger_summary, and other fields. Several copied fields are also not bounded or type-normalized. Consequently the returned context can exceed max_total_chars even for valid generated data, and tampered prior-run metadata can bypass the intended context bound entirely.",
    "Medium: Multi-loop issue deduplication and regression tracking are largely defeated by cycle-specific titles. Test issues include the test sequence, Luna issues include the attempt or review sequence, and Sol findings include the review sequence; these values are part of the fingerprint. The same underlying failure recurring in a later loop therefore becomes a new issue rather than incrementing occurrences or transitioning a resolved issue to regressed."
]

luna_prompt = f"""You are Luna Debugger. Analyze the following Sol Reviewer findings and output concrete, precise repair steps:
{json.dumps(findings, indent=2)}

Return ONLY a JSON object:
{{
  "analysis": "...",
  "repair_steps": [
    "Step 1: ...",
    "Step 2: ..."
  ]
}}
"""

payload = {
    "model": "gpt-5.6-luna",
    "messages": [{"role": "user", "content": luna_prompt}],
    "reasoning_effort": "xhigh",
    "response_format": {"type": "json_object"}
}

req = urllib.request.Request(
    "http://localhost:13844/v1/chat/completions",
    headers={"Authorization": "Bearer agt_codex_N0ogpcmP85D728nGpWbVU5YRbdLpCtrA", "Content-Type": "application/json"},
    data=json.dumps(payload).encode("utf-8")
)

res = urllib.request.urlopen(req, timeout=120)
print("Luna status:", res.status)
print("Luna output:\n", json.loads(res.read().decode("utf-8"))["choices"][0]["message"]["content"])
