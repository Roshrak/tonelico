# Antigravity Proxy Pool & Single-Turn Batch Remediation Guide

## 1. Antigravity Proxy Pool Immutable Configuration
To ensure `agy CLI` utilizes the multi-account proxy pool and avoids individual OAuth quota blocks (`RESOURCE_EXHAUSTED 429`):
- `~/.gemini/antigravity-cli/settings.json`:
  ```json
  {
    "model": "Gemini 3.8 Flash (High)",
    "modelProvider": "gemini",
    "trustedWorkspaces": ["C:\\Users\\HH18"]
  }
  ```
- System environment variables:
  ```bash
  export GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:8045"
  ```
- **Rule**: Never modify, remove, or switch these endpoints to personal OAuth credentials during quota recovery.

## 2. Single-Turn Batch Remediation Protocol
- When Sol Reviewer rejects a milestone with technical findings:
  - **Single-turn execution**: Prompt Builder with **EXACTLY ONE executable prompt** that directly performs source code fixes, runs tests, and creates a git commit.
  - **No Planning Turns**: Do NOT allow Builder to generate a plan, analyze in one turn, and execute in a second turn. Planning turns waste tokens, delay resolution, and violate batch remediation contracts.
  - **Scope**: Collate 100% of open findings into a single batch remediation round.
