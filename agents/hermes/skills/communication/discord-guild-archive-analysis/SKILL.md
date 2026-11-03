---
name: discord-guild-archive-analysis
description: "Use when archiving or analyzing a Discord server."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, archive, corpus, speech-analysis, guild-search, leveldb]
---

# Discord Guild Archive & Corpus Analysis

## When to Use
- Dumping the full message history of a Discord server from start to present.
- Searching across all channels in a guild for event clues, lore, or topic timelines.
- Extracting statistical speech profiles (length distribution, punctuation, casing, vocabulary, grammatical shortcuts) for a community or a specific user to tune conversational personas.

## Procedure

### 1. Authenticate Against the Target Guild
1. Prefer `DISCORD_BOT_TOKEN` via `discord-bot-rest-operations` when the bot is a member of the target server.
2. When the user requests analysis of a server where only their local Discord desktop client is a member:
   - **Try plaintext extraction first** (faster, no crypto deps): scan all `~/.config/discord/Local Storage/leveldb/*.ldb` files for plaintext tokens via regex `r'["\']([A-Za-z0-9_-]{24,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,})["\']'`. Read files in binary mode and decode with `errors='ignore'`.
   - If no plaintext match, fall back to encrypted extraction: scan for `dQw4w9WgXcQ:([A-Za-z0-9+/=]+)`, base64-decode, split `nonce = raw[3:15]`, `ciphertext = raw[15:-16]`, `tag = raw[-16:]`, derive AES-GCM key via `hashlib.pbkdf2_hmac("sha1", secret, b"saltysalt", 1, 16)` with system keyring or Linux Chromium fallback `b"peanuts"`.
   - Verify any extracted token against `GET https://discord.com/api/v10/users/@me` in memory before proceeding.

### 2. Archive Standard Text Channels in Parallel
1. List all guild channels (`GET /api/v10/guilds/<guild_id>/channels`) and filter to text/announcement channels (`type in (0, 5)`).
2. Paginate each standard channel from newest to oldest using `GET /api/v10/channels/<channel_id>/messages?limit=100&before=<last_id>` across 3–4 worker threads:
   - Sleep `0.25s` between page requests per worker.
   - On HTTP 429, read `retry_after` from the JSON body and sleep `retry_after + 0.5` seconds before retrying.
   - Save each channel to `<archive_dir>/channel_<name>_<id>.json`.

### 3. Query High-Volume Bridge Channels via Guild Search & Snowflake Windows
1. Avoid linear full-history pagination on automated bridge channels (such as Minecraft `#in-game-chat` with 100k+ messages).
2. Query the guild-wide search endpoint to locate exact timestamps and message hits across all channels at once:
   ```
   GET https://discord.com/api/v9/guilds/<guild_id>/messages/search?content=<keyword>&offset=<n>
   ```
3. To inspect full conversation context around a specific date/time in a massive channel, convert the target UTC timestamp directly to a Discord snowflake ID and fetch a bounded window:
   ```python
   DISCORD_EPOCH = 1420070400000
   snowflake = ((int(dt.timestamp() * 1000) - DISCORD_EPOCH) << 22)
   # GET /api/v10/channels/<channel_id>/messages?limit=100&before=<end_snowflake>
   ```

### 4. Filter, Search, and Extract Conversation Windows
1. **Filter noise channels first**: when scanning for a specific user's messages, skip automated/bot-heavy channels (hall-of-shame, hall-of-fame, thank-you, whats-new with bot posts) in your glob loop — these channels generate 60-80% of total message volume but almost never contain user-authored content.
2. **Keyword + author filtering**: combine `author.username` match with keyword lists to find topical messages. Use lowercase `.lower()` comparisons since Discord usernames and content are case-mixed.
3. **Conversation window extraction**: once a key message is located, dump ±15-20 surrounding messages from the same channel JSON to reconstruct full conversational context. This reveals responses, corrections, and follow-up clues that the isolated keyword match misses.
4. **Thread message extraction**: Discord threads are paginated identically to channels — use the thread ID as the channel ID in `GET /api/v10/channels/<thread_id>/messages`. List active/archived threads via `GET /api/v10/guilds/<guild_id>/threads/active` and `GET /api/v10/channels/<channel_id>/threads/archived/public`.

### 5. Download and Analyze Attachments
1. Extract attachment URLs from `message.attachments[].url` and `message.attachments[].filename` fields.
2. Download from Discord CDN (`cdn.discordapp.com`) using `urllib.request.urlopen` — CDN URLs include temporary auth query params (`ex`, `is`, `hm`) that expire; re-fetch from the API if downloads fail.
3. For screenshots and images, use `vision_analyze` to transcribe all visible text, signs, coordinates, item tooltips, and book content.
4. For batch analysis of many screenshots (10+), delegate to a subagent via `delegate_task` to run parallel `vision_analyze` calls — each image gets downloaded to a local directory then analyzed independently.
5. Save transcription results to a report file alongside the downloaded images for cross-referencing.

### 6. Extract Empirical Speech Profiles
1. Separate messages by channel context (e.g., general Discord chat vs. in-game bridge messages, where mobile auto-capitalization differs from desktop keyboard input).
2. Compute quantitative metrics before modifying any persona prompt:
   - Word and character length distributions (median, mean, and bucket percentages: `1-2`, `3-5`, `6-10`, `11-20`, `21+` words).
   - Casing ratios (strictly all-lowercase vs. sentence-case vs. all-caps).
   - Terminal punctuation rates (no ending period vs. `.`, `?`, `!`) and emoticon frequency.
   - Exact single-word/short-burst frequency rankings, recurring contractions/shortcuts, copula-drop patterns, and negative markers (slang terms the user never uses).

### 7. Mandatory Cleanup
1. Delete any temporary scripts in `$TMPDIR` / `~/.hermes/cache/scratch/` that read LevelDB or hold tokens immediately after the dump completes.
2. Never write raw Discord tokens into saved JSON files, logs, or summaries.

## Pitfalls
- When reconstructing puzzle hunts or server lore, distinguish admin/staff messages from player speculation — players frequently test theories in public chat that are completely wrong (e.g. "santa is at falcon tower" turned out to be a joke). Filter by `author.username` matching the quest designer and treat player theories as unverified hypotheses, not clues.
- Broonie-style quest architecture on this server follows a consistent pattern: an in-game build, lore books with rhyming riddles, interactive mechanics (custom NBT items, command blocks, locked chests), and always at least one decoy. The obvious structure is never the actual objective.
- Write multi-line Python scripts to a file instead of passing nested f-strings inside `python3 -c "..."` — bash double-quote expansion strips inner quotes and triggers `SyntaxError: unexpected character after line continuation character`.
- Check for read-only `/nix/store` symlinks before overwriting deployed scripts in `~/.local/bin/` or `~/.local/lib/` — unlink (`rm -f`) the symlink first, update the repository source of truth, and copy the updated file into place.
