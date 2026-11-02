---
name: screen-region-ocr-automation
description: "Capture Wayland screenshots and read GUI text via PaddleOCR."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [screenshot, grim, ocr, computer-use, vision]
---

# Screen Capture & Live GUI OCR Automation

## When to Use
- Reading text from a desktop window, dialog box, game HUD, or image-based UI where accessibility tree nodes are unavailable.

## Tools & MCP Integration
- `mcp_desktop_computer_use_mcp_cu_take_screenshot`: Captures full screen or `X,Y WxH` region via `grim`.
- `mcp_desktop_computer_use_mcp_cu_screenshot_ocr`: Captures screenshot and immediately extracts all visible text lines via PaddleOCR.
- `vision_analyze`: Inspects the captured PNG visually with optional pixel region cropping.

## Procedure
1. Ensure the target window is visible/focused via `cu_focus_window`.
2. Call `cu_screenshot_ocr` (or `cu_take_screenshot` + `vision_analyze` for visual layout/icons).
3. Ground your next GUI click or keystroke in the exact extracted coordinates/text.

## Verification
- Screenshot file exists in `/home/aesc/.hermes/cache/scratch/` and extracted OCR text is non-empty.
