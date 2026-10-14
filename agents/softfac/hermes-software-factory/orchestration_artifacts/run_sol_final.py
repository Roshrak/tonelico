import subprocess
import json
from pathlib import Path
import sys

REPO_DIR = Path(r"C:\Users\HH18\Downloads\hermes-software-factory-v2-hoh\hermes-software-factory-v2")
sys.path.insert(0, str(REPO_DIR / "lib"))
from hermes_factory_v2 import CodexRoleClient

def get_git_diff():
    res = subprocess.run(["git", "diff", "main..HEAD"], cwd=REPO_DIR, capture_output=True, text=True, check=True)
    return res.stdout

def main():
    diff_text = get_git_diff()
    print(f"Git diff length: {len(diff_text)} characters")

    system_prompt = (
        "You are Sol, the relentless, fail-closed principal software engineer and security reviewer for Hermes Software Factory v2 (HOH architecture).\n"
        "Your task is to thoroughly review the changes made to completely replace Aider with Agy CLI (`gemini-3.8-flash-high`) while preserving the HOH protocol.\n"
        "CRITICAL REVIEW DIRECTIVES:\n"
        "1. Fail-closed Isolation: Verify how AgyBuilder enforces filesystem boundaries. Since Agy CLI runs with `--sandbox` and `--dangerously-skip-permissions`, verify that Hermes actively tracks and asserts the source checkout (`repo`) and worktree containment (`_assert_source_unchanged`), so that ANY escape or untracked modification to the source repository fails closed with FactoryError.\n"
        "2. Strict Artifact Cleanup: Verify `clean_builder_generated_artifacts`. Check that only known builder cache files (`.gemini/logs/*`, `.agy/*`, `.aider.tags.cache.v4/tags.db`) are deleted in disposable worktrees, and that user files (like `user_notes.db`, `my_cache.cache`) or directories are strictly preserved and never clobbered.\n"
        "3. Builder Preflight: Verify that preflight strictly requires a valid JSON payload with `status == 'SUCCESS'` and `response == 'BUILDER_PREFLIGHT_OK'`, rejecting raw plaintext or non-dict payloads.\n"
        "4. SHA256SUMS and Documentation: Verify that SHA256SUMS accurately tracks modified files and README reflects Agy direct execution.\n"
        "5. Test Coverage & Integrity: Verify test suite covers preflight rejection, safe cache cleaning, and unchanged source checkout.\n"
        "6. Output Verdict: You MUST output a valid JSON object ONLY (no surrounding text or markdown, or fenced with ```json) with keys:\n"
        "   \"verdict\": \"APPROVED\" or \"REJECT\",\n"
        "   \"summary\": \"concise summary\",\n"
        "   \"reviewed_files\": [\"list\", \"of\", \"files\"],\n"
        "   \"feedback\": [\"feedback items\"],\n"
        "   \"concerns\": [\"concerns\"],\n"
        "   \"blocking_issues\": [\"blocking issues if any\"]\n"
    )

    user_prompt = (
        "Here is the complete git diff against main:\n\n"
        "```diff\n"
        f"{diff_text}\n"
        "```\n\n"
        "Please evaluate the entire solution across all dimensions (isolation, cleanup, preflight, tests, docs, checksums) and provide your final verdict JSON."
    )

    prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

    client = CodexRoleClient()
    output_path = Path(r"C:\Users\HH18\sol_final.output.txt")
    usage_path = Path(r"C:\Users\HH18\sol_final.usage.json")

    print("Calling Sol High via CodexRoleClient (timeout=1200s)...")
    structured = client.call(
        role="sol",
        provider="openai-codex",
        model="gpt-5.6-sol",
        prompt=prompt,
        usage_path=usage_path,
        output_path=output_path,
        timeout=1200,
        reasoning="high",
    )

    with open(r"C:\Users\HH18\sol_final_verdict.json", "w", encoding="utf-8") as f:
        json.dump(structured, f, indent=2, ensure_ascii=False)

    print("Sol verdict received successfully!")
    print(json.dumps(structured, indent=2))

if __name__ == "__main__":
    main()
