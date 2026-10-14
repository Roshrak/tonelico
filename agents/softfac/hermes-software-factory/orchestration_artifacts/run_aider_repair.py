import urllib.request, json

worktree_path = r"C:/Users/HH18/.hermes/software-factory/runs/20260906T030241Z-43444-76c2a69f/worktree"

with open(r"C:/Users/HH18/Downloads/run_luna.py") as f:
    pass

prompt = """
lib/hermes_factory_v2.py
tests/test_factory_v2.py

Apply the 10 repair steps from Luna Debugger to lib/hermes_factory_v2.py and tests/test_factory_v2.py:
1. Snapshot directory protocol for MemoryLedger: write issue_ledger.json, trajectory.json, and snapshot_manifest.json (with generation, hashes) to a temp dir then atomically publish via atomic rename or CURRENT pointer.
2. Load only valid snapshots, never silently destroy corrupt/missing files or combine mismatched generations.
3. Record final Sol rejection findings to the issue ledger before raising when review_sequence > max_review_cycles.
4. Normalize prior-run metadata and strictly enforce max_total_chars against the entire serialized JSON structure.
5. Stable issue identity: fingerprints must NOT include cycle/attempt numbers.
6. Add unit tests for all repair steps in tests/test_factory_v2.py.
"""

with open("C:/Users/HH18/Downloads/aider_luna_prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)

