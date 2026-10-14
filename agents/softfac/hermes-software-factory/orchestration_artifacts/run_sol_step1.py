import subprocess
import os

repo_dir = "C:/Users/HH18/Downloads/hermes-software-factory-v2-hoh/hermes-software-factory-v2"

# 1. Get real git diff
res_diff = subprocess.run(["git", "-C", repo_dir, "diff"], capture_output=True, text=True)
real_diff = res_diff.stdout

# 2. Run unit tests to capture real test output
res_test = subprocess.run(["python", "-m", "unittest", "tests/test_factory_v2.py"], cwd=repo_dir, capture_output=True, text=True)
test_output = res_test.stdout + ("\n" + res_test.stderr if res_test.stderr else "")

prompt = f"""You are Sol Reviewer, the adversarial reviewer for Hermes Software Factory v2 (HOH protocol).
Evaluate Step 1 of the migration plan: replacing Aider with Agy CLI in lib/hermes_factory_v2.py and tests/test_factory_v2.py.

Context and changes made:
- Default builder model is updated to `gemini-3.8-flash-high`.
- Config.__post_init__ automatically normalizes legacy model names (strips `openai/` prefix).
- AgyBuilder implemented:
  - preflight uses exact stripped string equality on raw stdout or structured response in SUCCESS json, NO --dangerously-skip-permissions during preflight probe.
  - run() executes agy with --model, --output-format json, --disable-slash-commands, --sandbox, --add-dir <worktree>, --dangerously-skip-permissions, --print.
  - Fail-closed JSON verification: validates result.stdout is valid JSON with status == "SUCCESS"; malformed, empty, or non-success raises FactoryError.
  - Fail-closed isolation: --sandbox flag passed to agy, confinement instructions added, clean_builder_generated_artifacts checks tracked files before removing untracked .gemini/.agy/.aider.tags.cache.v4, and cleans before both _source_status and _changed_files to avoid false isolation/scope alarms.
- AiderBuilder preserved with backward-compatible constructor surface (__init__(builder_bin=None, aider_bin=None), self.aider_bin = self.agy_bin).
- CLI argument --agy-model added as alias for --builder-model.
- Unit tests in tests/test_factory_v2.py updated to test AgyBuilder, preflight and run mocks return matching contracts.

REAL GIT DIFF:
```diff
{real_diff}
```

TEST SUITE EXECUTION OUTPUT:
```
{test_output}
```

Evaluate if Step 1 meets the HOH contract and strict fail-closed isolation standards.
Provide your verdict in exact format:
Verdict: APPROVE or REJECT
Feedback: <concise actionable review feedback>
"""

with open("C:/Users/HH18/sol_step1_prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)

cmd = [
    "C:/Users/HH18/AppData/Local/hermes/bin/codex.cmd", "exec",
    "-m", "gpt-5.6-sol",
    "-c", "model_reasoning_effort=\"high\"",
    "--ephemeral",
    "--skip-git-repo-check",
    "-o", "C:/Users/HH18/sol_step1_verdict.md",
    "-"
]
print("Running Sol review with real diff...")
with open("C:/Users/HH18/sol_step1_prompt.txt", "rb") as f_in:
    res = subprocess.run(cmd, stdin=f_in, capture_output=True, text=True)
print("Returncode:", res.returncode)
print("Stdout:", res.stdout[-500:] if res.stdout else "none")
print("Stderr:", res.stderr[-500:] if res.stderr else "none")
