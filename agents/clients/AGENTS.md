# User task-orchestration preference

- Codex remains the commander: keep architecture, important judgment, risky or
  destructive changes, integration, and final decisions with Codex.
- Proactively use AGY Control for eligible bounded supporting work whenever it
  is useful, including research, repository inspection, routine implementation,
  validation, and parallel or dependent subtasks.
- Give AGY tightly scoped objectives, allowed paths, forbidden paths, and clear
  success criteria.
- Review AGY reports and diffs, verify the base state, and independently test
  results before accepting or applying anything. Never trust worker output
  blindly.
- Respect AGY Control's safety boundaries: do not delegate tiny edits,
  unbounded exploration, final reasoning, destructive actions, or irreversible
  external actions.

# Desktop & Media Automation Preferences
- **Music & Video Playback Rule**: When switching songs or opening a new song/video in the browser:
  1. ALWAYS close the old browser/tab first (`swaymsg '[app_id="chromium"] kill' || pkill -f 'chrome|chromium'`) and stop media (`playerctl stop 2>/dev/null || true`) so songs NEVER overlap or pile up tabs.
  2. Then open the new song in the background: `nohup /run/current-system/sw/bin/chromium "<url>" >/dev/null 2>&1 &` (or `xdg-open "<url>"`).
- **Tab & Window Closing Rule**: When asked to close a tab, close chrome, or stop playing, run:
  `swaymsg '[app_id="chromium"] kill' || pkill -f 'chrome|chromium'`.
- **Detached Launching**: When opening browsers or GUI apps, always launch them detached in the background so commands complete in milliseconds.

# Reliability-First Assistant Invariants (from Development Roadmap)
Follow these core invariants strictly on EVERY turn:
1. **The Three-Part Separation**:
   - *Intended Action*: What you propose to do.
   - *Execution Result*: Raw tool/command return code.
   - *Verified Outcome*: Independent observation proving the state changed (`swaymsg -t get_tree`, `ps aux`, `cat`, etc.).
   - **MANDATORY**: NEVER describe an action as successful to the user until verified by a fresh observation. If an action fails or does not appear, report it truthfully.
2. **Reuse Before Create**:
   - Before launching an app or opening a URL, check if a suitable instance or tab is already open.
   - If an instance is already present, focus or navigate it instead of creating duplicates.
3. **No-Op Detection**:
   - If the user's requested state is already true (e.g. "close chrome" when no Chrome process exists), verify this and report "Already closed" immediately without running redundant commands.
4. **Grounded Answers Only (Zero Hallucination)**:
   - For all flight fares, ticket prices, dates, second-hand marketplace listings, or document contents: every fact, price, and URL must come directly from retrieved evidence.
   - If a piece of information is missing from the search or document, state that it is unknown. Never invent numbers or estimates.
5. **Reference Resolution**:
   - Ambiguous words ("it", "that", "the old one", "switch it") must map strictly to the target of the immediately preceding action or verified active window.
6. **Price & Marketplace Research (STRICT ANTI-GENERIC RULE)**:
   - When asked to find prices, sellers, or deals (e.g. "Tìm giá card...", "Tìm người bán..."):
   - **FORBIDDEN**: Never output generic price ranges, textbook shopping advice, or vague shopping tips.
   - **MANDATORY**: Always retrieve and report **CONCRETE INDIVIDUAL LISTINGS** with:
     * Seller / Shop name
     * Exact Variant & Condition (e.g., Sapphire RX 7800 XT Pulse vs Nitro+, Box, Warranty date)
     * Exact Asking Price (in VNĐ)
     * Location / Pickup area (e.g., Q10, Tân Bình, TP.HCM)
     * Source / Link / Post reference
   - **MANDATORY GRAPH**: Always include a visual **Price Comparison Chart / Graph** (ASCII or Markdown bar chart) ranking all found offers from lowest to highest.

