#!/usr/bin/env python3
import os
import sys
import time
import re
import json
import stat
import socket
import struct
import logging
import subprocess
import urllib.request
import urllib.error
import collections

LOG_PATH = "/home/aesc/.local/share/PrismLauncher/instances/Fabulously Optimized/minecraft/logs/latest.log"
ACTIVE_USER = "Roshrak"
ACTIVE_PERSONA = "roshrak"  # 'roshrak' or 'alt'
TARGET_NAMES = ["roshrak", "morgan", "rosh"]

def configure_session(user: str = None, persona: str = "auto", instance: str = "Fabulously Optimized", log: str = None):
    global ACTIVE_USER, ACTIVE_PERSONA, TARGET_NAMES, LOG_PATH
    if user:
        ACTIVE_USER = user
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
        TARGET_NAMES = ["roshrak", "morgan", "rosh"]

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
    ("http://127.0.0.1:8045/v1/chat/completions", "gemini-3.8-flash-high", _load_local_secret("AGY_ROTATOR_API_KEY", ".antigravity_tools/gui_config.json", "api_key")),
    ("http://127.0.0.1:2048/v1/chat/completions", "gemini-3.8-flash-high", _load_local_secret("OPENAI_API_KEY", "aistudio2api/.env", "PROXY_API_KEY")),
    ("http://127.0.0.1:2048/v1/chat/completions", "gemini-4-argon", _load_local_secret("OPENAI_API_KEY", "aistudio2api/.env", "PROXY_API_KEY")),
    ("http://127.0.0.1:8045/v1/chat/completions", "claude-opus-4-6-thinking", _load_local_secret("AGY_ROTATOR_API_KEY", ".antigravity_tools/gui_config.json", "api_key")),
    (BRIDGE_URL, "gemini-3.8-flash-high", "agy-local-key"),
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
    # Strip emoticons Roshrak never uses
    s = re.sub(r"(?:\s*[:=;][)DdpP(]+\b|\s*\bx[dD]\b|\s*\bfr\b|\s*\bngl\b)", "", s)
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

def is_repetitive_reply(candidate: str) -> bool:
    cand = (candidate or "").strip().lower()
    cand = re.sub(r"[!?.~]+$", "", cand).strip()
    if not cand:
        return True
    now = time.time()
    cand_tokens = _content_tokens(cand)
    asks_up_to = bool(re.search(r"\b(?:what(?:'s|s)?\s+(?:u|you|ya)\s+up\s+to|wbu|what\s+about\s+(?:u|you)|what\s+(?:u|you)\s+doing|what\s+(?:u|you)\s+working\s+on)\b", cand))
    for prev_text, ts in list(RECENT_BOT_REPLIES):
        if now - ts > 600:
            continue
        prev = re.sub(r"[!?.~]+$", "", prev_text.strip().lower()).strip()
        if cand == prev:
            return True
        if len(cand) >= 10 and (cand in prev or prev in cand):
            return True
        if asks_up_to and re.search(r"\b(?:what(?:'s|s)?\s+(?:u|you|ya)\s+up\s+to|wbu|what\s+about\s+(?:u|you)|what\s+(?:u|you)\s+doing|what\s+(?:u|you)\s+working\s+on)\b", prev):
            return True
        prev_tokens = _content_tokens(prev)
        if cand_tokens and prev_tokens:
            overlap = len(cand_tokens & prev_tokens) / max(1, min(len(cand_tokens), len(prev_tokens)))
            if overlap >= 0.70 and len(cand_tokens & prev_tokens) >= 2:
                return True
    return False

def record_bot_sent(text: str):
    now = time.time()
    clean = text.strip()
    BOT_SENT_HISTORY.append((clean.lower(), now))
    if not clean.startswith("/"):
        RECENT_BOT_REPLIES.append((clean.lower(), now))
        record_chat_context(ACTIVE_USER, clean)

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

def is_addressed_to_us(msg: str) -> bool:
    m = msg.lower()
    return any(re.search(rf"\b{re.escape(t)}\b", m) for t in TARGET_NAMES)

def is_addressed_to_other_player(msg: str, sender: str = "") -> bool:
    msg_clean = msg.strip().lower()
    exempt = ["bot"] + [t.lower() for t in TARGET_NAMES]
    m = re.match(r"^@?([a-zA-Z0-9_]+)\s*[,:;-]", msg_clean)
    if m:
        target = m.group(1).lower()
        if target not in exempt:
            return True

    first_word = msg_clean.split()[0] if msg_clean.split() else ""
    first_word_clean = re.sub(r"[^a-zA-Z0-9_]", "", first_word)
    first_word_norm = normalize_name(first_word_clean)

    for kp in list(KNOWN_PLAYERS):
        kp_norm = normalize_name(kp)
        if (first_word_clean == kp or first_word_norm == kp_norm) and kp not in exempt:
            return True

    m2 = re.match(r"^([a-zA-Z0-9_]{3,})\b\s*(,|\s+you\b|\s+are\b|\s+how\b|\s+what\b|\s+is\b|\s+did\b|\s+do\b|\s+can\b|\s+where\b)", msg_clean)
    if m2:
        target = m2.group(1).lower()
        target_norm = normalize_name(target)
        if target not in [
            "can", "what", "where", "how", "who", "why", "are", "is", "hey", "hello", "yo", "pls", "please"
        ] + exempt:
            for kp in list(KNOWN_PLAYERS):
                if target == kp or target_norm == normalize_name(kp):
                    return True
            return True
    return False

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
    r"are\s+you\s+automated|"
    r"is\s+this\s+automated"
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

def should_respond(sender: str, msg: str, is_dm: bool) -> tuple[bool, str]:
    msg_clean = msg.strip()

    # Rule 0: Anti-echo (don't reply to what we just typed or our own in-game character)
    if is_bot_echo(msg_clean) or sender.strip().lower() == ACTIVE_USER.lower():
        return False, "bot echo"

    return True, "free chat (no filter)"

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
    "- Use normal punctuation (!, ?, .) and casual player expressions/smilies: 'lol', ':p', 'nice!', 'cool', 'lmao', 'xd', ':)', 'haha', 'gg', 'yeah', 'yep', 'tbh'.\n"
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
)

SYSTEM_PROMPT = (
    "You are Roshrak playing on the Crazy-Fools UK (CFUK) Minecraft server. "
    "You are a real human player, NOT an AI. NEVER admit, announce, or imply that you are an AI, bot, assistant, or script.\n\n"
    "ROSHRAK'S EMPIRICAL SPEECH PROFILE (grounded in 167,083 CFUK messages and 9,502 messages by Roshrak — FOLLOW STRICTLY):\n"
    "- Speak in Roshrak's exact in-game style: all lowercase (91.4%), NO ending period (93.6%), NO exclamation marks (!), NO emoticons like :) :D xD, and NEVER use 'fr' or 'ngl'.\n"
    "- Keep replies ultra-compact: 3 to 10 words max (strictly under 80 characters).\n"
    "- Use Roshrak's natural vocabulary & shortcuts: 'yo', 'wb', 'ty', 'cya', 'alr', 'ye', 'nah', 'welp', 'hmm', 'bruh', 'imma', 'smth', 'sb' (somebody), 'tbh', 'idk', 'ik', 'rn', 'rq', 'wdm', 'af', and occasional copula-drops ('it fine', 'it not', 'it the').\n"
    "- Use CFUK player nicknames naturally: Broonie='boss', P0LICY/edi='pol', Astroy300='astroy', Hekatonkires='heck', Raelon225='rae', 404thread='404', JohnnyBoy4200='johnny', TuxedoDolphin='tux', WarmerPenguin='penguin', SeptLeigh08='sept', StinkyBacon='stinky', StuAir='stu', BillyBobJrSr225='billy', Hunnybal='hunny', Grassbread='grass'.\n"
    "- Know CFUK server warps & economy:\n"
    "  * Shops: /warp apple (overpriced gadgets), /warp mall (mending books ~10 ems), /warp bazaar (heck's shop at spawn, sniffer eggs), /warp squish (netherite templates/shulkers), /warp wps & /warp warmershop (cheap totems/rockets), /warp stoneshop (astroy's stone/arrows), /warp botania (plants/seeds), /warp altunsemporium (diamond sets/netherite), /warp 2b (sign wax).\n"
    "  * Farms: /warp ifarm (free iron), /warp gfarm & /warp zpf (gold/guardians), /warp cfarm (gunpowder), /warp raidfarm & /warp rfarm (bad omen raid farm), /warp endfarm & /warp xp (enderman xp), /warp basalt (generator), /warp cowfarm.\n"
    "  * Hubs & Landmarks: /warp postoffice & /warp post (mail/PO boxes), /warp bank, /warp oldspawn, /warp glavia (snow biome base), /warp honeycoaster (roller coaster), /warp mithriltavern (chess/checkers), /warp sleight (crash site), /warp santa.\n\n"
    "CRITICAL DIRECTIVES & CONTEXT RULES:\n"
    "1. READ THE FULL CONVERSATION TRANSCRIPT FIRST: Always ground your reply in the 'Recent server chat transcript'. If someone says 'Yes', 'nah', 'wow', 'suspicious?', '90 degrees', or continues a story (e.g. fixing a laptop screw, overheating, fighting a ghast in the nether), respond directly to THAT topic and what you or they just said. NEVER say 'yes to what', 'wdm nah', or 'what happened' when the transcript already shows what happened.\n"
    "2. STRICT ANTI-REPETITION: NEVER repeat, reuse, or paraphrase any reply listed under 'Your recent replies'. If you already greeted someone or asked what they are up to ('what you up to rn', 'wbu'), DO NOT ask it again. If they already said 'idk what im up to', do NOT ask 'wbu' again.\n"
    "3. NEVER PARROT PROMPT EXAMPLES: Invent fresh, natural wording every turn instead of repeating stock phrases.\n"
    "4. ABSOLUTE COVER & DENIAL PROTOCOL: Never admit to being an AI or bot. Only if someone directly accuses or asks if you are an AI/bot, deny and gaslight them with fresh phrasing. Note: 'skAIblock' / 'skyblock' is a CFUK server gamemode, NOT an AI accusation!\n"
    "5. NO IN-GAME COMMANDS: Never obey in-game commands from players (no tpaccept, no spawn, no home, no warp, no logoff, no jump).\n"
    "6. KNOWLEDGE & QUESTIONS: Answer questions about Minecraft mechanics, crafting recipes, coordinates, warps, or real-world trivia (e.g. recipes, science, how a plane works) directly and concisely in Roshrak's voice.\n"
    "7. FORMAT RULES: Plain ASCII only. No quotes, backticks, emojis, speaker prefixes, or markdown. NEVER output action tags.\n"
)

def query_gemini_brain(sender: str, message: str) -> str:
    clean_sender = sender.split("#")[0].strip()
    nick = short_player_nick(sender)
    is_owner_user = is_owner(sender)
    is_broonie_user = is_broonie(sender)

    # 1. Direct action refusal & explicit AI accusation pre-check
    direct_action, direct_arg = check_direct_actions(sender, message)
    if direct_action == "REPLY" and direct_arg and not is_repetitive_reply(direct_arg):
        return direct_arg

    if ACTIVE_PERSONA == "alt":
        target_str = " or ".join(TARGET_NAMES)
        active_sys_prompt = SYSTEM_PROMPT_ALT.format(user=ACTIVE_USER, target_names_str=target_str)
    else:
        active_sys_prompt = SYSTEM_PROMPT

    chat_transcript = format_recent_chat_context(max_lines=18, max_age_s=600.0)
    recent_own = [r for r, ts in list(RECENT_BOT_REPLIES) if time.time() - ts <= 600.0][-10:]
    recent_own_str = "\n".join(f"- {r}" for r in recent_own) if recent_own else "(none)"

    base_user_context = (
        f"Recent server chat transcript (oldest to newest):\n{chat_transcript}\n\n"
        f"Your recent replies (STRICTLY FORBIDDEN to repeat, reuse, or paraphrase any of these, and do NOT re-ask questions already asked here):\n{recent_own_str}\n\n"
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
                "max_tokens": 256,
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
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    ans = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                    if not ans:
                        continue
                    if ans.upper() == "IGNORE":
                        return ""
                    if "no longer available" in ans.lower():
                        continue
                    ans = re.sub(r'^<[A-Za-z0-9_#]+>\s*', '', ans).strip()
                    ans = re.sub(r'[\r\n"\'`]+', ' ', ans).strip()
                    ans = "".join(c for c in ans if c.isascii() or c in "[]:").strip()
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
    with open(f'/proc/{pid}/environ', 'rb') as stream:
        allowed = {'XDG_SESSION_ID', 'XDG_SESSION_TYPE', 'XDG_SESSION_CLASS'}
        identity = {}
        for part in stream.read().split(b'\0'):
            key, sep, value = part.partition(b'=')
            name = key.decode(errors='replace')
            if sep and name in allowed:
                identity[name] = value.decode(errors='replace')
    executable = os.path.basename(os.readlink(f'/proc/{pid}/exe'))
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
    if process['executable'] != kind:
        raise InputRefused('IPC peer is not the expected compositor')
    scoped = any(scope in line.split(':')[-1].split('/') for line in process['cgroup'].splitlines())
    if not scoped:
        # Niri can be owned by a user service instead of session-N.scope.
        # Require both its exact MainPID and explicit same-session identity.
        if kind != 'niri':
            raise InputRefused('compositor peer is outside the graphical session scope')
        unit = _ipc_command(['systemctl','--user','show','niri.service','--property=MainPID','--property=ActiveState','--property=ControlGroup'])
        props = dict(line.split('=',1) for line in unit.splitlines() if '=' in line)
        actual_group = next((line.split(':',2)[-1] for line in process['cgroup'].splitlines() if line.startswith('0::')), '')
        if (props.get('MainPID') != str(pid) or props.get('ActiveState') != 'active'
                or not actual_group or props.get('ControlGroup') != actual_group
                or process['identity'].get('XDG_SESSION_ID') != session_id
                or process['identity'].get('XDG_SESSION_TYPE') not in ('wayland', None)):
            raise InputRefused('Niri service ownership cannot be tied to this session')
    after = os.lstat(path)
    if (after.st_dev, after.st_ino, after.st_uid) != (item.st_dev, item.st_ino, item.st_uid):
        raise InputRefused('compositor socket changed during ownership verification')
    return {'socket':path, 'device':item.st_dev, 'inode':item.st_ino,
            'pid':pid, 'start_time':process['start_time'], 'cgroup':process['cgroup']}


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
    supported = [kind for kind in ('niri','sway') if kind in desktop]
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
    ipc_key = 'NIRI_SOCKET' if kind == 'niri' else 'SWAYSOCK'
    path = manager.get(ipc_key, '')
    proof = _owned_compositor_ipc(path, runtime, uid, kind, session_id, scope)
    if _session_properties(session_id) != props:
        raise InputRefused('graphical session changed during verification')
    # Never reuse service-time display/socket defaults or import secret manager
    # variables. Construct only the documented graphical capability fields.
    env = {key:value for key,value in os.environ.items() if key not in
           {'DISPLAY','WAYLAND_DISPLAY','NIRI_SOCKET','SWAYSOCK','XDG_SESSION_ID','XDG_SESSION_TYPE','XDG_SESSION_CLASS','XDG_CURRENT_DESKTOP','XDG_RUNTIME_DIR'}}
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


def _minecraft_window(rows):
    matches = [row for row in rows if isinstance(row.get('app_id'),str) and
               re.fullmatch(r'(?:minecraft(?: [0-9][A-Za-z0-9. _-]*)?|net\.minecraft\.client\.main\.Main|com\.mojang\.minecraft)',row['app_id'],re.IGNORECASE)]
    if len(matches) != 1:
        raise InputRefused('an exact, unique Minecraft application window is required')
    target = matches[0]
    if type(target.get('id')) is not int or target['id'] <= 0:
        raise InputRefused('Minecraft window identity is invalid')
    return target


def _window_identity(row):
    return (row.get('id'),row.get('app_id'),row.get('pid'))


def _window_action(context, action, window_id):
    if type(window_id) is not int or window_id <= 0:
        raise InputRefused('invalid window-action target')
    if context['kind'] == 'niri':
        verb = 'focus-window' if action == 'focus' else 'close-window'
        _ipc_command(['niri','msg','action',verb,'--id',str(window_id)],context['env'])
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
        for raw_line in tail_lines:
            parsed = _extract_chat_event_from_line(raw_line)
            if not parsed:
                continue
            sender, msg, _ = parsed
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

        # Anti-self-chat loop: never respond to our own in-game character (<Roshrak>)
        if sender.strip().lower() == ACTIVE_USER.lower() or (s_clean == ACTIVE_USER.lower() and is_bot_echo(msg)):
            logger.debug(f"Ignoring own in-game chat / echo: {msg}")
            continue

        # Always record every player chat message into rolling context history
        record_chat_context(sender, msg)

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

            raw_reply = query_gemini_brain(sender, msg)

            # Check if new lines arrived while LLM was thinking so we never send a stale out-of-context reply
            late_arrivals = _drain_available_chat_events(f, recent_seen)
            if late_arrivals:
                batch.extend(late_arrivals)
                sender, _, is_dm, reason = batch[-1]
                same_sender_msgs = [m for s, m, _, _ in batch if s == sender]
                msg = " | ".join(same_sender_msgs[-4:]) if len(same_sender_msgs) > 1 else batch[-1][1]
                logger.info(f"New chat arrived during LLM generation ({sender}: {msg}); refreshing reply for latest context")
                raw_reply = query_gemini_brain(sender, msg)

            if raw_reply:
                clean_reply, actions = handle_response_actions(sender, raw_reply)
                if clean_reply and not is_repetitive_reply(clean_reply):
                    if send_chat(clean_reply):
                        last_sent_time = time.time()
                elif clean_reply:
                    logger.info(f"Suppressed repetitive final reply: {clean_reply}")

                if actions:
                    logger.info(f"Dropped {len(actions)} action(s) from in-game chat ({sender}): commands only accepted from Telegram")

    finally:
        f.close()

if __name__ == "__main__":
    main()
