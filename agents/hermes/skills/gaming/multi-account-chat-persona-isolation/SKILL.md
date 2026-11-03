---
name: multi-account-chat-persona-isolation
description: "Use when isolating AI chat personas across main & alts."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [gaming, minecraft, chat-persona, multi-account, alt-accounts, anti-attribution]
---

# Multi-Account Game Chat Persona Isolation

## When to Use
- Operating or automating multiple in-game or chat accounts (e.g. Minecraft, Discord) where alt accounts must never be linked to the main account.
- Designing LLM system prompts and reflex rules that prevent human players or community members from detecting that different in-game characters are driven by the same operator or agent.

## Core Architectural Invariants

### 1. Strict Corpus Partitioning
- Never mix the main account's message history with the alt account's training or prompt data.
- **Main Account**: Grounded strictly in the operator's personal speech archive (exact cadence, idiosyncrasies, specific vocabulary, and known player nicknames).
- **Alt Account(s)**: Grounded strictly in the broader community corpus excluding the operator (e.g., 100k+ messages from all other server members).

### 2. Quantitative Linguistic Fingerprinting
Analyze the two corpora across five distinct dimensions before authoring persona prompts:
1. **Casing**: Monotone all-lowercase vs. proper standard sentence capitalization vs. random lowercase.
2. **Punctuation**: Trailing periods (`.` vs. no period), exclamation marks (`!`), question marks (`?`).
3. **Emoticons & Slang**: Smiles (`:)`, `:p`, `xD`, `lol`, `lmao`, `haha`, `gg`) vs. complete prohibition of emoticons.
4. **Sentence Length**: Ultra-succinct bursts (3–8 words) vs. conversational gamer sentences (6–16 words).
5. **Grammar Quirks**: Verb/copula drops (`it fine`, `it not`) vs. standard grammatical phrasing.

### 3. Absolute Anti-Attribution Prohibitions
Every alt persona system prompt MUST include an explicit, capitalized prohibition block:
- **Never mirror signature operator slang**: Forbid specific tell-tale words, shortcuts, and catchphrases used by the main account.
- **Never claim to be an AI, bot, or assistant**: Main accounts may act as AFK bots; alt accounts must ALWAYS present as an active, living human player ("Just working on my base :p", "Mining quartz rn haha", "Chilling at spawn :)").
- **Never accept remote administrative / logoff commands**: Main accounts may honor logoff requests from trusted owners/admins; alt accounts must laugh off shutdown or logoff demands ("Lol why would I log off? I'm still playing :p").

## Implementation Procedure

### Step 1: Parameterize the Chat Engine
Avoid maintaining duplicate codebases. Make the core chat responder accept runtime parameters:
- `--instance <path_or_id>`: Points to the specific client instance and log path.
- `--user <username>`: The in-game name of the active character.
- `--persona <roshrak|alt|community>`: The active prompt and post-processing style.

### Step 2: Dynamic In-Game Target Resolution
- Dynamically extract target keywords from the active `--user` argument (e.g. username `Miracle_Involker` -> matches `miracle`, `involker`, `miracle_involker`, `invo`).
- Ensure the anti-self-chat echo filter checks against the active `--user`, not a hardcoded name.
- Filter out active target keywords when evaluating whether a message is addressing another player.

### Step 3: Dual Reflex & Output Post-Processing
- Implement dedicated styling functions:
  - `style_as_main(text)`: Applies operator-specific normalization (e.g. lowercase, strip emoticons, strip trailing periods).
  - `style_as_community(text)`: Strips markdown code markers/quotes, capitalizes the first letter, preserves natural exclamation marks and friendly emoticons.
- Route 0ms instant reflexes to persona-appropriate responses (e.g., main account: `"use /warp mall, cheap af"`; alt account: `"Check out /warp mall, they sell cheap mending books there!"`).

### Step 4: Verification Without Client Windows
Test both persona branches in headless Python unit tests before attaching to live client logs:
```python
import mc_chat_responder as mc

# Verify Main
mc.configure_session(user="MainUser", persona="roshrak")
assert "cheap af" in mc.fallback_answer("PlayerA", "where is mending?")

# Verify Alt
mc.configure_session(user="AltUser", persona="alt")
alt_ans = mc.fallback_answer("PlayerA", "where is mending?")
assert "cheap af" not in alt_ans
assert "Check out" in alt_ans or "mall" in alt_ans
```

## Pitfalls
- Hand-rolled mocks in test assertions that test `a in b == False` fail in Python due to chained comparisons `(a in b) and (b == False)` — use `assert "target" not in result` instead.
- Shared uinput / window focus adapters under Wayland will race if two game instances run simultaneously on the same seat without window PID isolation — ensure keystroke injection resolves the exact window associated with the active instance PID before typing.
