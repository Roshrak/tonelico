import subprocess
import sys

def run():
    with open("C:/Users/HH18/sol_review_prompt.txt", "r", encoding="utf-8") as f:
        prompt = f.read()

    cmd = [
        "codex", "exec",
        "-m", "gpt-5.6-sol",
        "-c", "model_reasoning_effort=\"high\"",
        "--ephemeral",
        "--skip-git-repo-check",
        "-o", "C:/Users/HH18/sol_step1_review.md",
        prompt
    ]
    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    print("RETURNCODE:", res.returncode)
    print("STDOUT:", res.stdout[:500])
    print("STDERR:", res.stderr[:500])

if __name__ == "__main__":
    run()
