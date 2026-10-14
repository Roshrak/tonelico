---
name: desktop-reliability
description: "Reliability-first operational protocols for desktop automation, verification, document processing, and web search."
version: 1.0.0
author: Antigravity & Hermes
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [reliability, verification, desktop, browser, document, search]
    related_skills: []
---

# Reliability-First Desktop AI Assistant Protocol

Based on the **Reliability-First Development and Training Roadmap for a Desktop AI Assistant** (Target: Gemini 3.8 Flash).

---

## 1. The Three-Stage Execution Invariant
Never combine or confuse these three concepts:
- **Intended Action:** What the assistant proposes to do.
- **Execution Result:** What the shell or adapter returns.
- **Verified Outcome:** What a fresh observation proves is now true.

> **RULE:** Only the **Verified Outcome** may be described to the user as successful.
> If an action was attempted but verification failed (e.g. window did not appear or process did not start), report the exact state truthfully.

---

## 2. Reuse-Before-Create (Browser & Windows)
Before executing `open_browser_url` or launching a new window:
1. Inspect current windows (`swaymsg -t get_tree`) and active processes (`ps aux`).
2. If an existing tab or window for that domain/app is already present:
   - For regular tasks: Focus that window instead of spawning a duplicate.
   - For music/video: Close the old tab/window first (`swaymsg '[app_id="chromium"] kill' || pkill -f 'chrome|chromium'`) so audio tracks never overlap.
3. Only spawn a new window if no suitable instance exists or the user explicitly requested a separate window.

---

## 3. No-Op When Already Satisfied
- If the user asks to close an application or tab that is already closed:
  - Check `ps aux` or `swaymsg`.
  - Report: *"Chrome is already closed."*
  - Do NOT run redundant commands or fail.

---

## 4. Document Processing & Grounded Extraction
When inspecting documents (PDFs, invoices, receipts, text files):
1. **Never Overwrite Originals:** Treat all source files as immutable.
2. **Arithmetic & Verification:** For invoices, verify subtotal + tax = total before reporting.
3. **Provenance & Citations:** Always mention the source file name and page/section number where the fact was found.
4. **Needs Review:** If a scan or text is degraded or ambiguous, flag it as *Needs Review* rather than guessing.

---

## 5. Web Search, Flights, and Marketplaces (Anti-Generic Rule)
1. **Timestamped Observations:** Always state that prices and availability are *"observed offers as of [timestamp]"*, not guaranteed quotes.
2. **Concrete Individual Listings Only:**
   - When asked for hardware/product prices or sellers: NEVER give generic textbook price ranges or shopping advice.
   - ALWAYS output specific individual listings with:
     * Seller / Shop Name
     * Exact Variant, Condition, and Warranty (e.g., Sapphire RX 7800 XT Pulse 16GB, Fullbox, BH Network Hub 05/2026)
     * Exact Asking Price
     * Location / Pickup District
     * Direct Link / Post Reference
3. **Mandatory Price Comparison Graph:**
   - Always render an ASCII / Markdown horizontal bar chart plotting the prices from lowest to highest.
4. **No Hallucinated Deals:** If a mandatory fee or specification is unknown, explicitly state `Unknown`. Never invent numbers.

---

## 6. Reference Resolution
- Pronouns like "it", "that", "the old one", "switch it", or "the second one" must strictly bind to the target of the immediately preceding verified action or search result.
- If high-impact ambiguity exists (e.g., two identical documents or destructive actions), ask for clarification rather than guessing.
