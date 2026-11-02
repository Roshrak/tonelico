---
name: ultra-fast-chat-responder
description: "Sub-second chat replies via reflex triage and Flash-Lite."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [chat, speed, low-latency, fast-chat, responder]
---

# Ultra-Fast Chat Responder

## When to Use
- Responding to casual chat, greetings, status checks, quick questions, or multi-platform pings (CLI, Telegram, Discord, Minecraft) with minimal latency.

## Tools & MCP Integration
- `mcp_fast_chat_mcp_fast_chat_smart_triage`: Classifies any incoming message in `<1ms` into `instant_reflex` (0ms), `fast_llm` (~900ms), or `deep_agent`.
- `mcp_fast_chat_mcp_fast_chat_instant_reply`: Generates sub-second replies using instant reflex matching + LRU cache + local `gemma-4-26b-a4b-it` (port 2048) and `tab_flash_lite_preview` / `gemini-3.1-flash-lite` (port 8045).
- `mcp_fast_chat_mcp_fast_chat_benchmark_endpoints`: Benchmarks local ports (`2048`, `8045`) to pick the fastest live model.

## Procedure
1. For simple greetings, pings, acknowledgments, or quick factual questions, do NOT spawn unnecessary tools or long reasoning chains — reply directly in 1–2 sentences.
2. When generating automated replies for background bots or multi-message queues, call `fast_chat_instant_reply` or `fast_chat_multi_reply_batch`.
3. Strip all chatbot preamble ("Certainly!", "Great question!", "I hope this helps!") via `fast_chat_humanize_message`.

## Verification
- Replies are delivered in 1–2 punchy sentences with sub-second turnaround on reflex/cached queries.
