---
name: telegram-experience
description: "Send media, charts, voice notes, and alerts to Telegram."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [telegram, messaging, media, voice, charts, notifications, bot, gateway]
    category: communication
    related_skills: [hermes-agent, baoyu-infographic, concept-diagrams, meme-generation, product-price-monitor]
---

# Rich Telegram Experience for Hermes Agent

## When to Use
Use whenever responding on Telegram or sending media, charts, screenshots, documents, voice notes, or scheduled alerts to the user's Telegram chat.

Deliver a fast, visual, and high-signal Telegram experience across both live Telegram Gateway sessions and CLI/background tasks.

## 1. Delivering Media in a Live Telegram Session (Gateway)

When the current conversation is running on the Telegram platform:
- **Inline Images / Screenshots / Charts:** Save the image to a durable path (e.g., `/home/aesc/.hermes/cache/scratch/chart.png`) and include `MEDIA:/absolute/path/to/file.png` in your response text. The Telegram gateway intercepts `MEDIA:` tags and uploads them as native photos/files.
- **Voice Bubbles (`sendVoice`):** Generate audio with `text_to_speech(text="...")` or include `[[audio_as_voice]]` with an `.ogg`/`.mp3` path so it renders as a playable Telegram voice note waveform.
- **Documents / PDFs / Archives:** Reference the absolute path via `MEDIA:/absolute/path/to/report.pdf` (or list it in `artifacts` when completing Kanban tasks).

## 2. Sending to Telegram from CLI, Scripts, or Background Jobs (`telegram_send.py`)

In CLI sessions (`Platform: cli`), `MEDIA:` tags are printed literally and are NOT intercepted by a gateway. To push screenshots, charts, files, voice notes, or alerts directly to the user's Telegram chat from CLI or background scripts, run `/home/aesc/.local/bin/telegram_send.py`:

```bash
# Send a text notification
/home/aesc/.local/bin/telegram_send.py --text "Build finished and verified."

# Send a screenshot or generated chart image
/home/aesc/.local/bin/telegram_send.py --photo /home/aesc/.hermes/cache/scratch/chart.png --caption "Price comparison chart"

# Send a PDF, DOCX, XLSX, or archive
/home/aesc/.local/bin/telegram_send.py --document /home/aesc/.hermes/cache/scratch/report.pdf --caption "Full report"

# Send a message with clickable inline URL buttons
/home/aesc/.local/bin/telegram_send.py --text "View listing:" --buttons '[[{"text":"Open Listing","url":"https://chotot.com"}]]'
```

## 3. Visual-First Telegram Responses

Whenever a response involves comparisons, prices, system metrics, architecture, or desktop state, pair concise text with a visual artifact:
- **Hardware / Marketplace Prices:** Run `/home/aesc/.local/bin/gpu_market_search.py "<query>"` (automatically generates and sends the comparison chart photo to Telegram) and include an ASCII bar chart in text.
- **Diagrams & Infographics:** Use `concept-diagrams`, `excalidraw`, `architecture-diagram`, or `baoyu-infographic` to render clean visuals and send the image to Telegram.
- **Desktop Proof:** Capture the window or screen with `grim` or `computer_use(action="capture")` and send the screenshot when the user asks to see what is on the monitor.

## 4. Scheduled Alerts & Monitoring to Telegram (`cronjob_manage`)

When scheduling recurring checks (price drops, watchers, daily briefings, server health) that should notify the user on Telegram:
- Always set `deliver="telegram"` in `cronjob_manage(action="create", ...)` so the output lands directly in the user's Telegram chat even if created from the CLI.

## 5. Formatting Best Practices for Telegram Mobile Reading

- Lead with the bottom-line answer or status in the first line.
- Keep paragraphs short (2-3 lines max) so messages are scannable on a phone screen.
- Use compact bullet points and monospace values for commands, paths, and prices.
- Avoid wide multi-column tables on Telegram mobile (they wrap poorly on narrow screens); prefer stacked bullet cards or a rendered PNG chart via `telegram_send.py --photo`.
