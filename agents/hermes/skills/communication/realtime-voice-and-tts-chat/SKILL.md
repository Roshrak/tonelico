---
name: realtime-voice-and-tts-chat
description: "Fast TTS voice notes and Whisper STT for voice chatting."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [voice, tts, stt, whisper, telegram-voice]
---

# Realtime Voice & TTS/STT Chat Loop

## When to Use
- Converting chat replies into spoken audio or Telegram voice notes (`[[audio_as_voice]]`), or transcribing incoming voice messages with Whisper/Gemini STT.

## Tools & MCP Integration
- Built-in `stt` and `tts` toolsets + `whisper` skill.
- `mcp_fast_chat_mcp_fast_chat_instant_reply`: Generates concise 1–2 sentence spoken scripts ideal for low-latency TTS synthesis.
- `telegram-experience`: Delivers `.ogg`/`.mp3` voice bubbles to Telegram.

## Procedure
1. Keep spoken chat responses under 25 words so TTS synthesis and playback start in under 1 second.
2. Strip all symbols, URLs, and markdown before passing text to TTS.
