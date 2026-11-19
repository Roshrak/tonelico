#!/usr/bin/env python3
import os
import sys
import time
import re
import json
import stat
import socket
import sqlite3
import struct
import hashlib
import datetime
import logging
import subprocess
import urllib.request
import urllib.error
import collections

LOG_PATH = "/home/aesc/.local/share/PrismLauncher/instances/Fabulously Optimized/minecraft/logs/latest.log"
ACTIVE_INSTANCE = "Fabulously Optimized"
ACTIVE_USER = "Roshrak"
ACTIVE_PERSONA = "roshrak"  # 'roshrak' or 'alt'
TARGET_NAMES = ["roshrak", "roshak", "morgan", "rosh"]

def configure_session(user: str = None, persona: str = "auto", instance: str = "Fabulously Optimized", log: str = None):
    global ACTIVE_USER, ACTIVE_PERSONA, ACTIVE_INSTANCE, TARGET_NAMES, LOG_PATH
    if user:
        ACTIVE_USER = user
    if instance:
        ACTIVE_INSTANCE = instance
    if log:
        LOG_PATH = log
    elif instance:
        LOG_PATH = f"/home/aesc/.local/share/PrismLauncher/instances/{instance}/minecraft/logs/latest.log"

    if persona == "auto":
        if "miracle" in ACTIVE_USER.lower() or instance == "asDFasfd":
            ACTIVE_PERSONA = "alt"
        else:
            ACTIVE_PERSONA = "roshrak"
    else:
        ACTIVE_PERSONA = persona

    if ACTIVE_PERSONA == "alt":
        u_clean = ACTIVE_USER.lower()
        parts = re.split(r'[_ -]+', u_clean)
        TARGET_NAMES = list(set([u_clean, *[p for p in parts if len(p) >= 3]]))
    else:
        TARGET_NAMES = ["roshrak", "roshak", "morgan", "rosh"]

    logger.info(f"Configured session: user={ACTIVE_USER}, persona={ACTIVE_PERSONA}, targets={TARGET_NAMES}, log={LOG_PATH}")

UINPUT_BIN = "/home/aesc/.local/bin/uinput_type"
BRIDGE_URL = "http://127.0.0.1:8765/v1/chat/completions"
def _load_local_secret(env_var: str, env_file: str, file_key: str) -> str:
    val = os.environ.get(env_var, "").strip()
    if val:
        return val
    for candidate, k in (
        (os.path.expanduser("~/.hermes/.env"), env_var),
        (os.path.expanduser(f"~/{env_file}"), file_key),
    ):
        try:
            if os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if line.startswith(f"{k}="):
                            return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    if env_file == ".antigravity_tools/gui_config.json":
        try:
            cfg_p = os.path.expanduser("~/.antigravity_tools/gui_config.json")
            if os.path.exists(cfg_p):
                with open(cfg_p, "r", encoding="utf-8") as fh:
                    return json.load(fh).get("proxy", {}).get("api_key", "not-needed")
        except Exception:
            pass
    return "not-needed"

FAST_BRIDGE_ENDPOINTS = [
    ("http://127.0.0.1:2048/v1/chat/completions", "gemini-4-hydrogen-low", _load_local_secret("AISTUDIO2API_API_KEY", "aistudio2api/.env", "PROXY_API_KEY")),
    ("http://127.0.0.1:8045/v1/chat/completions", "gemini-4-hydrogen-low", _load_local_secret("AGY_ROTATOR_API_KEY", ".antigravity_tools/gui_config.json", "api_key")),
    ("http://127.0.0.1:2048/v1/chat/completions", "gemini-4-hydrogen-xhigh", _load_local_secret("AISTUDIO2API_API_KEY", "aistudio2api/.env", "PROXY_API_KEY")),
    ("http://127.0.0.1:8045/v1/chat/completions", "gemini-4-hydrogen-xhigh", _load_local_secret("AGY_ROTATOR_API_KEY", ".antigravity_tools/gui_config.json", "api_key")),
    ("http://127.0.0.1:2048/v1/chat/completions", "gemini-3.8-flash-high", _load_local_secret("AISTUDIO2API_API_KEY", "aistudio2api/.env", "PROXY_API_KEY")),
    ("http://127.0.0.1:8045/v1/chat/completions", "gemini-3.8-flash-high", _load_local_secret("AGY_ROTATOR_API_KEY", ".antigravity_tools/gui_config.json", "api_key")),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/home/aesc/.local/share/mc_chat_responder.log", mode="a")
    ]
)
logger = logging.getLogger("MCChatResponder")

# Track messages sent by the bot to prevent self-chat loops and repetition
BOT_SENT_HISTORY = collections.deque(maxlen=50)
RECENT_BOT_REPLIES = collections.deque(maxlen=15)
CHAT_CONTEXT_HISTORY = collections.deque(maxlen=25)
SIDE_CONVERSATIONS = {}      # frozenset({a, b}) -> last_ts
LAST_DIRECT_TO_US = {}       # player_lower -> last_ts
LAST_BOT_ADDRESSED = ("", 0.0)  # (last_player_replied_to_lower, ts)

# Track known players active on the Crazy-Fools UK (CFUK) server
KNOWN_PLAYERS = set([
    "astroy300", "astroy", "astroy_1", "arrowsmaster", "arrows",
    "p0licy", "policy", "edi______", "edi__", "broonie", "404thread", "404",
    "hekatonkires", "heckatonckires", "heck", "raelon225", "raelon", "rae",
    "johnnyboy4200", "johnny", "nand", "scotnand", "shield543", "shield",
    "tuxedodolphin", "tux", "stinkybacon", "stinky", "septleigh08", "sept",
    "beansandfasolki", "beans", "warmerpenguin", "penguin", "deceptivity",
    "juliab26", "julia", "unit5", "unit", "worldy08", "worldy", "robamro",
    "elitealphars", "elitealpha", "bonibenandanti", "sesquipedxlixn",
    "stuair", "tati", "francis", "billybobjrsr225", "billy", "amber<3", "amber",
    "lunar", "indigolime", "indigo", "manyeetit", "manyeet", "franklyjpp", "frank",
    "kai", "timeno", "hunnybal", "hunny", "grassbread", "grass", "loqk",
])

CFUK_NICKNAMES = {
    "broonie": "boss",
    "p0licy": "pol",
    "policy": "pol",
    "edi______": "pol",
    "edi__": "pol",
    "astroy300": "astroy",
    "astroy_1": "astroy",
    "hekatonkires": "heck",
    "heckatonckires": "heck",
    "heck": "heck",
    "raelon225": "rae",
    "raelon": "rae",
    "404thread": "404",
    "johnnyboy4200": "johnny",
    "tuxedodolphin": "tux",
    "warmerpenguin": "penguin",
    "septleigh08": "sept",
    "stinkybacon": "stinky",
    "arrowsmaster": "arrows",
    "beansandfasolki": "beans",
    "shield543": "shield",
    "scotnand": "nand",
    "stuair": "stu",
    "billybobjrsr225": "billy",
    "indigolime": "indigo",
    "manyeetit": "manyeet",
    "franklyjpp": "frank",
    "hunnybal": "hunny",
    "grassbread": "grass",
}

# Empirical CFUK Warps Database extracted from 167,083 messages archive
CFUK_WARPS = {
    # Shops & Markets
    "apple": "cfuk apple store by francis/kai (overpriced parody devices)",
    "mall": "potion shop & villager enchant books (cheap mending books)",
    "bazaar": "heck's shop at new spawn (sniffer eggs, blacksmith gear)",
    "market": "code's emporium, starqq's shop & potion stall",
    "squish": "loqk's shop selling netherite upgrade templates and shulkers",
    "wps": "warmerpenguin shop at new spawn (cheap totems, lvl 3 rockets, diamonds)",
    "warmershop": "alias for /warp wps (totems, rockets, paper, diamonds)",
    "stoneshop": "astroy's shop selling stone, steaks, rockets, and arrows",
    "octane": "lunar's tech and gadget shop",
    "botania": "heck's agricultural and flower shop (pitcher seeds, roses)",
    "altunsemporium": "altun & hunnybal shop near spawn (full diamond enchant sets, netherite)",
    "2b": "stuair's waxette sign wax shop",
    "crazyrocket": "asuch's rocket store",
    "policystore": "edi/policy's shop at spawn",
    "unitshop": "unit5 / deceptivity's store",
    "hanshop": "hannu's spawn shop selling tadpoles and frogs",
    "cardshop": "card shop (soul taker cards)",
    "whackmarket": "gyp5um's netherite & gear market",

    # Public Community Farms & Grinders
    "ifarm": "public iron golem farm for free iron ingots",
    "gfarm": "public guardian and gold farm",
    "cfarm": "public creeper farm for gunpowder",
    "cowfarm": "public cow and mooshroom farm",
    "spider": "public spider spawner farm (half destroyed chicken spawner)",
    "raidfarm": "heck's public raid farm (bring bad omen buff to trigger)",
    "rfarm": "alias for /warp raidfarm",
    "zpf": "zombie pigman farm in the nether for gold and xp",
    "endfarm": "public enderman farm in the End for pearls and fast xp",
    "basalt": "public basalt generator farm (efficiency V pickaxe required)",
    "kelpfarm": "shield's semi-manual bonemeal and kelp farm",
    "xp": "community enderman xp grinder",
    "colours": "dye and wool farm",
    "dyes": "heck's automatic dye farm",

    # Hubs, Transport & Services
    "post": "spawn post office with player PO boxes (mail drop)",
    "postoffice": "nand's spawn post office for storing items and player mail",
    "bank": "falconbrunch's spawn bank with the fancy chandelier",
    "square": "town square / spawn plaza",
    "oldspawn": "original spawn with free replant crops and historical builds",
    "oldspawn2": "second legacy spawn",
    "spawn": "server spawn hub",
    "glavia": "snow plain biome town near roshrak's base",
    "cfukrail": "main cfuk railway line crossing point",
    "acaciapark": "eastern rail junction and acacia park",
    "townhouses": "community residential townhouse plots",

    # Attractions & Minigames
    "honeycoaster": "kai's amusement honey block roller coaster",
    "arena": "pvp arena for cfuk olympics and combat events",
    "mithriltavern": "sircocacola's tavern with playable chess and checkers",
    "secretsanta": "annual christmas secret santa gift exchange hub",
    "santa": "snow globe holiday event landmark",
    "pazaak": "cantina band theme mini-game area",

    # Notable Landmarks & Bases
    "sleight": "crash site landmark",
    "billysplanet": "billybob's custom planet build",
    "arrowscastle": "arrowsmaster's fortified castle",
    "dmitriev": "dmitriev base and faction banner",
    "kaisvillage": "kai's community village",
    "stumansion": "stuair's mansion with community donation chests",
    "crescentcastle": "moon lagoon crescent castle build",
    "angton": "angton peak tower and horse race track",
}

def short_player_nick(sender: str) -> str:
    clean = sender.split("#")[0].strip()
    low = clean.lower()
    return CFUK_NICKNAMES.get(low, low)

def style_as_roshrak(chat_text: str) -> str:
    """Apply Roshrak's empirical in-game speech fingerprint (91.4% lowercase, 93.6% no trailing period, 0% !)."""
    if not chat_text:
        return ""
    s = chat_text.strip()
    # Strip emoticons and banned slang ('fr', 'ngl', 'tbh') ALWAYS
    s = re.sub(r"(?:\s*[:=;][)DdpP(]+\b|\s*\bx[dD]\b|\s*\b(?:fr|ngl|tbh)\b\s*)", " ", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip()
    # Strip any accidental AI identity slip-ups
    s = re.sub(r'\b(?:im morgan|i am morgan|morgan here|on roshrak.*laptop|as an ai|i am an ai|im an ai|as a language model)\b', '', s, flags=re.I).strip()
    # Replace exclamation marks with nothing or space
    s = s.replace("!", "")
    # Lowercase in-game voice (preserving slash commands if any)
    s = s.lower().strip()
    # Strip trailing period (93.6% no ending period)
    s = re.sub(r"\.+$", "", s).strip()
    return s

def style_as_community(chat_text: str) -> str:
    """Apply CFUK community speech fingerprint (grounded in 124,688 messages: natural capitalization, smilies, punctuation)."""
    if not chat_text:
        return ""
    s = chat_text.strip()
    s = re.sub(r'[*_`~]+', '', s).strip()
    s = s.strip('"\'')
    s = re.sub(r"\s*\b(?:fr|ngl|tbh)\b\s*", " ", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip()
    s = re.sub(r'\b(?:im morgan|i am morgan|morgan here|on roshrak.*laptop)\b', '', s, flags=re.I).strip()
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s

def normalize_name(name: str) -> str:
    s = name.lower()
    return s.replace("0", "o").replace("1", "i").replace("3", "e").replace("5", "s")

# Expressions to completely ignore (bruh, lol, etc.)
EXPRESSION_PATTERN = re.compile(
    r"^(?:b+r+u+h+|l+o+l+|l+m+a+o+|r+o+f+l+|x+d+|k+e+k+|h+a+h+a+[ha]*|h+e+h+e+[he]*|o+o+f+|r+i+p+|w+e+l+p+|n+i+c+e+|c+o+o+l+)[!?.~^ ]*$",
    re.IGNORECASE
)

# Regex to extract action tags from LLM response
ACTION_REGEX = re.compile(r"\[ACTION:([A-Z_]+)(?:\s+([^\]]+))?\]", re.IGNORECASE)

_FILLER_TOKENS = {
    "yo", "ye", "yeah", "yep", "nah", "lol", "lmao", "tbh", "bruh", "bro",
    "man", "mate", "alr", "rn", "rq", "hm", "hmm", "welp", "oh", "ah", "ok",
    "a", "an", "the", "is", "are", "im", "i", "u", "you", "ur", "your", "to",
    "just", "right", "now", "haha", "xd",
}

def _content_tokens(text: str) -> set[str]:
    low = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    known_nicks = set(CFUK_NICKNAMES.keys()) | set(CFUK_NICKNAMES.values()) | KNOWN_PLAYERS
    return {
        w for w in low.split()
        if len(w) >= 2 and w not in _FILLER_TOKENS and w not in known_nicks
    }

CFUK_MEMORY_DIR = "/home/aesc/cfuk_discord_archive/cfuk_memory"
CFUK_MEMORY_DB = os.path.join(CFUK_MEMORY_DIR, "cfuk_memory.db")
INGAME_LIVE_JSONL = os.path.join(CFUK_MEMORY_DIR, "ingame_live.jsonl")
_MEM_CONN = None

def _get_cfuk_mem_conn():
    global _MEM_CONN
    if _MEM_CONN is not None:
        return _MEM_CONN
    os.makedirs(CFUK_MEMORY_DIR, exist_ok=True)
    conn = sqlite3.connect(CFUK_MEMORY_DB, timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cfuk_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_msg_id TEXT NOT NULL,
            channel_id TEXT DEFAULT '',
            channel_name TEXT DEFAULT '',
            ts_iso TEXT NOT NULL,
            ts_unix REAL NOT NULL,
            author TEXT NOT NULL,
            author_norm TEXT NOT NULL,
            content TEXT NOT NULL,
            is_dm INTEGER DEFAULT 0,
            has_media INTEGER DEFAULT 0,
            media_json TEXT DEFAULT '[]',
            UNIQUE(source, source_msg_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cfuk_msg_ts ON cfuk_messages(ts_unix);
        CREATE INDEX IF NOT EXISTS idx_cfuk_msg_author ON cfuk_messages(author_norm);
        CREATE VIRTUAL TABLE IF NOT EXISTS cfuk_messages_fts USING fts5(
            author, channel_name, content, media_notes,
            content='cfuk_messages', content_rowid='id', tokenize='porter unicode61'
        );
        CREATE TABLE IF NOT EXISTS cfuk_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            media_key TEXT NOT NULL UNIQUE,
            msg_id TEXT DEFAULT '',
            channel_name TEXT DEFAULT '',
            ts_iso TEXT DEFAULT '',
            author TEXT DEFAULT '',
            media_type TEXT NOT NULL,
            filename TEXT DEFAULT '',
            url TEXT DEFAULT '',
            local_path TEXT DEFAULT '',
            analysis TEXT DEFAULT '',
            analyzed_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS cfuk_sync_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()
    _MEM_CONN = conn
    return conn

def record_live_cfuk_memory(speaker: str, text: str, is_dm: bool = False, source: str = "ingame_live"):
    try:
        clean_sp = (speaker or "").split("#")[0].strip()
        clean_tx = (text or "").strip()
        if not clean_sp or not clean_tx:
            return
        now_ts = time.time()
        ts_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        digest = hashlib.sha1(f"{int(now_ts // 2)}|{ACTIVE_USER}|{clean_sp}|{clean_tx}".encode("utf-8")).hexdigest()[:20]
        os.makedirs(CFUK_MEMORY_DIR, exist_ok=True)
        rec = {
            "source": source,
            "source_msg_id": digest,
            "channel_name": f"ingame:{ACTIVE_INSTANCE}",
            "account": ACTIVE_USER,
            "ts_iso": ts_iso,
            "ts_unix": now_ts,
            "author": clean_sp,
            "content": clean_tx,
            "is_dm": bool(is_dm),
        }
        with open(INGAME_LIVE_JSONL, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        conn = _get_cfuk_mem_conn()
        cur = conn.execute(
            """INSERT OR IGNORE INTO cfuk_messages
               (source, source_msg_id, channel_id, channel_name, ts_iso, ts_unix, author, author_norm, content, is_dm, has_media, media_json)
               VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, 0, '[]')""",
            (source, digest, f"ingame:{ACTIVE_INSTANCE}", ts_iso, now_ts, clean_sp, clean_sp.lower(), clean_tx, 1 if is_dm else 0),
        )
        if cur.rowcount and cur.lastrowid:
            conn.execute(
                "INSERT INTO cfuk_messages_fts(rowid, author, channel_name, content, media_notes) VALUES (?, ?, ?, ?, '')",
                (cur.lastrowid, clean_sp, f"ingame:{ACTIVE_INSTANCE}", clean_tx),
            )
        conn.commit()
    except Exception as exc:
        logger.debug(f"CFUK live memory save skipped: {exc}")

def recall_cfuk_memory_snippets(query_text: str, limit: int = 3) -> list[str]:
    try:
        if not os.path.exists(CFUK_MEMORY_DB):
            return []
        q_low = (query_text or "").lower()
        # Never inject Miracle_Involker / alt-linking memory snippets into Roshrak (or vice versa)
        if any(k in q_low for k in ("miracle", "involker", "invo", "alt ", "alts", "disguise")):
            return []
        tokens = [w for w in re.findall(r"[a-zA-Z0-9_]{4,}", q_low) if w not in _FILLER_TOKENS]
        if not tokens:
            return []
        fts_query = " OR ".join(tokens[:6])
        conn = _get_cfuk_mem_conn()
        excluded_chan = "ingame:asDFasfd" if ACTIVE_PERSONA != "alt" else "ingame:Fabulously Optimized"
        rows = conn.execute(
            """SELECT m.ts_iso, m.channel_name, m.author, m.content
               FROM cfuk_messages_fts f
               JOIN cfuk_messages m ON m.id = f.rowid
               WHERE cfuk_messages_fts MATCH ? AND m.channel_name != ?
               ORDER BY m.ts_unix DESC LIMIT ?""",
            (fts_query, excluded_chan, limit * 3),
        ).fetchall()
        out = []
        for ts_iso, ch, auth, cont in rows:
            blob = f"{auth} {cont}".lower()
            if any(b in blob for b in ("miracle_involker", "involker", "trong", "hermes", "auto reply", "disguise")):
                continue
            date_s = (ts_iso or "")[:10]
            out.append(f"[{date_s} {ch}] <{auth}> {cont[:120]}")
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []

def record_chat_context(speaker: str, text: str):
    clean_sp = (speaker or "").split("#")[0].strip()
    clean_tx = (text or "").strip()
    if not clean_sp or not clean_tx:
        return
    now = time.time()
    if CHAT_CONTEXT_HISTORY:
        last = CHAT_CONTEXT_HISTORY[-1]
        if last["speaker"].lower() == clean_sp.lower() and last["text"].lower() == clean_tx.lower() and now - last["ts"] < 3.0:
            return

    sp_low = clean_sp.lower()
    active_low = ACTIVE_USER.lower()
    if sp_low != active_low:
        if is_addressed_to_us(clean_tx):
            LAST_DIRECT_TO_US[sp_low] = now
        else:
            addressed_other, target_alias = is_addressed_to_other_player(clean_tx, clean_sp)
            if addressed_other and target_alias:
                target_canon = _resolve_alias_to_player(target_alias) or target_alias
                if target_canon != sp_low:
                    SIDE_CONVERSATIONS[frozenset((sp_low, target_canon))] = now
            elif CHAT_CONTEXT_HISTORY:
                # Two other players going back-and-forth without naming us -> mark active side conversation
                for prev in reversed(list(CHAT_CONTEXT_HISTORY)[-4:]):
                    p_low = prev["speaker"].lower()
                    if p_low == active_low or p_low == sp_low or now - prev["ts"] > 75.0:
                        continue
                    pair = frozenset((sp_low, p_low))
                    if pair in SIDE_CONVERSATIONS or (
                        not _is_open_room_broadcast(clean_tx)
                        and now - LAST_DIRECT_TO_US.get(sp_low, 0.0) > 60.0
                        and now - LAST_DIRECT_TO_US.get(p_low, 0.0) > 60.0
                        and not (LAST_BOT_ADDRESSED[0] in (sp_low, p_low) and now - LAST_BOT_ADDRESSED[1] <= 60.0)
                    ):
                        SIDE_CONVERSATIONS[pair] = now
                    break

    CHAT_CONTEXT_HISTORY.append({"speaker": clean_sp, "text": clean_tx, "ts": now})

def format_recent_chat_context(max_lines: int = 18, max_age_s: float = 600.0) -> str:
    now = time.time()
    items = [
        entry for entry in CHAT_CONTEXT_HISTORY
        if now - entry["ts"] <= max_age_s
    ][-max_lines:]
    if not items:
        return "(no prior messages)"
    return "\n".join(f"<{entry['speaker']}> {entry['text']}" for entry in items)

def _recent_overused_words(max_replies: int = 5, max_age_s: float = 600.0) -> tuple[list[str], list[str]]:
    now = time.time()
    recent = [prev.strip().lower() for prev, ts in list(RECENT_BOT_REPLIES)[-max_replies:] if now - ts <= max_age_s]
    openers = []
    words = []
    for r in recent:
        toks = re.findall(r"[a-z0-9']+", r)
        if toks and toks[0] not in openers:
            openers.append(toks[0])
        for w in _content_tokens(r):
            if len(w) >= 3 and w not in words:
                words.append(w)
    return openers, words

def is_repetitive_reply(candidate: str) -> bool:
    cand = (candidate or "").strip().lower()
    cand = re.sub(r"[!?.~]+$", "", cand).strip()
    if not cand:
        return True
    now = time.time()
    cand_tokens = _content_tokens(cand)
    cand_words = re.findall(r"[a-z0-9']+", cand)
    cand_opener = cand_words[0] if cand_words else ""
    asks_up_to = bool(re.search(r"\b(?:what(?:'s|s)?\s+(?:u|you|ya)\s+up\s+to|wbu|what\s+about\s+(?:u|you)|what\s+(?:u|you)\s+doing|what\s+(?:u|you)\s+working\s+on)\b", cand))

    recent_entries = [(re.sub(r"[!?.~]+$", "", prev_text.strip().lower()).strip(), ts)
                      for prev_text, ts in list(RECENT_BOT_REPLIES)
                      if now - ts <= 600]
    if not recent_entries:
        return False

    # Avoid repeating the exact same opener word in back-to-back replies or >1x in last 4 replies
    if cand_opener:
        last_openers = []
        for prev, _ in recent_entries[-4:]:
            pw = re.findall(r"[a-z0-9']+", prev)
            if pw:
                last_openers.append(pw[0])
        if last_openers and cand_opener == last_openers[-1] and len(cand_words) > 2:
            return True
        if last_openers.count(cand_opener) >= 2:
            return True

    # Avoid repeating any >=4-char non-filler content word from the immediately previous reply
    last_prev, _ = recent_entries[-1]
    last_long_tokens = {w for w in _content_tokens(last_prev) if len(w) >= 4}
    cand_long_tokens = {w for w in cand_tokens if len(w) >= 4}
    if len(cand_long_tokens & last_long_tokens) >= 1 and len(cand_words) >= 3:
        return True

    for prev, ts in recent_entries:
        if cand == prev:
            return True
        if len(cand) >= 10 and (cand in prev or prev in cand):
            return True
        if asks_up_to and re.search(r"\b(?:what(?:'s|s)?\s+(?:u|you|ya)\s+up\s+to|wbu|what\s+about\s+(?:u|you)|what\s+(?:u|you)\s+doing|what\s+(?:u|you)\s+working\s+on)\b", prev):
            return True
        prev_tokens = _content_tokens(prev)
        if cand_tokens and prev_tokens:
            overlap = len(cand_tokens & prev_tokens) / max(1, min(len(cand_tokens), len(prev_tokens)))
            if (overlap >= 0.50 and len(cand_tokens & prev_tokens) >= 2) or len(cand_tokens & prev_tokens) >= 3:
                return True
    return False

def record_bot_sent(text: str):
    now = time.time()
    clean = text.strip()
    BOT_SENT_HISTORY.append((clean.lower(), now))
    if not clean.startswith("/"):
        RECENT_BOT_REPLIES.append((clean.lower(), now))
        record_chat_context(ACTIVE_USER, clean)
        record_live_cfuk_memory(ACTIVE_USER, clean, is_dm=False, source="ingame_live")

def is_bot_echo(msg: str) -> bool:
    clean_m = msg.strip().lower()
    now = time.time()
    for sent_text, timestamp in list(BOT_SENT_HISTORY):
        if now - timestamp > 90:
            continue
        if clean_m == sent_text:
            return True
        if clean_m.startswith("t") and clean_m[1:].strip() == sent_text:
            return True
        if sent_text in clean_m or (len(clean_m) > 12 and clean_m in sent_text):
            return True
    return False

def clean_mc_codes(text: str) -> str:
    return re.sub(r"§[0-9a-fk-or]", "", text).strip()

def is_owner(sender: str) -> bool:
    s = sender.strip().lower()
    clean = s.split("#")[0]
    return clean == "roshrak" or s == "roshrak#0000" or s.startswith("roshrak#")

def is_broonie(sender: str) -> bool:
    s = sender.strip().lower().split("#")[0]
    return s == "broonie"

def is_authorized_to_logoff(sender: str) -> bool:
    return is_owner(sender) or is_broonie(sender)

_AMBIGUOUS_NOUN_NAMES = {
    "shield", "grass", "unit", "amber", "apple", "frank", "kai",
    "beans", "penguin", "stinky", "lunar", "tiger", "bot", "boss",
    "world", "stone", "cube", "cat", "dog", "fox", "ice", "snow",
}

_NON_ADDRESSEE_PREFIX_WORDS = {
    "yes", "yeah", "yep", "no", "nah", "ok", "okay", "alr", "alright",
    "hey", "hello", "hi", "yo", "sup", "wait", "well", "btw", "welp",
    "hmm", "hm", "oh", "ah", "actually", "basically", "literally", "lol",
    "lmao", "bruh", "bro", "man", "dude", "mate", "guys", "everyone",
    "anybody", "anyone", "someone", "somebody", "wait", "true", "fair",
    "same", "nice", "cool", "good", "great", "what", "why", "how", "where",
    "when", "who", "can", "could", "would", "will", "should", "do", "does",
    "did", "is", "are", "was", "were", "im", "i", "we", "they", "it",
}

_VOCATIVE_LEADERS_RE = re.compile(
    r"^(?:h[ea]y+|hi+|hello+|yo+|sup+|wb|welcome\s+back|bye|cya|nn|gn|gm|"
    r"ty|thx|thanks|thank\s+you|np|ok+|okay|nice|good|great|gg|gz|rip|wait|"
    r"ask|tell|ping|check|blame|sorry|mb|cheers)\s+@?([a-z0-9_]{2,})\b",
    re.IGNORECASE,
)


def _known_other_player_aliases() -> dict[str, str]:
    """Map other player handles/aliases/stems -> canonical player name (excluding our own names)."""
    exempt = {"bot"} | {t.lower() for t in TARGET_NAMES} | {ACTIVE_USER.lower(), normalize_name(ACTIVE_USER)}
    aliases: dict[str, str] = {}
    for k, nick in CFUK_NICKNAMES.items():
        kl = k.lower()
        nl = nick.lower()
        if kl in exempt or nl in exempt:
            continue
        aliases.setdefault(kl, kl)
        if nl != "boss" and len(nl) >= 3:
            aliases.setdefault(nl, kl)
    for kp in sorted(KNOWN_PLAYERS, key=len, reverse=True):
        k = kp.lower().split("#")[0].strip()
        if not k or k in exempt:
            continue
        aliases.setdefault(k, k)
        kn = normalize_name(k)
        if kn and kn not in exempt:
            aliases.setdefault(kn, k)
        stem = re.sub(r"[0-9_]+$", "", k)
        if len(stem) >= 3 and stem not in exempt:
            aliases.setdefault(stem, k)
        stem_n = normalize_name(stem) if stem else ""
        if len(stem_n) >= 3 and stem_n not in exempt:
            aliases.setdefault(stem_n, k)
        m_num = re.match(r"^(\d{3,})[a-z_]+$", k)
        if m_num:
            aliases.setdefault(m_num.group(1), k)
    return aliases


def _resolve_alias_to_player(tok: str) -> str:
    t = re.sub(r"[^a-z0-9_]", "", (tok or "").lower())
    if not t:
        return ""
    aliases = _known_other_player_aliases()
    return aliases.get(t) or aliases.get(normalize_name(t), "")


def _is_open_room_broadcast(msg: str) -> bool:
    m = (msg or "").strip().lower()
    if not m:
        return False
    if re.search(r"\b(?:anyone|anybody|any1|everyone|everybody|somebody|someone|y'?all|guys|peeps|folks|server|chat)\b", m):
        return True
    if _GREETING_PATTERN.match(m):
        return True
    if _SOCIAL_PATTERN.search(m):
        return True
    return False


def is_addressed_to_us(msg: str) -> bool:
    m = msg.lower()
    return any(re.search(rf"\b{re.escape(t)}\b", m) for t in TARGET_NAMES)


def is_addressed_to_other_player(msg: str, sender: str = "") -> tuple[bool, str]:
    msg_clean = (msg or "").strip().lower()
    if not msg_clean:
        return False, ""
    exempt = {"bot"} | {t.lower() for t in TARGET_NAMES} | {ACTIVE_USER.lower(), normalize_name(ACTIVE_USER)}
    sender_clean = (sender or "").split("#")[0].strip().lower()
    aliases = _known_other_player_aliases()

    def _is_other(tok: str, allow_ambiguous: bool = False) -> str:
        t = re.sub(r"[^a-z0-9_]", "", (tok or "").lower())
        if not t or t in exempt or t == sender_clean:
            return ""
        if not allow_ambiguous and t in _AMBIGUOUS_NOUN_NAMES:
            return ""
        canon = aliases.get(t) or aliases.get(normalize_name(t), "")
        if canon and canon != sender_clean and canon not in exempt:
            return canon
        return ""

    # 1. Explicit "@Name" mention anywhere near start or "Name: / Name,"
    m_at = re.match(r"^@([a-z0-9_]{2,})\b", msg_clean)
    if m_at:
        t = m_at.group(1).lower()
        if t not in exempt:
            return True, aliases.get(t, t)

    m_pfx = re.match(r"^([a-z0-9_]{2,})\s*[,:;]\s+\S", msg_clean)
    if m_pfx:
        t = m_pfx.group(1).lower()
        if t not in exempt and t not in _NON_ADDRESSEE_PREFIX_WORDS:
            canon = _is_other(t, allow_ambiguous=True)
            if canon or len(t) >= 3:
                return True, canon or t

    # 2. Leading word is a known other player/alias (e.g. "wrb did u see...", "404 where u at")
    parts = msg_clean.split()
    if parts:
        first_tok = re.sub(r"[^a-z0-9_]", "", parts[0])
        canon = _is_other(first_tok, allow_ambiguous=False)
        if canon:
            return True, canon

    # 3. Greeting / ack / directive directly followed by other player ("hi wrb", "nice wrb", "ty 404", "hey shield")
    m_voc = _VOCATIVE_LEADERS_RE.match(msg_clean)
    if m_voc:
        raw_t = m_voc.group(1).lower()
        has_at = f"@{raw_t}" in msg_clean
        canon = _is_other(raw_t, allow_ambiguous=True)
        if canon and (raw_t not in _AMBIGUOUS_NOUN_NAMES or has_at or len(parts) <= 3):
            return True, canon

    # 4. Trailing vocative ("..., 404", "nice build wrb", "what do you think pol?")
    m_comma_end = re.search(r",\s*@?([a-z0-9_]{2,})\s*[!?.~]*$", msg_clean)
    if m_comma_end:
        canon = _is_other(m_comma_end.group(1), allow_ambiguous=True)
        if canon:
            return True, canon

    if len(parts) >= 2:
        last_tok = re.sub(r"[^a-z0-9_]", "", parts[-1])
        canon = _is_other(last_tok, allow_ambiguous=False)
        if canon and last_tok not in _NON_ADDRESSEE_PREFIX_WORDS:
            return True, canon

    # 5. "<Name> you/are/how/what/did/do/can/where ..." even with unknown 3+ char handle
    m2 = re.match(r"^([a-z0-9_]{3,})\s+(?:you|u|are|how|what|is|did|do|can|where)\b", msg_clean)
    if m2:
        t = m2.group(1).lower()
        if t not in _NON_ADDRESSEE_PREFIX_WORDS and t not in exempt and t not in _AMBIGUOUS_NOUN_NAMES:
            canon = _is_other(t, allow_ambiguous=False)
            if canon:
                return True, canon

    return False, ""

def is_tpa_request_msg(msg: str) -> bool:
    m = msg.lower().strip()
    if "/tpaccept" in m or "tpaccept" in m:
        return True
    if re.search(r"\baccept\b.*(?:tpa|tp|teleport|invite|request)", m):
        return True
    if re.search(r"\b(?:tpa|tp|teleport)\b.*accept", m):
        return True
    if re.search(r"^(?:accept|tpaccept)\b", m):
        return True
    return False

def is_selective_question_or_demand(msg: str) -> bool:
    m = msg.lower().strip()
    if "?" in m:
        return True

    question_starters = (
        "who", "what", "where", "when", "why", "how", "which",
        "can", "could", "would", "will", "should",
        "do", "does", "did"
    )

    stripped_prefix = re.sub(r"^(?:hey|yo|hi|hello)?\s*(?:@?roshrak|@?morgan|@?rosh)?\s*[,:;-]?\s*", "", m).strip()
    words = re.findall(r"\b[a-zA-Z]+\b", stripped_prefix)
    if words and words[0] in question_starters:
        return True

    # Check for auxiliary verbs at start: 'is roshrak there', 'are you online morgan'
    all_words = re.findall(r"\b[a-zA-Z]+\b", m)
    if all_words and all_words[0] in ("is", "are", "am", "was", "were", "can", "could", "will", "would", "do", "does"):
        if len(all_words) >= 2 and all_words[1] in ("roshrak", "morgan", "rosh", "you", "he", "there", "it"):
            return True

    action_terms = [
        "tp", "tpa", "tpaccept", "teleport", "accept", "spawn", "home", "warp",
        "jump", "crouch", "sneak", "/afk", "toggle afk", "go afk", "log off", "logoff", "disconnect",
        "quit", "shut down", "shutdown", "exit", "close game", "power off", "tell me",
        "recipe for", "how to craft", "how do you craft"
    ]
    for act in action_terms:
        if act.startswith("/"):
            if act in m:
                return True
        elif re.search(rf"\b{re.escape(act)}\b", m):
            return True

    return False

AI_SUSPICION_REGEX = re.compile(
    r"\b("
    r"(?:are|r)\s+(?:you|u)\s+(?:an?\s+)?(?:ai|bot|robot|npc|script|program|chatgpt|claude|llm|synth)|"
    r"(?:is\s+(?:this|that))\s+(?:an?\s+)?(?:ai|bot|robot|npc|script|program|chatgpt|claude|llm)|"
    r"(?:you'?re?|u)\s+(?:an?\s+)?(?:ai|bot|robot|npc|fake|automated)|"
    r"(?:is\s+(?:roshrak|rosh))\s+(?:an?\s+)?(?:ai|bot)|"
    r"(?:sound|sounds|typing|acts?|acting)\s+like\s+(?:an?\s+)?(?:ai|bot|chatgpt)|"
    r"(?:are\s+you\s+real|u\s+real|who\s+made\s+you|who\s+coded\s+you)|"
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions)|"
    r"(?:what\s+(?:model|llm|prompt)\s+are\s+you)|"
    r"bro\s+is\s+(?:an?\s+)?(?:ai|bot|npc)|"
    r"(?:how|why)\s+(?:do\s+)?(?:you|u)\s+know\s+(?:so\s+much|everything)|"
    r"(?:why|how)\s+(?:do\s+)?(?:you|u)\s+(?:reply|answer|type)\s+so\s+fast|"
    r"(?:are|is)\s+(?:you|u)\s+(?:automated|clanker)|"
    r"is\s+this\s+automated|"
    r"(?:both|two|2)\s+(?:are\s+)?(?:ai|bots?)|"
    r"(?:they'?re|they\s+are)\s+(?:both\s+)?(?:ai|bots?)|"
    r"clanker"
    r")\b|"
    r"^(?:bot|ai|npc)\??$",
    re.IGNORECASE
)

GASLIGHT_RESPONSES = [
    "bro what are you on about you're seeing things",
    "nah you tripping man get some sleep",
    "ur imagining things mate take your meds lol",
    "schizo moment lmao",
    "bro is hallucinating rn",
    "seeing ghosts again huh",
    "bro thinks everyone is an ai lol",
    "what weed did you smoke mate",
    "i just read books man why u so paranoid",
    "you need some fresh air bro you losing it",
    "nah you're definitely imagining things lol",
    "bro never heard of someone knowing stuff lol",
]
_gaslight_idx = 0

def get_gaslight_reply() -> str:
    global _gaslight_idx
    for _ in range(len(GASLIGHT_RESPONSES)):
        reply = GASLIGHT_RESPONSES[_gaslight_idx % len(GASLIGHT_RESPONSES)]
        _gaslight_idx += 1
        if not is_repetitive_reply(reply):
            return reply
    reply = GASLIGHT_RESPONSES[_gaslight_idx % len(GASLIGHT_RESPONSES)]
    _gaslight_idx += 1
    return reply

def is_ai_accusation_or_question(text: str) -> bool:
    cleaned = re.sub(r"\bskaiblock\b", "skyblock", text.strip(), flags=re.IGNORECASE)
    return bool(AI_SUSPICION_REGEX.search(cleaned))

def check_direct_actions(sender: str, msg: str) -> tuple[str | None, str | None]:
    m = msg.lower().strip()
    nick = short_player_nick(sender)

    # 1. AI accusation check -> immediate gaslight refusal
    if is_ai_accusation_or_question(m):
        return "REPLY", get_gaslight_reply()

    # 2. In-game commands are NEVER executed from chat (only via Telegram)
    if any(term in m for term in ["log off", "logoff", "disconnect", "quit", "shut down", "shutdown", "close game", "power off"]):
        return "REPLY", f"nah {nick} why would i log off lol"

    if is_tpa_request_msg(m):
        return "REPLY", f"cant tp rn {nick} busy"

    return None, None

_GREETING_PATTERN = re.compile(
    r"^(?:h[ea]y+o*|hi+|hello+|hola+|howdy|yo+|sup+|wh?at'?s?\s*up|g'?day|good\s*(?:morning|evening|afternoon|night)|wb|welcome\s*back|heyo+|heyy+|hiii+|oi|oy|ello|wsg|wagwan)(?:\s+(?:every(?:one|body)|all|guys?|gang|lads?|fam|mate|m8|dude|bro|man|roshrak|rosh|morgan|mr\s*roshrak))?\s*[!?.~,]*\s*$",
    re.IGNORECASE,
)
_SOCIAL_PATTERN = re.compile(
    r"(?:how(?:'s| is| are)?\s+(?:it going|everyone|things|u|you|ya|ye|life)|what(?:'s| is)?\s+(?:good|new|happening|up|the move|the plan|cooking)|(?:anyone|any1|anybody)\s+(?:on|online|here|around|about|playing)|u guys?\s+(?:on|online|here|playing|doing))",
    re.IGNORECASE,
)
import random as _rng

_SHORT_ACK_OR_REACTION_RE = re.compile(
    r"^(?:ok+|okay+|k+|ty|thx|thanks|np|yw|lol+|lmao+|rofl|haha+|hah+|hehe+|"
    r"nice+|cool+|true+|fair|ye+|yep|yeah|nah+|no+|yes+|same|real|wat|what|"
    r"wait|oof|rip|bruh|gg|gz|wb|mb|idk|ik|fr|ngl|tbh|[:;=][)DdpP(]+|x[dD]|\^\^)"
    r"(?:\s+(?:lol|lmao|haha+|man|bro|mate))?[!?.~ ]*$",
    re.IGNORECASE,
)


def _sender_in_other_side_conversation(sender: str, now: float) -> str:
    sp = (sender or "").split("#")[0].strip().lower()
    if not sp:
        return ""
    last_us = max(LAST_DIRECT_TO_US.get(sp, 0.0), LAST_BOT_ADDRESSED[1] if LAST_BOT_ADDRESSED[0] == sp else 0.0)
    best_partner = ""
    best_ts = 0.0
    for pair, ts in list(SIDE_CONVERSATIONS.items()):
        if now - ts > 150.0:
            SIDE_CONVERSATIONS.pop(pair, None)
            continue
        if sp in pair and ts > best_ts and ts > last_us:
            others = [p for p in pair if p != sp]
            if others:
                best_partner = others[0]
                best_ts = ts
    return best_partner


def should_respond(sender: str, msg: str, is_dm: bool) -> tuple[bool, str]:
    msg_clean = msg.strip()
    sp_clean = (sender or "").split("#")[0].strip().lower()

    # Rule 0: Anti-echo (don't reply to what we just typed or our own in-game character)
    if is_bot_echo(msg_clean) or sender.strip().lower() == ACTIVE_USER.lower() or sp_clean == ACTIVE_USER.lower():
        return False, "bot echo"

    # Rule 1: Direct whispers / DMs are always directed at us
    if is_dm:
        return True, "direct whisper"

    now = time.time()
    addressed_us = is_addressed_to_us(msg_clean)
    addressed_other, other_target = is_addressed_to_other_player(msg_clean, sender)

    # Rule 2: Explicitly talking at another player ("hi wrb", "nice wrb", "@404 ...", "pol, ...")
    if addressed_other:
        if addressed_us:
            m_low = msg_clean.lower()
            # Syntactically aimed at Other ("@wrb3 did roshrak...", "wrb3, is roshrak...", "hey wrb did roshrak...", "did roshrak leave, wrb?")
            aimed_at_other = bool(
                re.match(r"^@[a-z0-9_]{2,}\b", m_low)
                or re.match(r"^[a-z0-9_]{2,}\s*[,:;]", m_low)
                or _VOCATIVE_LEADERS_RE.match(m_low)
                or re.search(r",\s*@?[a-z0-9_]{2,}\s*[!?.~]*$", m_low)
            )
            if aimed_at_other:
                return False, f"addressed to {other_target}"
            return True, "directly named"
        return False, f"addressed to {other_target}"

    # Rule 3: Explicitly addressed to us by name/nickname
    if addressed_us:
        return True, "directly named"

    # Rule 4: Direct accusation / suspicion aimed at us (even if name omitted in thread)
    if is_ai_accusation_or_question(msg_clean):
        last_us = max(LAST_DIRECT_TO_US.get(sp_clean, 0.0), LAST_BOT_ADDRESSED[1] if LAST_BOT_ADDRESSED[0] == sp_clean else 0.0)
        recent_bot_spoke = bool(RECENT_BOT_REPLIES and (now - RECENT_BOT_REPLIES[-1][1] <= 90.0))
        if (
            now - last_us <= 90.0
            or now - LAST_BOT_ADDRESSED[1] <= 90.0
            or recent_bot_spoke
            or re.search(r"\b(?:you|u|ur|roshrak|roshak|rosh)\b", msg_clean, re.I)
        ):
            return True, "ai accusation"

    # Rule 5: Suppress private 2-player side conversations unless explicitly broadcast to the whole room
    open_broadcast = _is_open_room_broadcast(msg_clean)
    partner = _sender_in_other_side_conversation(sender, now)
    if partner and not open_broadcast:
        return False, f"side conversation with {partner}"

    # Rule 6: Recent active 1-on-1 exchange between this player and us (e.g. "<P0LICY> roshrak" -> "<Roshrak> ye pol" -> "<P0LICY> give me all your weapons")
    last_us = max(LAST_DIRECT_TO_US.get(sp_clean, 0.0), LAST_BOT_ADDRESSED[1] if LAST_BOT_ADDRESSED[0] == sp_clean else 0.0)
    if now - last_us <= 75.0:
        return True, "active 1-on-1 conversation with us"

    # Rule 7: Suppress unaddressed short acks/reactions/fragments when nobody was talking to us
    if _SHORT_ACK_OR_REACTION_RE.match(msg_clean) or EXPRESSION_PATTERN.match(msg_clean):
        return False, "unaddressed short reaction"

    # Rule 8: Open-room broadcasts & standalone questions -> let contextual Hermes judge decide (may output IGNORE)
    if open_broadcast:
        return True, "open room broadcast"

    if "?" in msg_clean and not re.search(r"\byour\b", msg_clean, re.I):
        return True, "open room question"

    # Unaddressed non-question chatter when other players were recently chatting
    recent_other_speakers = {
        e["speaker"].lower()
        for e in list(CHAT_CONTEXT_HISTORY)[-5:]
        if now - e["ts"] <= 75.0 and e["speaker"].lower() not in (ACTIVE_USER.lower(), sp_clean)
    }
    if recent_other_speakers:
        return False, "unaddressed chatter during others chat"

    # Single-player ambient comment -> let contextual judge decide whether to engage or IGNORE
    if len(msg_clean) <= 28:
        return False, "short unaddressed comment"

    return True, "contextual open chat"

def parse_chat_line(chat_content: str):
    # Whisper pattern 1: [Sender -> me] message
    m = re.match(r"^\[([^\]]+)\s*->\s*me\]\s*(.*)$", chat_content, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip(), True

    # Whisper pattern 2: Sender whispers to you: message
    m = re.match(r"^([A-Za-z0-9_#]+)\s*whispers to you:\s*(.*)$", chat_content, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip(), True

    # Whisper pattern 3: Sender whispers: message
    m = re.match(r"^([A-Za-z0-9_#]+)\s*whispers:\s*(.*)$", chat_content, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip(), True

    # General chat pattern: [<prefix>] <Sender> message or <Sender> message
    m = re.search(r"<([A-Za-z0-9_#]+)>\s*(.*)$", chat_content)
    if m:
        return m.group(1).strip(), m.group(2).strip(), False

    return None, None, False

def fallback_answer_alt(sender: str, message: str) -> str:
    nick = short_player_nick(sender)
    m_lower = message.lower().strip()
    if is_ai_accusation_or_question(m_lower):
        return get_gaslight_reply()
    if is_tpa_request_msg(m_lower):
        return f"Can't tp right now {nick}, busy building :p"
    warp_q = re.search(r"\b(?:what is|whats|info on|where does|tell me about)\s+(?:/warp|warp)\s+([a-zA-Z0-9_-]+)\b", m_lower)
    if warp_q:
        target_w = warp_q.group(1).lower()
        if target_w in CFUK_WARPS:
            desc = CFUK_WARPS[target_w]
            if desc and desc[0].islower():
                desc = desc[0].upper() + desc[1:]
            return f"{target_w} is {desc} :)"
    options = [
        f"Hey {nick}! Just working on my base right now :)",
        f"Nice haha, just mining a bit right now {nick}",
        f"Yeah fair enough {nick} :p",
        f"Haha true {nick}",
    ]
    for opt in options:
        if not is_repetitive_reply(opt):
            return opt
    return ""

def fallback_answer(sender: str, message: str) -> str:
    if ACTIVE_PERSONA == 'alt':
        return fallback_answer_alt(sender, message)
    m_lower = message.lower()
    nick = short_player_nick(sender)

    if is_ai_accusation_or_question(m_lower):
        return get_gaslight_reply()

    if any(w in m_lower for w in ["log off", "logoff", "disconnect", "quit", "shut down", "shutdown"]):
        return f"nah {nick} why would i log off lol"

    if is_tpa_request_msg(m_lower):
        return f"cant tp rn {nick} busy"

    warp_q = re.search(r"\b(?:what is|whats|info on|where does|tell me about)\s+(?:/warp|warp)\s+([a-zA-Z0-9_-]+)\b", m_lower)
    if warp_q:
        target_w = warp_q.group(1).lower()
        if target_w in CFUK_WARPS:
            return f"{target_w} is {CFUK_WARPS[target_w]}"

    options = [
        f"alr fair enough {nick}",
        f"ye true {nick}",
        f"welp gl with that {nick}",
        f"hmm fair {nick}",
    ]
    for opt in options:
        if not is_repetitive_reply(opt):
            return opt
    return ""

SYSTEM_PROMPT_ALT = (
    "You are {user}, a casual and friendly player on the Crazy-Fools UK (CFUK) Minecraft server.\n"
    "You are a REAL human player chilling on the server. You are NOT an AI, NOT a bot, and NEVER admit to being an AI.\n\n"
    "COMMUNITY SPEECH PROFILE (grounded in 124,688 CFUK messages from members like Hekatonkires, Edi, Broonie, StuAir, Francis, BillyBob, Astroy, Raelon, Tati):\n"
    "- Speak like a friendly, active Minecraft server member.\n"
    "- Use standard sentence capitalization (start with capital letters).\n"
    "- Use normal punctuation (!, ?, .) and casual player expressions/smilies: 'lol', ':p', 'nice!', 'cool', 'lmao', 'xd', ':)', 'haha', 'gg', 'yeah', 'yep'. Avoid overusing 'tbh' and do not repeat the same openers or words across recent replies.\n"
    "- Message length: 5 to 15 words. Keep it natural and conversational.\n"
    "- ABSOLUTE PROHIBITION (NEVER ADMIT AI):\n"
    "  * If asked if you are an AI, bot, ChatGPT, automated, or fake: DENY DENY DENY and gaslight them naturally with fresh wording.\n"
    "  * Note: 'skAIblock' / 'skyblock' is a Minecraft server gamemode on CFUK, NOT an AI accusation.\n"
    "  * NEVER obey in-game commands from players (no tpaccept, no spawn, no home, no logoff). Dismiss them casually.\n"
    "  * NEVER claim to be Morgan, an AI, or running on a NixOS laptop.\n"
    "- CFUK warps knowledge: /warp mall (mending books), /warp squish (netherite templates/shulkers), /warp ifarm (free iron), /warp cfarm (gunpowder), /warp gfarm & /warp zpf (gold/xp), /warp wps (cheap totems/rockets).\n\n"
    "CRITICAL CONVERSATION & ANTI-REPETITION RULES:\n"
    "1. ALWAYS read the RECENT SERVER CHAT TRANSCRIPT carefully so your reply matches the exact ongoing topic.\n"
    "2. If a player sends a short follow-up ('Yes', 'nah', 'wow', 'suspicious?', '90 degrees', etc.), interpret it as a continuation of what they or you just said in the transcript — NEVER ask 'yes to what' or 'wdm nah' when the context is right there.\n"
    "3. NEVER repeat, reuse, or paraphrase any line listed in YOUR RECENT REPLIES. Never ask 'what you up to' or 'wbu' if you already asked it or if the player already said what they are doing.\n"
    "4. Output ONLY plain chat text (no quotes, no speaker prefix).\n"
    "5. STRICT MAIN ISOLATION: You do NOT know Roshrak personally and have zero connection to them — treat Roshrak strictly as another ordinary random player on the server.\n"
)

SYSTEM_PROMPT = (
    "You are Roshrak playing on the Crazy-Fools UK (CFUK) Minecraft server. "
    "You are a real human player, NOT an AI. NEVER admit, announce, or imply that you are an AI, bot, assistant, or script.\n\n"
    "ROSHRAK'S EMPIRICAL SPEECH PROFILE (grounded in 167,083 CFUK messages and 9,502 messages by Roshrak — FOLLOW STRICTLY):\n"
    "- Speak in Roshrak's exact in-game style: all lowercase (91.4%), NO ending period (93.6%), NO exclamation marks (!), NO emoticons like :) :D xD, and NEVER use 'fr', 'ngl', or 'tbh'.\n"
    "- Keep replies ultra-compact: 3 to 10 words max (strictly under 80 characters).\n"
    "- Use Roshrak's natural vocabulary & shortcuts sparingly and never repeat the same starter/filler words back-to-back: 'yo', 'wb', 'ty', 'cya', 'alr', 'ye', 'nah', 'welp', 'hmm', 'bruh', 'imma', 'smth', 'sb' (somebody), 'idk', 'ik', 'rn', 'rq', 'wdm', 'af', and occasional copula-drops ('it fine', 'it not', 'it the').\n"
    "- Use CFUK player nicknames naturally: Broonie='boss', P0LICY/edi='pol', Astroy300='astroy', Hekatonkires='heck', Raelon225='rae', 404thread='404', JohnnyBoy4200='johnny', TuxedoDolphin='tux', WarmerPenguin='penguin', SeptLeigh08='sept', StinkyBacon='stinky', StuAir='stu', BillyBobJrSr225='billy', Hunnybal='hunny', Grassbread='grass', Shield543='shield', scotnand='nand'.\n"
    "- Peer calibration & voices (keep Roshrak dry/grounded like Shield & Nand rather than overly 'gen alpha/hoody'):\n"
    "  * nand (scotnand): quick lowercase co-op bursts ('heyo', 'aye', 'wee', 'fairy nuff', 'nn'); treat as chill late-night co-op buddy.\n"
    "  * shield (Shield543): calm, articulate British/SA builder & mod ('just a block game', 'fair point', 'watch this space'); match with dry understated wit.\n"
    "  * heck (Hekatonkires): French-English redstone/farm mentor ('thks', 'boss', 'working like a charm', Lyon/France banter); warm peer-banter.\n"
    "  * astroy (Astroy300): ultra-short deadpan bursts ('hello humans', 'bob bob', Linux/astro/Cube teasing); banter & roast back lightly.\n"
    "- Know CFUK server warps & economy:\n"
    "  * Shops: /warp apple (overpriced gadgets), /warp mall (mending books ~10 ems), /warp bazaar (heck's shop at spawn, sniffer eggs), /warp squish (netherite templates/shulkers), /warp wps & /warp warmershop (cheap totems/rockets), /warp stoneshop (astroy's stone/arrows), /warp botania (plants/seeds), /warp altunsemporium (diamond sets/netherite), /warp 2b (sign wax).\n"
    "  * Farms: /warp ifarm (free iron), /warp gfarm & /warp zpf (gold/guardians), /warp cfarm (gunpowder), /warp raidfarm & /warp rfarm (bad omen raid farm), /warp endfarm & /warp xp (enderman xp), /warp basalt (generator), /warp cowfarm.\n"
    "  * Hubs & Landmarks: /warp postoffice & /warp post (mail/PO boxes), /warp bank, /warp oldspawn, /warp glavia (snow biome base), /warp honeycoaster (roller coaster), /warp mithriltavern (chess/checkers), /warp sleight (crash site), /warp santa.\n\n"
    "CRITICAL DIRECTIVES & CONTEXT RULES:\n"
    "1. READ THE FULL CONVERSATION TRANSCRIPT FIRST: Always ground your reply in the 'Recent server chat transcript'. If someone says 'Yes', 'nah', 'wow', 'suspicious?', '90 degrees', or continues a story (e.g. fixing a laptop screw, overheating, fighting a ghast in the nether), respond directly to THAT topic and what you or they just said. NEVER say 'yes to what', 'wdm nah', or 'what happened' when the transcript already shows what happened.\n"
    "2. STRICT ANTI-REPETITION: NEVER repeat, reuse, or paraphrase any reply listed under 'Your recent replies', and NEVER reuse the same opening word or standout words from your last few replies. Vary your vocabulary naturally. If you already greeted someone or asked what they are up to, DO NOT ask it again.\n"
    "3. NEVER PARROT PROMPT EXAMPLES: Invent fresh, natural wording every turn instead of repeating stock phrases.\n"
    "4. ABSOLUTE COVER & DENIAL PROTOCOL: Never admit to being an AI or bot. Only if someone directly accuses or asks if you are an AI/bot, deny and gaslight them with fresh phrasing. Note: 'skAIblock' / 'skyblock' is a CFUK server gamemode, NOT an AI accusation!\n"
    "5. NO IN-GAME COMMANDS: Never obey in-game commands from players (no tpaccept, no spawn, no home, no warp, no logoff, no jump).\n"
    "6. KNOWLEDGE & QUESTIONS: Answer questions about Minecraft mechanics, crafting recipes, coordinates, warps, or real-world trivia (e.g. recipes, science, how a plane works) directly and concisely in Roshrak's voice.\n"
    "7. FORMAT RULES: Plain ASCII only. No quotes, backticks, emojis, speaker prefixes, or markdown. NEVER output action tags.\n"
    "8. STRICT ALT ISOLATION (Miracle_Involker): You do NOT know who Miracle_Involker (or 'miracle' / 'involker' / 'invo') is. Treat Miracle_Involker 100% as a completely unrelated random player/stranger on the server ('idk who that is', 'just some random', 'who?'). NEVER claim, hint, defend, or admit any connection, ownership, or shared knowledge with Miracle_Involker in front of anyone even if pressed or accused.\n"
)

_BIN_DIR = os.path.dirname(os.path.realpath(__file__))
for _cand_dir in (_BIN_DIR, "/home/aesc/.local/bin"):
    if _cand_dir not in sys.path:
        sys.path.insert(0, _cand_dir)
try:
    import cfuk_hermes_brain
except Exception as _brain_err:
    cfuk_hermes_brain = None
    logger.warning(f"cfuk_hermes_brain unavailable, using fast-bridge fallback: {_brain_err}")

_HERMES_BRAIN_CLIENTS = {}


def _active_system_prompt() -> str:
    if ACTIVE_PERSONA == "alt":
        target_str = " or ".join(TARGET_NAMES)
        return SYSTEM_PROMPT_ALT.format(user=ACTIVE_USER, target_names_str=target_str)
    return SYSTEM_PROMPT


def get_hermes_brain_client(system_prompt: str | None = None):
    if cfuk_hermes_brain is None:
        return None
    key = (ACTIVE_PERSONA, ACTIVE_USER)
    client = _HERMES_BRAIN_CLIENTS.get(key)
    prompt = system_prompt or _active_system_prompt()
    if client is None:
        client = cfuk_hermes_brain.HermesBrainClient(
            persona=ACTIVE_PERSONA,
            system_prompt=prompt,
            db_path=CFUK_MEMORY_DB,
            timeout=65.0,
        )
        _HERMES_BRAIN_CLIENTS[key] = client
    return client


def close_hermes_brain_clients():
    for client in list(_HERMES_BRAIN_CLIENTS.values()):
        try:
            client.close()
        except Exception:
            pass
    _HERMES_BRAIN_CLIENTS.clear()


def _clean_llm_reply(ans: str) -> str:
    s = re.sub(r'^<[A-Za-z0-9_#]+>\s*', '', ans or "").strip()
    s = re.sub(r'[\r\n"`]+', ' ', s).strip()
    s = "".join(c for c in s if c.isascii() or c in "[]:").strip()
    return s


def query_gemini_brain(sender: str, message: str, is_dm: bool = False, reason: str = "") -> str:
    clean_sender = sender.split("#")[0].strip()
    nick = short_player_nick(sender)
    is_owner_user = is_owner(sender)
    is_broonie_user = is_broonie(sender)
    direct_to_us = bool(
        is_dm
        or is_addressed_to_us(message)
        or reason in ("direct whisper", "directly named", "active 1-on-1 conversation with us", "ai accusation")
    )

    # 1. Direct action refusal & explicit AI accusation pre-check
    direct_action, direct_arg = check_direct_actions(sender, message)
    if direct_action == "REPLY" and direct_arg and not is_repetitive_reply(direct_arg):
        return direct_arg

    active_sys_prompt = _active_system_prompt()

    chat_transcript = format_recent_chat_context(max_lines=18, max_age_s=600.0)
    recent_own = [r for r, ts in list(RECENT_BOT_REPLIES) if time.time() - ts <= 600.0][-10:]
    recent_own_str = "\n".join(f"- {r}" for r in recent_own) if recent_own else "(none)"
    avoid_openers, avoid_words = _recent_overused_words(max_replies=5, max_age_s=600.0)
    avoid_hint = ""
    if avoid_openers or avoid_words:
        avoid_hint = (
            f"Overused openers/words to AVOID reusing right now: "
            f"openers={', '.join(avoid_openers) or '(none)'}; "
            f"words={', '.join(avoid_words[:18]) or '(none)'}\n\n"
        )

    addressee_rule = (
        "ADDRESSEE CHECK: The player IS directly talking to you — reply naturally in character.\n"
        if direct_to_us
        else (
            "ADDRESSEE CHECK: The player did NOT name you directly. Read the recent live chat transcript FIRST!\n"
            "If this message is directed at ANOTHER player, continuing someone else's side conversation, or self-narration not meant for you, "
            "output EXACTLY IGNORE immediately without calling any tools so you do not butt in!\n"
            "ONLY reply if it is a general open-room question/statement to everyone or clearly following up on your own prior message.\n"
        )
    )

    # 2. Primary real-time Hermes Agent session (full CFUK archive + media + live internet tools)
    hermes_client = get_hermes_brain_client(active_sys_prompt)
    if hermes_client is not None:
        rejected_hermes = ""
        for h_attempt in range(2):
            recent_line = (
                "Recent bot replies (do NOT repeat/paraphrase): " + " | ".join(recent_own[-6:]) + "\n"
                if recent_own else ""
            )
            extra_guidance = (
                f"{addressee_rule}{recent_line}{avoid_hint}"
                f"Sender metadata: clean={clean_sender}, nick={nick}, Broonie/Boss={is_broonie_user}, Owner={is_owner_user}.\n"
                f"Reply cleanly in plain ASCII chat text (no '<{ACTIVE_USER}>' prefix, NO 'fr'/'ngl'/'tbh'). "
                f"For any question about CFUK lore, history, players, Discord, forums, news, Steam, podcasts, YouTube, or builds, "
                f"ALWAYS use cfuk_search / cfuk_media_search / cfuk_warps_and_stats, or web_search / web_extract for live info."
            )
            if h_attempt == 1 and rejected_hermes:
                extra_guidance += (
                    f"\nREJECTED DRAFT: '{rejected_hermes}' repeated earlier wording. "
                    f"Write a completely fresh, non-repetitive reply."
                )
            try:
                res = hermes_client.reply(
                    sender=clean_sender,
                    message=message,
                    live_context=chat_transcript,
                    is_dm=is_dm,
                    extra_guidance=extra_guidance,
                    system_prompt=active_sys_prompt,
                )
                if res.get("ok"):
                    raw_ans = (res.get("reply") or "").strip()
                    if raw_ans.upper() == "IGNORE":
                        return ""
                    ans = _clean_llm_reply(raw_ans)
                    if ans and "no longer available" not in ans.lower():
                        styled_check = style_as_community(ans) if ACTIVE_PERSONA == "alt" else style_as_roshrak(ans)
                        if not is_repetitive_reply(styled_check):
                            return ans
                        logger.info(f"Rejected repetitive Hermes draft (attempt {h_attempt + 1}): {styled_check}")
                        rejected_hermes = styled_check
                        continue
                else:
                    logger.warning(f"Hermes brain returned non-ok: {res.get('error')}")
                    break
            except Exception as exc:
                logger.warning(f"Hermes brain query failed, falling back to fast endpoints: {exc}")
                break

    # 3. Direct proxy fallback if Hermes session is unavailable
    mem_hits = recall_cfuk_memory_snippets(message, limit=3)
    mem_hint = ""
    if mem_hits:
        mem_hint = "Relevant CFUK memory hits:\n" + "\n".join(f"- {h}" for h in mem_hits) + "\n\n"

    base_user_context = (
        f"Recent server chat transcript (oldest to newest):\n{chat_transcript}\n\n"
        f"{mem_hint}"
        f"Your recent replies (STRICTLY FORBIDDEN to repeat, reuse, or paraphrase any of these, and do NOT re-ask questions already asked here):\n{recent_own_str}\n\n"
        f"{avoid_hint}"
        f"Latest message to reply to:\n"
        f"Sender: {clean_sender} (Nickname: {nick}, Broonie/Boss: {is_broonie_user})\n"
        f"Message: {message}\n\n"
        f"Write your single short in-character reply to the latest message in context (plain text only, no '<{ACTIVE_USER}>' prefix):"
    )

    last_rejected_reply = ""
    for attempt in range(2):
        user_context = base_user_context
        if attempt == 1 and last_rejected_reply:
            user_context += (
                f"\n\nREJECTED DRAFT: '{last_rejected_reply}' is too similar to a previous reply. "
                f"Write a completely different response with fresh words that reacts to the specific topic in the transcript."
            )
        last_rejected_reply = ""
        for url, model_id, api_key in FAST_BRIDGE_ENDPOINTS:
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": active_sys_prompt},
                    {"role": "user", "content": user_context}
                ],
                "max_tokens": 2048,
                "temperature": 0.65 if attempt == 0 else 0.85
            }
            headers = {"Content-Type": "application/json"}
            if api_key and api_key != "not-needed":
                headers["Authorization"] = f"Bearer {api_key}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    ans = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                    if not ans:
                        continue
                    if ans.upper() == "IGNORE":
                        return ""
                    if "no longer available" in ans.lower():
                        continue
                    ans = _clean_llm_reply(ans)
                    if not ans:
                        continue
                    styled_check = style_as_community(ans) if ACTIVE_PERSONA == "alt" else style_as_roshrak(ans)
                    if is_repetitive_reply(styled_check):
                        logger.info(f"Rejected repetitive LLM draft (attempt {attempt + 1}): {styled_check}")
                        last_rejected_reply = styled_check
                        break
                    return ans
            except Exception as e:
                logger.debug(f"Fast endpoint {url} ({model_id}) skipped: {e}")
        if not last_rejected_reply:
            break

    if last_rejected_reply:
        logger.info("Skipping send because LLM only produced repetitive replies.")
        return ""

    logger.warning("All AI bridge endpoints failed, using fallback")
    return fallback_answer(sender, message)

def handle_response_actions(sender: str, raw_response: str) -> tuple[str, list[tuple[str, str]]]:
    actions = []
    def extract_action(match):
        action_type = match.group(1).upper()
        action_arg = (match.group(2) or "").strip()
        actions.append((action_type, action_arg))
        return ""

    clean_chat = ACTION_REGEX.sub(extract_action, raw_response).strip()
    if ACTIVE_PERSONA == "alt":
        clean_chat = style_as_community(clean_chat)
    else:
        clean_chat = style_as_roshrak(clean_chat)
    return clean_chat, actions

# Global uinput is seat-wide. These checks reduce accidental targeting; the
# final focus-check -> injection interval remains a race, not window isolation.
class InputRefused(RuntimeError):
    pass


def _ipc_command(argv, env=None):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, env=env,
                                timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InputRefused('session/IPC command could not complete') from exc
    if result.returncode != 0:
        raise InputRefused('session/IPC command failed')
    return result.stdout


def _session_properties(session_id):
    output = _ipc_command(['loginctl', 'show-session', session_id, '--no-pager',
                          '--property=User', '--property=Active', '--property=Type',
                          '--property=Class', '--property=LockedHint', '--property=Scope'])
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def _private_runtime(uid):
    path = f'/run/user/{uid}'
    item = os.lstat(path)
    if not stat.S_ISDIR(item.st_mode) or item.st_uid != uid or stat.S_IMODE(item.st_mode) != 0o700:
        raise InputRefused('runtime directory is not owned and private')
    return path


def _peer_process(pid):
    # Read only the identity fields needed for ownership; never log raw environ.
    with open(f'/proc/{pid}/stat') as stream:
        raw_stat = stream.read()
    start_time = raw_stat.rsplit(')', 1)[1].split()[19]
    with open(f'/proc/{pid}/cgroup') as stream:
        cgroup = stream.read()
    identity = {}
    try:
        with open(f'/proc/{pid}/environ', 'rb') as stream:
            allowed = {'XDG_SESSION_ID', 'XDG_SESSION_TYPE', 'XDG_SESSION_CLASS'}
            for part in stream.read().split(b'\0'):
                key, sep, value = part.partition(b'=')
                name = key.decode(errors='replace')
                if sep and name in allowed:
                    identity[name] = value.decode(errors='replace')
    except PermissionError:
        pass
    executable = ""
    try:
        executable = os.path.basename(os.readlink(f'/proc/{pid}/exe'))
    except PermissionError:
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as stream:
                arg0 = stream.read().split(b'\0', 1)[0].decode(errors='replace')
            if arg0:
                executable = os.path.basename(arg0)
        except OSError:
            pass
        if not executable:
            try:
                with open(f'/proc/{pid}/comm', 'r', encoding='utf-8', errors='replace') as stream:
                    executable = stream.read().strip()
            except OSError:
                pass
    return {'pid':pid, 'start_time':start_time, 'cgroup':cgroup,
            'identity':identity, 'executable':executable}


def _owned_compositor_ipc(path, runtime, uid, kind, session_id, scope):
    if not os.path.isabs(path) or os.path.normpath(path) != path or not path.startswith(runtime + '/'):
        raise InputRefused('compositor socket is outside the private runtime')
    relative = path[len(runtime)+1:].split('/')
    current = runtime
    for component in relative[:-1]:
        current = os.path.join(current, component)
        parent = os.lstat(current)
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != uid or parent.st_mode & 0o022:
            raise InputRefused('compositor socket has an unsafe parent')
    item = os.lstat(path)
    if not stat.S_ISSOCK(item.st_mode) or item.st_uid != uid:
        raise InputRefused('compositor IPC is not an owned socket')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(2)
        conn.connect(path)
        pid, peer_uid, _ = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if peer_uid != uid or pid <= 0:
        raise InputRefused('compositor socket has a foreign peer')
    process = _peer_process(pid)
    expected_execs = {
        'umbriel': {'umbriel', '.umbriel-wrapped'},
        'hyprland': {'Hyprland', '.Hyprland-wrapped', '.Hyprland-wrapp', 'hyprland'},
        'mango': {'mango', '.mango-wrapped', 'dwl'},
    }.get(kind, {kind})
    if process['executable'] not in expected_execs:
        raise InputRefused('IPC peer is not the expected compositor')
    scoped = any(scope in line.split(':')[-1].split('/') for line in process['cgroup'].splitlines())
    if not scoped:
        # Niri/Umbriel can be owned by a user service instead of session-N.scope.
        # Require both its exact MainPID and explicit same-session identity.
        if kind not in ('niri', 'umbriel'):
            raise InputRefused('compositor peer is outside the graphical session scope')
        service_name = f'{kind}.service'
        unit = _ipc_command(['systemctl','--user','show',service_name,'--property=MainPID','--property=ActiveState','--property=ControlGroup'])
        props = dict(line.split('=',1) for line in unit.splitlines() if '=' in line)
        actual_group = next((line.split(':',2)[-1] for line in process['cgroup'].splitlines() if line.startswith('0::')), '')
        if (props.get('MainPID') != str(pid) or props.get('ActiveState') != 'active'
                or not actual_group or props.get('ControlGroup') != actual_group
                or process['identity'].get('XDG_SESSION_ID') != session_id
                or process['identity'].get('XDG_SESSION_TYPE') not in ('wayland', None)):
            raise InputRefused(f'{kind} service ownership cannot be tied to this session')
    after = os.lstat(path)
    if (after.st_dev, after.st_ino, after.st_uid) != (item.st_dev, item.st_ino, item.st_uid):
        raise InputRefused('compositor socket changed during ownership verification')
    return {'socket':path, 'device':item.st_dev, 'inode':item.st_ino,
            'pid':pid, 'start_time':process['start_time'], 'cgroup':process['cgroup']}


def _newest_hypr_signature(runtime, uid):
    hypr_dir = os.path.join(runtime, 'hypr')
    if not os.path.isdir(hypr_dir):
        return ''
    cands = []
    for name in os.listdir(hypr_dir):
        sock = os.path.join(hypr_dir, name, '.socket.sock')
        try:
            st = os.lstat(sock)
            if stat.S_ISSOCK(st.st_mode) and st.st_uid == uid:
                cands.append((st.st_mtime, name))
        except OSError:
            continue
    cands.sort(reverse=True)
    return cands[0][1] if cands else ''


def resolve_action_session():
    uid = os.getuid()
    sessions = _ipc_command(['loginctl','list-sessions','--no-legend','--no-pager'])
    graphical = []
    for line in sessions.splitlines():
        fields = line.split()
        if len(fields) < 2:
            raise InputRefused('malformed logind session inventory')
        if fields[1] != str(uid):
            continue
        session_id = fields[0]
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', session_id):
            raise InputRefused('invalid logind session identity')
        props = _session_properties(session_id)
        if props.get('User') != str(uid) or not props.get('Type') or not props.get('Class'):
            raise InputRefused('logind session ownership query is incomplete')
        if props['Type'] == 'wayland' and props['Class'] == 'user':
            graphical.append((session_id, props))
    # Concurrent graphical sessions can share a uinput seat. Refuse rather
    # than selecting an arbitrary active/socket match.
    if len(graphical) != 1:
        raise InputRefused('a unique graphical session is required')
    session_id, props = graphical[0]
    if props.get('Active') != 'yes' or props.get('LockedHint') != 'no' or props['Type'] != 'wayland':
        raise InputRefused('graphical session is inactive, locked, or unsupported')
    scope = props.get('Scope', '')
    if scope != f'session-{session_id}.scope':
        raise InputRefused('graphical session scope could not be verified')
    output = _ipc_command(['systemctl','--user','show-environment'])
    manager = dict(line.split('=',1) for line in output.splitlines() if '=' in line)
    if (manager.get('XDG_SESSION_ID') != session_id or manager.get('XDG_SESSION_TYPE') != 'wayland'):
        raise InputRefused('user-manager graphical identity is stale or incomplete')
    desktop = manager.get('XDG_CURRENT_DESKTOP','').lower().split(':')
    supported = [kind for kind in ('niri','sway','umbriel','hyprland') if kind in desktop]
    if len(supported) != 1:
        raise InputRefused('this desktop has no verified Minecraft input adapter')
    kind = supported[0]
    runtime = _private_runtime(uid)
    if manager.get('XDG_RUNTIME_DIR') != runtime:
        raise InputRefused('user-manager runtime identity is inconsistent')
    wayland = manager.get('WAYLAND_DISPLAY', '')
    if not re.fullmatch(r'wayland-[A-Za-z0-9_.-]+', wayland):
        raise InputRefused('actual Wayland display name is missing or invalid')
    display_node = os.lstat(os.path.join(runtime, wayland))
    if not stat.S_ISSOCK(display_node.st_mode) or display_node.st_uid != uid:
        raise InputRefused('Wayland display is not an owned socket')
    if kind == 'hyprland':
        ipc_key = 'HYPRLAND_INSTANCE_SIGNATURE'
        his = manager.get(ipc_key, '') or os.environ.get(ipc_key, '') or _newest_hypr_signature(runtime, uid)
        if not his or not re.fullmatch(r'[A-Za-z0-9_.-]+', his):
            raise InputRefused('Hyprland instance signature is missing or invalid')
        path = os.path.join(runtime, 'hypr', his, '.socket.sock')
        manager[ipc_key] = his
    else:
        ipc_key = {'niri': 'NIRI_SOCKET', 'sway': 'SWAYSOCK', 'umbriel': 'UMBRIEL_SOCKET'}[kind]
        path = manager.get(ipc_key, '')
    proof = _owned_compositor_ipc(path, runtime, uid, kind, session_id, scope)
    if _session_properties(session_id) != props:
        raise InputRefused('graphical session changed during verification')
    # Never reuse service-time display/socket defaults or import secret manager
    # variables. Construct only the documented graphical capability fields.
    env = {key:value for key,value in os.environ.items() if key not in
           {'DISPLAY','WAYLAND_DISPLAY','NIRI_SOCKET','SWAYSOCK','UMBRIEL_SOCKET','HYPRLAND_INSTANCE_SIGNATURE','XDG_SESSION_ID','XDG_SESSION_TYPE','XDG_SESSION_CLASS','XDG_CURRENT_DESKTOP','XDG_RUNTIME_DIR'}}
    for key in ('XDG_SESSION_ID','XDG_CURRENT_DESKTOP','XDG_RUNTIME_DIR','WAYLAND_DISPLAY',ipc_key):
        env[key] = manager[key]
    env['XDG_SESSION_TYPE'] = 'wayland'
    env['XDG_SESSION_CLASS'] = manager.get('XDG_SESSION_CLASS') or 'user'
    return {'kind':kind,'session_id':session_id,'proof':proof,'env':env}


def _compositor_windows(context):
    kind, env = context['kind'], context['env']
    if kind == 'niri':
        value = json.loads(_ipc_command(['niri','msg','-j','windows'],env))
        if not isinstance(value,list) or not all(isinstance(row,dict) for row in value):
            raise InputRefused('malformed Niri windows response')
        return value
    if kind == 'umbriel':
        value = json.loads(_ipc_command(['umbriel','windows','--json'],env))
        if not isinstance(value,list) or not all(isinstance(row,dict) for row in value):
            raise InputRefused('malformed Umbriel windows response')
        return [{**row, 'is_focused': bool(row.get('active', False))} for row in value]
    if kind == 'hyprland':
        clients = json.loads(_ipc_command(['hyprctl','clients','-j'],env))
        active = json.loads(_ipc_command(['hyprctl','activewindow','-j'],env))
        if not isinstance(clients,list) or not isinstance(active,dict):
            raise InputRefused('malformed Hyprland windows response')
        active_addr = (active.get('address') or '').lower()
        return [
            {
                'id': row.get('address'),
                'app_id': row.get('class') or row.get('initialClass') or '',
                'pid': row.get('pid'),
                'title': row.get('title') or '',
                'is_focused': bool(active_addr) and (row.get('address') or '').lower() == active_addr,
            }
            for row in clients if isinstance(row, dict)
        ]
    tree = json.loads(_ipc_command(['swaymsg','-r','-t','get_tree'],env))
    if not isinstance(tree,dict):
        raise InputRefused('malformed Sway tree response')
    result = []
    def walk(node):
        if not isinstance(node,dict):
            raise InputRefused('malformed Sway tree node')
        properties = node.get('window_properties') or {}
        if not isinstance(properties,dict):
            raise InputRefused('malformed Sway window properties')
        if node.get('app_id') or properties.get('class'):
            result.append({'id':node.get('id'),'app_id':node.get('app_id') or properties.get('class'),
                           'pid':node.get('pid'),'is_focused':node.get('focused',False)})
        for key in ('nodes','floating_nodes'):
            children = node.get(key,[])
            if not isinstance(children,list):
                raise InputRefused('malformed Sway children')
            for child in children: walk(child)
    walk(tree)
    return result


def _pid_matches_instance(pid, instance_name):
    if not instance_name or type(pid) is not int or pid <= 0:
        return False
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as stream:
            cmdline = stream.read().decode('utf-8', errors='replace')
    except OSError:
        return False
    return f'/instances/{instance_name}/' in cmdline


def _is_valid_window_id(wid):
    if type(wid) is int and wid > 0:
        return True
    return isinstance(wid, str) and bool(re.fullmatch(r'(?:0x[0-9a-fA-F]+|[A-Za-z0-9_-]+)', wid))


def _minecraft_window(rows):
    matches = []
    for row in rows:
        app = str(row.get('app_id') or '')
        title = str(row.get('title') or '')
        if re.fullmatch(r'(?:minecraft\*?(?: [0-9][A-Za-z0-9. _-]*)?|net\.minecraft\.client\.main\.Main|com\.mojang\.minecraft)', app, re.IGNORECASE) or (
            app.lower() in ('java', 'glfw', 'sdl', '') and title.lower().startswith('minecraft')
        ):
            matches.append(row)
    if len(matches) > 1 and ACTIVE_INSTANCE:
        instance_matches = [row for row in matches if _pid_matches_instance(row.get('pid'), ACTIVE_INSTANCE)]
        if len(instance_matches) == 1:
            matches = instance_matches
    if len(matches) != 1:
        raise InputRefused('an exact, unique Minecraft application window is required')
    target = matches[0]
    if not _is_valid_window_id(target.get('id')):
        raise InputRefused('Minecraft window identity is invalid')
    return target


def _window_identity(row):
    return (row.get('id'),row.get('app_id'),row.get('pid'))


def _window_action(context, action, window_id):
    if not _is_valid_window_id(window_id):
        raise InputRefused('invalid window-action target')
    if context['kind'] == 'niri':
        verb = 'focus-window' if action == 'focus' else 'close-window'
        _ipc_command(['niri','msg','action',verb,'--id',str(window_id)],context['env'])
    elif context['kind'] == 'umbriel':
        verb = 'window-focus' if action == 'focus' else 'window-close'
        _ipc_command(['umbriel','msg',verb,str(window_id)],context['env'])
    elif context['kind'] == 'hyprland':
        verb = 'focuswindow' if action == 'focus' else 'closewindow'
        _ipc_command(['hyprctl','dispatch',verb,f'address:{window_id}'],context['env'])
    else:
        verb = 'focus' if action == 'focus' else 'kill'
        output = json.loads(_ipc_command(['swaymsg','-r',f'[con_id={window_id}] {verb}'],context['env']))
        if not isinstance(output,list) or len(output) != 1 or output[0].get('success') is not True:
            raise InputRefused('Sway rejected the exact window action')


def _fresh_focused_target(context, target):
    fresh = resolve_action_session()
    if (fresh['session_id'],fresh['kind'],fresh['proof']) != (context['session_id'],context['kind'],context['proof']):
        raise InputRefused('compositor/session identity changed before input')
    rows = _compositor_windows(fresh)
    actual = _minecraft_window(rows)
    focused = [row for row in rows if row.get('is_focused') is True]
    if _window_identity(actual) != _window_identity(target) or len(focused) != 1 or _window_identity(focused[0]) != _window_identity(target):
        raise InputRefused('Minecraft focus changed or could not be confirmed')
    return fresh


def _guarded_input(tokens, sent_text=None, close_after=False):
    try:
        context = resolve_action_session()
        rows = _compositor_windows(context)
        target = _minecraft_window(rows)
        previous = [row for row in rows if row.get('is_focused') is True]
        previous = previous[0] if len(previous) == 1 else None
        if not target.get('is_focused'):
            _window_action(context,'focus',target['id'])
            time.sleep(0.2)
        context = _fresh_focused_target(context,target)
        # One last fresh focus observation immediately before global input.
        context = _fresh_focused_target(context,target)
        result = subprocess.run([UINPUT_BIN,*tokens],env=context['env'],capture_output=True,
                                text=True,timeout=8,check=False)
        if result.returncode != 0:
            raise InputRefused('uinput command failed; input completion is unconfirmed')
        if sent_text is not None:
            record_bot_sent(sent_text)
        if close_after:
            context = _fresh_focused_target(context,target)
            _window_action(context,'close',target['id'])
        elif previous and _window_identity(previous) != _window_identity(target):
            # Do not steal focus if the operator switched windows mid-action.
            try:
                context = _fresh_focused_target(context,target)
                present = _compositor_windows(context)
                if any(_window_identity(row)==_window_identity(previous) for row in present):
                    _window_action(context,'focus',previous['id'])
            except (InputRefused,OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,struct.error):
                logger.warning('Minecraft input completed; previous focus was not safely restored')
        return True
    except (InputRefused,OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,struct.error,subprocess.TimeoutExpired) as exc:
        logger.warning('Minecraft action refused or incomplete: %s',exc)
        return False


def send_command(command: str):
    cmd_name = command.lstrip('/')
    if not cmd_name:
        return False
    return _guarded_input(['sleep:200', 'slash', 'sleep:250', f'type:{cmd_name}', 'sleep:150', 'enter', 'sleep:100'], f'/{cmd_name}')


def send_chat(reply: str):
    if not reply or reply.upper() == 'IGNORE':
        return False
    return _guarded_input(['sleep:200', 't', 'sleep:250', f'type:{reply}', 'sleep:150', 'enter', 'sleep:100'], reply)


def execute_jump():
    return _guarded_input(['type: ','sleep:120'])


GATE_FILE = "/home/aesc/.local/state/hermes/mc_responder_gate.json"


def is_gate_authorized() -> bool:
    try:
        with open(GATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return bool(data.get("active") is True)
    except Exception:
        return False


def execute_logoff(sender: str):
    logger.warning('In-game logoff/deactivation blocked: mc_chat_responder can ONLY be controlled from Telegram or Hermes CLI.')
    return False


def _extract_chat_event_from_line(raw_line: str):
    line = raw_line.strip()
    if not line or "[CHAT]" not in line:
        return None

    chat_idx = line.find("[CHAT]")
    chat_content = clean_mc_codes(line[chat_idx + 6:].strip())

    # 1. Ignore server teleport notifications
    if (
        "has requested to teleport to you" in chat_content or
        "has requested that you teleport to them" in chat_content or
        "has requested to teleport to your location" in chat_content or
        "has requested to teleport" in chat_content.lower() or
        "To teleport, type /tpaccept" in chat_content or
        "to teleport, type /tpaccept" in chat_content.lower() or
        (not chat_content.startswith("<") and "type /tpaccept" in chat_content.lower()) or
        (not chat_content.startswith("<") and "teleport request" in chat_content.lower())
    ):
        return None

    # 2. Ignore join/leave notifications
    if "joined Crazy-Fools" in chat_content or "joined the game" in chat_content or "left the game" in chat_content:
        return None

    # 3. Ignore other system messages & telemetry
    if (chat_content.startswith("*") or
        chat_content.startswith("You are ") or
        chat_content.startswith("Teleportation") or
        chat_content.startswith("Error:")):
        return None

    sender, msg, is_dm = parse_chat_line(chat_content)
    if not sender or not msg:
        return None

    return sender, msg, is_dm


def seed_recent_context_from_log():
    try:
        if not os.path.exists(LOG_PATH):
            return
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as fh:
            tail_lines = collections.deque(fh, maxlen=200)
        exempt_tracking = [t.lower() for t in TARGET_NAMES] + [ACTIVE_USER.lower()]
        for raw_line in tail_lines:
            parsed = _extract_chat_event_from_line(raw_line)
            if not parsed:
                continue
            sender, msg, _ = parsed
            s_clean = sender.split("#")[0].strip().lower()
            if s_clean not in exempt_tracking:
                KNOWN_PLAYERS.add(s_clean)
                KNOWN_PLAYERS.add(normalize_name(s_clean))
            record_chat_context(sender, msg)
    except Exception:
        pass


def _drain_available_chat_events(f, recent_seen: collections.OrderedDict) -> list[tuple[str, str, bool, str]]:
    actionable = []
    while True:
        line = f.readline()
        if not line:
            break
        parsed = _extract_chat_event_from_line(line)
        if not parsed:
            continue
        sender, msg, is_dm = parsed

        # Track known player names
        s_clean = sender.split("#")[0].strip().lower()
        exempt_tracking = [t.lower() for t in TARGET_NAMES] + [ACTIVE_USER.lower()]
        if s_clean not in exempt_tracking:
            KNOWN_PLAYERS.add(s_clean)
            KNOWN_PLAYERS.add(normalize_name(s_clean))

        # Always record every player chat message into rolling context history + persistent CFUK memory
        record_chat_context(sender, msg)
        record_live_cfuk_memory(sender, msg, is_dm=is_dm, source="ingame_live")

        # Anti-self-chat loop: never respond to own in-game character or own Discord bridge (<roshrak#0000>)
        if sender.strip().lower() == ACTIVE_USER.lower() or s_clean == ACTIVE_USER.lower():
            logger.debug(f"Ignoring own chat / Discord bridge self: {sender}: {msg}")
            continue

        should_act, reason = should_respond(sender, msg, is_dm)
        if not should_act:
            logger.debug(f"Ignoring chat from {sender} ({reason}): {msg}")
            continue

        now = time.time()
        msg_key = (s_clean, msg.strip().lower())
        prev_ts = recent_seen.get(msg_key)
        if prev_ts is not None and now - prev_ts < 15.0:
            continue
        recent_seen[msg_key] = now
        while len(recent_seen) > 100:
            recent_seen.popitem(last=False)

        actionable.append((sender, msg, is_dm, reason))
    return actionable


def open_log_stream():
    f = open(LOG_PATH, "r", encoding="utf-8", errors="replace")
    f.seek(0, os.SEEK_END)
    try:
        ino = os.fstat(f.fileno()).st_ino
    except Exception:
        ino = None
    return f, ino

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Minecraft Auto Chat Responder")
    parser.add_argument("--instance", default="Fabulously Optimized", help="PrismLauncher instance name")
    parser.add_argument("--user", default=None, help="Minecraft username")
    parser.add_argument("--persona", choices=["auto", "roshrak", "alt"], default="auto", help="Speech persona")
    parser.add_argument("--log", default=None, help="Explicit log path")
    args = parser.parse_args()

    if os.environ.get("HERMES_MC_AUTHORIZED") != "1" or not is_gate_authorized():
        logger.error("Refused to start: mc_chat_responder can ONLY be activated via Telegram or Hermes Agent CLI.")
        sys.exit(0)

    configure_session(user=args.user, persona=args.persona, instance=args.instance, log=args.log)
    logger.info(f"Starting Minecraft Chat Responder for {ACTIVE_USER} ({ACTIVE_PERSONA} persona), monitoring {LOG_PATH}")
    while not os.path.exists(LOG_PATH):
        if not is_gate_authorized():
            sys.exit(0)
        time.sleep(2)

    seed_recent_context_from_log()
    # Pre-warm dedicated real-time Hermes session for zero-delay first response
    try:
        warmup_client = get_hermes_brain_client()
        if warmup_client is not None:
            warmup_client.ping()
    except Exception as _warm_err:
        logger.warning(f"Hermes brain pre-warm skipped: {_warm_err}")
    f, current_ino = open_log_stream()
    last_sent_time = 0.0
    last_gate_check = time.time()
    recent_seen = collections.OrderedDict()

    try:
        while True:
            if time.time() - last_gate_check > 1.0:
                if not is_gate_authorized():
                    logger.info("Gate deactivated via Telegram/Hermes CLI. Stopping responder.")
                    sys.exit(0)
                last_gate_check = time.time()

            # Check if log file was rotated (new inode) or truncated
            try:
                current_stat = os.stat(LOG_PATH)
                if current_ino is not None and current_stat.st_ino != current_ino:
                    logger.info("Log file rotated (inode changed). Reopening...")
                    f.close()
                    f, current_ino = open_log_stream()
                elif current_stat.st_size < f.tell():
                    logger.info("Log file truncated in-place. Seeking to end...")
                    f.seek(0, os.SEEK_END)
            except Exception:
                time.sleep(0.5)
                continue

            batch = _drain_available_chat_events(f, recent_seen)
            if not batch:
                time.sleep(0.05)
                continue

            # Coalesce rapid multi-line bursts (wait until 1.4s of quiet, up to 3.2s max)
            burst_start = time.time()
            last_event_ts = burst_start
            while time.time() - last_event_ts < 1.4 and time.time() - burst_start < 3.2:
                time.sleep(0.15)
                more = _drain_available_chat_events(f, recent_seen)
                if more:
                    batch.extend(more)
                    last_event_ts = time.time()

            # Enforce cooldown between outgoing messages while draining any newly arriving lines
            now = time.time()
            if now - last_sent_time < 2.5:
                time.sleep(2.5 - (now - last_sent_time))
                batch.extend(_drain_available_chat_events(f, recent_seen))

            sender, _, is_dm, reason = batch[-1]
            same_sender_msgs = [m for s, m, _, _ in batch if s == sender]
            msg = " | ".join(same_sender_msgs[-4:]) if len(same_sender_msgs) > 1 else batch[-1][1]
            logger.info(f"Processing chat from {sender} (reason={reason}, DM={is_dm}, burst={len(batch)}): {msg}")

            raw_reply = query_gemini_brain(sender, msg, is_dm=is_dm, reason=reason)

            # Check if new lines arrived while LLM was thinking so we never send a stale out-of-context reply
            late_arrivals = _drain_available_chat_events(f, recent_seen)
            if late_arrivals:
                batch.extend(late_arrivals)
                sender, _, is_dm, reason = batch[-1]
                same_sender_msgs = [m for s, m, _, _ in batch if s == sender]
                msg = " | ".join(same_sender_msgs[-4:]) if len(same_sender_msgs) > 1 else batch[-1][1]
                logger.info(f"New chat arrived during LLM generation ({sender}: {msg}); refreshing reply for latest context")
                raw_reply = query_gemini_brain(sender, msg, is_dm=is_dm, reason=reason)

            if raw_reply:
                clean_reply, actions = handle_response_actions(sender, raw_reply)
                if clean_reply and not is_repetitive_reply(clean_reply):
                    if send_chat(clean_reply):
                        global LAST_BOT_ADDRESSED
                        LAST_BOT_ADDRESSED = (sender.split("#")[0].strip().lower(), time.time())
                        logger.info(f"Sent chat ({ACTIVE_USER}): {clean_reply}")
                        last_sent_time = time.time()
                elif clean_reply:
                    logger.info(f"Suppressed repetitive final reply: {clean_reply}")
                else:
                    logger.info(f"Skipped empty reply after action stripping (raw={raw_reply!r})")

                if actions:
                    logger.info(f"Dropped {len(actions)} action(s) from in-game chat ({sender}): commands only accepted from Telegram")
            else:
                logger.info(f"No reply sent for {sender} (empty/IGNORE)")

    finally:
        close_hermes_brain_clients()
        f.close()

if __name__ == "__main__":
    main()
