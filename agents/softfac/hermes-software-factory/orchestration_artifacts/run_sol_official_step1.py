import os
import sys
import json
import subprocess
from pathlib import Path

REPO_DIR = Path(r"C:\Users\HH18\Downloads\hermes-software-factory-v2-hoh\hermes-software-factory-v2")
sys.path.insert(0, str(REPO_DIR / "lib"))
from hermes_factory_v2 import CodexRoleClient

def main():
    diff_res = subprocess.run(["git", "-C", str(REPO_DIR), "diff", "main"], capture_output=True, text=True)
    diff_text = diff_res.stdout

    prompt = f"""You are Sol Reviewer (high reasoning), the strict quality and architecture gatekeeper of Software Factory v2 (HOH).
We are reviewing Step 1: replacing Aider with agy CLI while maintaining full HOH fail-closed isolation and backward compatibility.

Here is the full git diff of our changes:
```diff
{diff_text}
```

Evaluate these changes thoroughly against fail-closed isolation, sandbox security, backward compatibility, and correctness:
1. Does AgyBuilder properly invoke `agy` with `--sandbox`, `--model`, `--output-format json`, `--disable-slash-commands`, `--dangerously-skip-permissions`, `--add-dir`, and `--print`?
2. Does `clean_builder_generated_artifacts` safely handle only exact known cache files/directories, fail closed if untracked files have unknown extensions, and avoid touching the source repo?
3. Does `_changed_files` / `_scope_check` properly manage cleanup before inspecting git changes, without risk of erasing user data?
4. Are `json.loads` return types validated to be dicts?
5. Does the test suite pass and are backwards compatibility aliases preserved?

Return your response strictly as a single raw JSON object (and nothing else):
{{"verdict": "APPROVE", "feedback": "<concise explanation>"}}
or
{{"verdict": "REJECT", "feedback": "<concise explanation>"}}
"""

    client = CodexRoleClient(r"C:\Users\HH18\AppData\Local\hermes\bin\codex.cmd")
    run_dir = Path(r"C:\Users\HH18")
    res = client.call(
        role="Sol Reviewer",
        provider="openai-codex",
        model="gpt-5.6-sol",
        prompt=prompt,
        usage_path=run_dir / "sol_step1_official.usage.json",
        output_path=run_dir / "sol_step1_official.output.txt",
        timeout=900,
        reasoning="high"
    )
    print("SOL OFFICIAL RESULT:", res)
    with open(run_dir / "sol_official_verdict.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

if __name__ == "__main__":
    main()
