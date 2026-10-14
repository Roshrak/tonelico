---
name: agy-env-provenance-guide
description: Guide for AGY environments and commit provenance gating.
version: 1.0.0
---

# AGY Environments and Commit Provenance Guide

Guide for environment switching and commit provenance verification in AGY workflows.

## 1. Environment Switching (Proxy Pool vs Google Auth)
- **Google Auth:** Ensure `~/.gemini/antigravity-cli/settings.json` omits `"modelProvider": "gemini"`. Clean env vars: `GOOGLE_GEMINI_BASE_URL` and `GEMINI_API_KEY`.
- **Proxy Pool:** Require `"modelProvider": "gemini"` in `settings.json` and export `GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:8045"`.

## 2. Multi-turn Quota vs Short Probes
Short probe `1+1=?` can succeed while multi-turn agent sessions fail if streaming quota or conversation title generation hits 429 (`All accounts exhausted`). Always inspect `~/.gemini/antigravity-cli/cli.log` when AGY exits silently.

## 3. Commit Provenance Invariant
Never record anticipated commit hashes into manifests before committing. Commit code changes first, capture exact `git rev-parse HEAD` and `git rev-parse HEAD^{tree}`, update provenance manifests, and `git commit --amend --no-edit`.
