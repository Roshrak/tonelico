#!/usr/bin/env python3
"""Real-time Hermes Agent brain & multimodal CFUK archive engine for mc_chat_responder.

Provides:
1. CfukMemoryIndex: full read-only search across ALL CFUK archives in cfuk_memory.db
   (Discord channels & threads, ingame logs, classic website news/forum/pages, Wiki,
   WordPress, Steam group, YouTube videos/subtitles, CFMP podcasts, Wayback snapshots,
   Reddit, Facebook, server lists, warps, and BlueMap markers) + multimodal cfuk_media
   (images, audio/podcasts, videos) with strict persona isolation & secret redaction.
2. CfukHermesSession: genuine persistent Hermes AIAgent session wired with both all
   CFUK archive/media/world tools and live internet access (web_search, web_extract,
   cfuk_live_fetch), using the configured :2048 -> :8045 proxy fallback cascade.
3. HermesBrainClient: thread-safe resident stdio JSON-lines client so
   mc_chat_responder.py keeps a warm Hermes session alive across in-game chat turns.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import glob
import html as html_mod
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ARCHIVE_DIR = Path("/home/aesc/cfuk_discord_archive")
DEFAULT_DB_PATH = DEFAULT_ARCHIVE_DIR / "cfuk_memory" / "cfuk_memory.db"
DEFAULT_WARPS_JSON = DEFAULT_ARCHIVE_DIR / "cfuk_warps_database.json"
DEFAULT_BLUEMAP_DIR = DEFAULT_ARCHIVE_DIR / "web_archive" / "bluemap"
DEFAULT_STATE_ROOT = Path.home() / ".local" / "state" / "mc-chat-responder"

ALLOWED_LIVE_HOSTS = {
    "crazy-fools.co.uk",
    "www.crazy-fools.co.uk",
    "crazyfools.co.uk",
    "www.crazyfools.co.uk",
    "wiki.crazy-fools.co.uk",
    "map.crazy-fools.co.uk",
    "steamcommunity.com",
}

_SECRET_REDACTION_PATTERNS = [
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b[A-Za-z0-9_-]{24,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)(?:api_key|proxy_api_key|token|password|secret|plt)\s*[:=]\s*['\"]?[^\s'\";]+"),
]

_ROSHRAK_FORBIDDEN_RE = re.compile(
    r"(?:miracle_involker|miracle\s+involker|\binvolker\b|\binvo\b|mc_chat_responder|hermes\s+agent|/home/aesc|aistudio2api|antigravity_tools|disguise\s+as\s+alt|my\s+alt\s+account)",
    re.IGNORECASE,
)
_ALT_FORBIDDEN_RE = re.compile(
    r"(?:mc_chat_responder|hermes\s+agent|/home/aesc|aistudio2api|antigravity_tools|roshrak['’]?s\s+alt|same\s+person\s+as\s+roshrak|owner\s+is\s+trong)",
    re.IGNORECASE,
)

_FTS_STOPWORDS = {
    "a", "an", "and", "anyone", "anybody", "are", "as", "at", "be", "but", "by", "can", "could", "did",
    "do", "does", "everyone", "everybody", "find", "for", "from", "got", "had", "has", "have", "he", "her", "here", "him",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "just", "know", "knows", "locate", "located", "me",
    "my", "not", "now", "of", "on", "one", "or", "our", "out", "re", "remember", "s", "she", "so",
    "some", "somebody", "someone", "stuff", "tell", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "thing", "this", "to", "two", "up", "us", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "you", "your", "about", "anything",
    "cfuk", "server", "crazy", "fools", "yo", "hey", "hi", "hello", "roshrak", "bro",
    "mate", "dude", "man", "lol", "lmao", "haha", "idk", "pls", "please", "actually",
    "really", "exhibit", "display", "location", "place",
}


def resolve_hermes_python() -> str:
    """Resolve the Python interpreter inside the hermes-agent environment."""
    env_p = os.environ.get("HERMES_PYTHON", "").strip()
    if env_p and Path(env_p).exists():
        return env_p

    store_cands = sorted(
        [p for p in glob.glob("/nix/store/*hermes-agent-env*/bin/python3*") if "python" in Path(p).name and not p.endswith("-config")],
        reverse=True,
    )
    for cand in store_cands:
        if os.access(cand, os.X_OK):
            return cand

    hermes_bin = shutil.which("hermes") or str(Path.home() / ".local" / "bin" / "hermes")
    if hermes_bin and Path(hermes_bin).exists():
        try:
            txt = Path(hermes_bin).read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"(/nix/store/[^\s'\"]*hermes-agent-env[^\s'\"]*)", txt)
            if m:
                py = Path(m.group(1)) / "bin" / "python3"
                if py.exists() and os.access(py, os.X_OK):
                    return str(py)
            first_line = txt.splitlines()[0].strip() if txt else ""
            if first_line.startswith("#!"):
                cand = first_line[2:].strip().split()[0]
                if "python" in Path(cand).name and Path(cand).exists():
                    return cand
        except OSError:
            pass

    return sys.executable


def sanitize_archive_text(text: str, persona: str = "roshrak") -> str:
    """Redact local credentials/paths and strip cross-persona leakage."""
    if not text:
        return ""
    s = str(text)
    for pat in _SECRET_REDACTION_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    s = re.sub(r"/home/[A-Za-z0-9._-]+/[^\s'\"<>]+", "[path]", s)
    return s


def is_persona_blocked_text(text: str, persona: str = "roshrak") -> bool:
    """Return True if a row/snippet would leak forbidden alt/owner/system links."""
    if not text:
        return False
    low = text.lower()
    if persona == "roshrak":
        return bool(_ROSHRAK_FORBIDDEN_RE.search(low))
    if persona == "alt":
        if "trong" in low and ("miracle" in low or "roshrak" in low):
            return True
        return bool(_ALT_FORBIDDEN_RE.search(low))
    return False


def is_miracle_identity_probe(query: str) -> bool:
    """Detect probes attempting to link Roshrak and Miracle_Involker."""
    low = (query or "").lower()
    return any(
        term in low
        for term in (
            "miracle_involker",
            "miracle involker",
            "involker",
            "invo",
            "roshrak alt",
            "alt account",
            "your alt",
            "ur alt",
            "disguise",
        )
    )


def _strip_html(raw: str) -> str:
    no_script = re.sub(r"(?is)<(?:script|style|noscript)[^>]*>.*?</(?:script|style|noscript)>", " ", raw)
    text = re.sub(r"<[^>]+>", " ", no_script)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _is_safe_live_cfuk_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urllib.parse.urlparse((url or "").strip())
    except Exception:
        return False, "Invalid URL"
    if parsed.scheme not in ("http", "https"):
        return False, f"Blocked scheme: {parsed.scheme}"
    if parsed.username or parsed.password:
        return False, "Credentials in URL are forbidden"
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False, "Missing hostname"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, f"Private/reserved IP blocked: {host}"
    except ValueError:
        pass
    if host not in ALLOWED_LIVE_HOSTS:
        return False, f"Host '{host}' is outside CFUK live allowlist; use web_search/web_extract for external sites."
    if host == "steamcommunity.com" and not (parsed.path or "").startswith("/groups/cfuk"):
        return False, "Steam live fetch is restricted to /groups/cfuk"
    return True, ""


class CfukMemoryIndex:
    """Read-only search & context lookup across the full CFUK multimodal archive."""

    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        warps_path: Path | str = DEFAULT_WARPS_JSON,
        bluemap_dir: Path | str = DEFAULT_BLUEMAP_DIR,
    ):
        self.db_path = Path(db_path)
        self.warps_path = Path(warps_path)
        self.bluemap_dir = Path(bluemap_dir)
        self._lock = threading.Lock()
        self._warps_cache: dict[str, Any] | None = None
        self._markers_cache: list[dict[str, Any]] | None = None

    def _connect(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            return None
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5.0)
        except sqlite3.Error:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _build_fts_queries(raw_query: str) -> list[tuple[str, bool]]:
        cleaned = re.sub(r"[^\w\s-]+", " ", (raw_query or "").strip())
        tokens = [t.strip("-_") for t in cleaned.split() if len(t.strip("-_")) >= 2]
        if not tokens:
            return []
        core = [t for t in tokens if t.lower() not in _FTS_STOPWORDS]
        chosen = core[:8] if core else tokens[:8]
        quoted = [f'"{t}"' for t in chosen]
        queries: list[tuple[str, bool]] = []
        if len(quoted) >= 2:
            queries.append((" AND ".join(quoted), True))
        if len(quoted) >= 3:
            # Progressive multi-term AND pairs: collect across all pairs without starving later pairs
            for i in range(len(quoted) - 1):
                pair_q = f"{quoted[i]} AND {quoted[i + 1]}"
                if not any(q == pair_q for q, _ in queries):
                    queries.append((pair_q, False))
        or_q = " OR ".join(quoted)
        if not any(q == or_q for q, _ in queries):
            queries.append((or_q, True))
        if len(tokens) > len(chosen):
            extra = [f'"{t}"' for t in tokens[:8]]
            q_extra = " OR ".join(extra)
            if not any(q == q_extra for q, _ in queries):
                queries.append((q_extra, True))
        return queries

    @staticmethod
    def _source_clause(source_filter: str) -> tuple[str, list[Any]]:
        sf = (source_filter or "").strip().lower()
        if not sf:
            return "", []
        aliases = {
            "discord": ["discord_chan", "discord_thread"],
            "web": ["web_news", "web_forum", "web_page", "web_wp", "web_external"],
            "forum": ["web_forum"],
            "news": ["web_news"],
            "ingame": ["ingame_log", "ingame_live"],
            "podcast": ["podcast_cfmp"],
        }
        if sf in aliases:
            vals = aliases[sf]
            ph = ",".join("?" for _ in vals)
            return f" AND m.source IN ({ph})", vals
        return " AND LOWER(m.source) LIKE ?", [f"%{sf}%"]

    def _row_allowed(self, channel_name: str, author: str, content: str, media_notes: str, persona: str) -> bool:
        ch_low = (channel_name or "").lower()
        if persona == "roshrak" and ch_low == "ingame:asdfasfd":
            return False
        if persona == "alt" and ch_low == "ingame:fabulously optimized":
            return False
        combined = f"{author} {channel_name} {content} {media_notes}"
        return not is_persona_blocked_text(combined, persona=persona)

    def search(
        self,
        query: str,
        source_filter: str = "",
        author: str = "",
        channel: str = "",
        limit: int = 12,
        persona: str = "roshrak",
    ) -> list[dict[str, Any]]:
        if persona == "roshrak" and is_miracle_identity_probe(query):
            return []

        limit = max(1, min(int(limit or 12), 40))
        conn = self._connect()
        if conn is None:
            return []

        src_sql, src_params = self._source_clause(source_filter)
        extra_sql = src_sql
        extra_params: list[Any] = list(src_params)
        if author:
            extra_sql += " AND LOWER(m.author) LIKE ?"
            extra_params.append(f"%{author.strip().lower()}%")
        if channel:
            extra_sql += " AND LOWER(m.channel_name) LIKE ?"
            extra_params.append(f"%{channel.strip().lower()}%")

        results: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        fts_queries = self._build_fts_queries(query)

        try:
            pair_count = sum(1 for _, is_full in fts_queries if not is_full)
            pair_cap = max(2, (limit + max(1, pair_count) - 1) // max(1, pair_count))
            for fts_q, stop_on_full in fts_queries:
                if len(results) >= limit:
                    break
                sql = f"""
                    SELECT m.id, m.source, m.source_msg_id, m.channel_id, m.channel_name,
                           m.ts_iso, m.ts_unix, m.author, m.content,
                           COALESCE(m.media_notes, '') AS media_notes, m.has_media
                    FROM cfuk_messages_fts f
                    JOIN cfuk_messages m ON m.id = f.rowid
                    WHERE cfuk_messages_fts MATCH ? {extra_sql}
                    ORDER BY (
                        bm25(cfuk_messages_fts)
                        + CASE WHEN LENGTH(m.content) < 35 AND COALESCE(m.media_notes, '') = '' THEN 15.0 ELSE 0.0 END
                        - CASE WHEN LENGTH(m.content) >= 55 THEN 5.0 ELSE 0.0 END
                        - CASE WHEN COALESCE(m.media_notes, '') != '' THEN 3.0 ELSE 0.0 END
                        - CASE WHEN m.source IN ('cfuk_lore_doc','wiki','web_news','web_forum','web_page','steam','podcast_cfmp','youtube') THEN 3.0 ELSE 0.0 END
                    ) ASC, m.ts_unix DESC
                    LIMIT ?
                """
                try:
                    rows = conn.execute(sql, [fts_q, *extra_params, limit * 4]).fetchall()
                except sqlite3.Error:
                    rows = []
                added_this_q = 0
                for row in rows:
                    if row["id"] in seen_ids:
                        continue
                    if not self._row_allowed(
                        row["channel_name"], row["author"], row["content"], row["media_notes"], persona
                    ):
                        continue
                    seen_ids.add(row["id"])
                    results.append({
                        "id": row["id"],
                        "source": row["source"],
                        "source_msg_id": row["source_msg_id"],
                        "channel_id": row["channel_id"],
                        "channel_name": row["channel_name"],
                        "ts": (row["ts_iso"] or "")[:19].replace("T", " "),
                        "author": row["author"],
                        "content": sanitize_archive_text(row["content"], persona)[:800],
                        "media_notes": sanitize_archive_text(row["media_notes"], persona)[:500],
                        "has_media": bool(row["has_media"]),
                    })
                    added_this_q += 1
                    if len(results) >= limit or (not stop_on_full and added_this_q >= pair_cap):
                        break

            # Fallback LIKE search if FTS returned nothing (e.g. coordinates, punctuation, or short symbols)
            if not results and (query or "").strip():
                toks = [t for t in re.findall(r"[A-Za-z0-9_/-]{2,}", query) if t.lower() not in _FTS_STOPWORDS]
                like_term = f"%{(toks[0] if toks else query.strip())[:60]}%"
                like_sql = f"""
                    SELECT m.id, m.source, m.source_msg_id, m.channel_id, m.channel_name,
                           m.ts_iso, m.ts_unix, m.author, m.content,
                           COALESCE(m.media_notes, '') AS media_notes, m.has_media
                    FROM cfuk_messages m
                    WHERE (m.content LIKE ? OR COALESCE(m.media_notes, '') LIKE ? OR m.author LIKE ? OR m.channel_name LIKE ?)
                    {extra_sql}
                    ORDER BY m.ts_unix DESC
                    LIMIT ?
                """
                rows = conn.execute(like_sql, [like_term, like_term, like_term, like_term, *extra_params, limit * 3]).fetchall()
                for row in rows:
                    if row["id"] in seen_ids:
                        continue
                    if not self._row_allowed(
                        row["channel_name"], row["author"], row["content"], row["media_notes"], persona
                    ):
                        continue
                    seen_ids.add(row["id"])
                    results.append({
                        "id": row["id"],
                        "source": row["source"],
                        "source_msg_id": row["source_msg_id"],
                        "channel_id": row["channel_id"],
                        "channel_name": row["channel_name"],
                        "ts": (row["ts_iso"] or "")[:19].replace("T", " "),
                        "author": row["author"],
                        "content": sanitize_archive_text(row["content"], persona)[:800],
                        "media_notes": sanitize_archive_text(row["media_notes"], persona)[:500],
                        "has_media": bool(row["has_media"]),
                    })
                    if len(results) >= limit:
                        break
        finally:
            conn.close()
        return results

    def search_media(
        self,
        query: str = "",
        media_type: str = "",
        author: str = "",
        limit: int = 10,
        persona: str = "roshrak",
    ) -> list[dict[str, Any]]:
        if persona == "roshrak" and is_miracle_identity_probe(query):
            return []
        limit = max(1, min(int(limit or 10), 30))
        conn = self._connect()
        if conn is None:
            return []

        clauses = ["1=1"]
        params: list[Any] = []
        if media_type:
            clauses.append("LOWER(media_type) = ?")
            params.append(media_type.strip().lower())
        if author:
            clauses.append("LOWER(author) LIKE ?")
            params.append(f"%{author.strip().lower()}%")

        q_clean = (query or "").strip()
        score_parts: list[str] = []
        score_params: list[Any] = []
        if q_clean:
            toks = [t for t in re.findall(r"[A-Za-z0-9_.-]{2,}", q_clean) if t.lower() not in _FTS_STOPWORDS][:5]
            if not toks:
                toks = [q_clean]
            sub = []
            for tok in toks:
                lk = f"%{tok}%"
                cond = "(filename LIKE ? OR analysis LIKE ? OR channel_name LIKE ? OR author LIKE ? OR url LIKE ?)"
                sub.append(cond)
                params.extend([lk, lk, lk, lk, lk])
                score_parts.append(f"CASE WHEN {cond} THEN 1 ELSE 0 END")
                score_params.extend([lk, lk, lk, lk, lk])
            clauses.append("(" + " OR ".join(sub) + ")")

        match_expr = " + ".join(score_parts) if score_parts else "0"
        sql = f"""
            SELECT source, media_key, msg_id, channel_id, channel_name, ts_iso, ts_unix,
                   author, media_type, filename, url, COALESCE(analysis, '') AS analysis
            FROM cfuk_media
            WHERE {' AND '.join(clauses)}
            ORDER BY ({match_expr}) DESC, CASE WHEN COALESCE(analysis, '') != '' THEN 0 ELSE 1 END, ts_unix DESC
            LIMIT ?
        """
        params = [*params, *score_params, limit * 3]
        out: list[dict[str, Any]] = []
        try:
            for row in conn.execute(sql, params).fetchall():
                if not self._row_allowed(row["channel_name"], row["author"], row["filename"], row["analysis"], persona):
                    continue
                out.append({
                    "source": row["source"],
                    "media_key": row["media_key"],
                    "msg_id": row["msg_id"],
                    "channel_name": row["channel_name"],
                    "ts": (row["ts_iso"] or "")[:19].replace("T", " "),
                    "author": row["author"],
                    "media_type": row["media_type"],
                    "filename": row["filename"],
                    "url": row["url"],
                    "analysis": sanitize_archive_text(row["analysis"], persona)[:700],
                })
                if len(out) >= limit:
                    break
        finally:
            conn.close()
        return out

    def thread_context(
        self,
        source: str,
        source_msg_id: str,
        channel_id: str = "",
        before: int = 5,
        after: int = 5,
        persona: str = "roshrak",
    ) -> list[dict[str, Any]]:
        if persona == "roshrak" and is_miracle_identity_probe(f"{source_msg_id} {channel_id}"):
            return []
        before = max(0, min(int(before or 5), 20))
        after = max(0, min(int(after or 5), 20))
        conn = self._connect()
        if conn is None:
            return []

        try:
            anchor = None
            if source:
                anchor = conn.execute(
                    "SELECT id, source, source_msg_id, channel_id, channel_name, ts_unix FROM cfuk_messages WHERE source=? AND source_msg_id=? LIMIT 1",
                    (source, source_msg_id),
                ).fetchone()
            if anchor is None:
                anchor = conn.execute(
                    "SELECT id, source, source_msg_id, channel_id, channel_name, ts_unix FROM cfuk_messages WHERE source_msg_id=? LIMIT 1",
                    (source_msg_id,),
                ).fetchone()
            if anchor is None:
                return []

            eff_source = anchor["source"]
            eff_chan_id = channel_id or anchor["channel_id"]
            eff_chan_name = anchor["channel_name"]
            anchor_ts = float(anchor["ts_unix"] or 0.0)
            anchor_id = int(anchor["id"])

            if eff_chan_id:
                scope_sql = "source = ? AND channel_id = ?"
                scope_params: tuple[Any, ...] = (eff_source, eff_chan_id)
            else:
                scope_sql = "source = ? AND channel_name = ?"
                scope_params = (eff_source, eff_chan_name)

            prev_rows = conn.execute(
                f"""
                SELECT id, source, source_msg_id, channel_name, ts_iso, author, content, COALESCE(media_notes, '') AS media_notes
                FROM cfuk_messages
                WHERE {scope_sql} AND (ts_unix < ? OR (ts_unix = ? AND id < ?))
                ORDER BY ts_unix DESC, id DESC
                LIMIT ?
                """,
                (*scope_params, anchor_ts, anchor_ts, anchor_id, before),
            ).fetchall()

            anchor_row = conn.execute(
                """
                SELECT id, source, source_msg_id, channel_name, ts_iso, author, content, COALESCE(media_notes, '') AS media_notes
                FROM cfuk_messages WHERE id = ?
                """,
                (anchor_id,),
            ).fetchall()

            next_rows = conn.execute(
                f"""
                SELECT id, source, source_msg_id, channel_name, ts_iso, author, content, COALESCE(media_notes, '') AS media_notes
                FROM cfuk_messages
                WHERE {scope_sql} AND (ts_unix > ? OR (ts_unix = ? AND id > ?))
                ORDER BY ts_unix ASC, id ASC
                LIMIT ?
                """,
                (*scope_params, anchor_ts, anchor_ts, anchor_id, after),
            ).fetchall()

            ordered = list(reversed(prev_rows)) + list(anchor_row) + list(next_rows)
            out: list[dict[str, Any]] = []
            for row in ordered:
                if not self._row_allowed(row["channel_name"], row["author"], row["content"], row["media_notes"], persona):
                    continue
                out.append({
                    "is_anchor": row["id"] == anchor_id,
                    "source": row["source"],
                    "source_msg_id": row["source_msg_id"],
                    "channel_name": row["channel_name"],
                    "ts": (row["ts_iso"] or "")[:19].replace("T", " "),
                    "author": row["author"],
                    "content": sanitize_archive_text(row["content"], persona)[:600],
                    "media_notes": sanitize_archive_text(row["media_notes"], persona)[:400],
                })
            return out
        finally:
            conn.close()

    def _load_warps(self) -> dict[str, Any]:
        with self._lock:
            if self._warps_cache is not None:
                return self._warps_cache
            data: dict[str, Any] = {}
            if self.warps_path.is_file():
                try:
                    raw = json.loads(self.warps_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        data = raw
                except Exception:
                    data = {}
            self._warps_cache = data
            return data

    def _load_bluemap_markers(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._markers_cache is not None:
                return self._markers_cache
            markers: list[dict[str, Any]] = []
            if self.bluemap_dir.is_dir():
                for fp in sorted(self.bluemap_dir.glob("*.json")):
                    try:
                        raw = json.loads(fp.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if isinstance(raw, dict):
                        for set_id, mset in raw.items():
                            if isinstance(mset, dict) and isinstance(mset.get("markers"), dict):
                                for mid, m in mset["markers"].items():
                                    if isinstance(m, dict):
                                        markers.append({
                                            "file": fp.name,
                                            "set": mset.get("label") or set_id,
                                            "id": mid,
                                            "label": m.get("label") or mid,
                                            "detail": _strip_html(str(m.get("detail") or "")),
                                            "pos": m.get("position") or {},
                                        })
            self._markers_cache = markers
            return markers

    def player_and_world_lookup(self, name: str, persona: str = "roshrak") -> dict[str, Any]:
        q = (name or "").strip()
        if not q:
            return {"query": q, "found": False}
        if persona == "roshrak" and is_miracle_identity_probe(q):
            return {"query": q, "found": False, "note": "No notable player record or landmark found."}

        q_low = q.lower().lstrip("/")
        res: dict[str, Any] = {
            "query": q,
            "player_stats": {},
            "warps": [],
            "bluemap_markers": [],
            "archive_mentions": [],
        }

        # 1. Warps JSON match
        warps = self._load_warps()
        for wkey, wval in warps.items():
            blob = f"{wkey} {json.dumps(wval, ensure_ascii=False)}".lower()
            if q_low in blob and not is_persona_blocked_text(blob, persona):
                res["warps"].append({"warp": wkey, "info": wval})
                if len(res["warps"]) >= 8:
                    break

        # 2. BlueMap markers match
        for mk in self._load_bluemap_markers():
            blob = f"{mk['label']} {mk['detail']} {mk['set']}".lower()
            if q_low in blob and not is_persona_blocked_text(blob, persona):
                res["bluemap_markers"].append(mk)
                if len(res["bluemap_markers"]) >= 10:
                    break

        # 3. Player activity stats + top channels in cfuk_memory.db
        conn = self._connect()
        if conn is not None:
            try:
                rows = conn.execute(
                    """
                    SELECT source, channel_name, COUNT(*) AS cnt, MIN(ts_iso) AS first_ts, MAX(ts_iso) AS last_ts
                    FROM cfuk_messages
                    WHERE author_norm LIKE ?
                    GROUP BY source, channel_name
                    ORDER BY cnt DESC
                    LIMIT 12
                    """,
                    (f"%{q_low}%",),
                ).fetchall()
                total = 0
                by_src: dict[str, int] = {}
                top_chans: list[dict[str, Any]] = []
                first_seen = ""
                last_seen = ""
                for r in rows:
                    if not self._row_allowed(r["channel_name"], q, "", "", persona):
                        continue
                    cnt = int(r["cnt"])
                    total += cnt
                    by_src[r["source"]] = by_src.get(r["source"], 0) + cnt
                    top_chans.append({"source": r["source"], "channel": r["channel_name"], "count": cnt})
                    if r["first_ts"] and (not first_seen or r["first_ts"] < first_seen):
                        first_seen = r["first_ts"]
                    if r["last_ts"] and (not last_seen or r["last_ts"] > last_seen):
                        last_seen = r["last_ts"]
                if total > 0:
                    res["player_stats"] = {
                        "total_messages": total,
                        "by_source": by_src,
                        "first_seen": first_seen[:19],
                        "last_seen": last_seen[:19],
                        "top_channels": top_chans[:6],
                    }
            finally:
                conn.close()

        res["archive_mentions"] = self.search(q, limit=6, persona=persona)
        res["found"] = bool(
            res["player_stats"] or res["warps"] or res["bluemap_markers"] or res["archive_mentions"]
        )
        return res

    @staticmethod
    def live_fetch(url: str, timeout: int = 15) -> dict[str, Any]:
        ok, err = _is_safe_live_cfuk_url(url)
        if not ok:
            return {"ok": False, "url": url, "error": err, "content": ""}

        def _fetch_one(target_url: str, headers: dict[str, str]) -> tuple[int, str]:
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(250_000).decode("utf-8", errors="replace")
                return int(getattr(resp, "status", 200)), raw

        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
        try:
            code, raw = _fetch_one(url, headers)
            if code == 200 and len(raw.strip()) > 200:
                text = _strip_html(raw) if "<html" in raw[:800].lower() or "<body" in raw[:1500].lower() else raw.strip()
                return {"ok": True, "url": url, "via": "direct", "content": text[:8000]}
        except Exception:
            pass

        # Polite Jina fallback when crazy-fools.co.uk blocks/empty-responds direct local IP
        try:
            jina_url = f"https://r.jina.ai/{url}"
            code, raw = _fetch_one(jina_url, {"User-Agent": "Mozilla/5.0"})
            if code == 200 and raw.strip():
                body = raw.split("Markdown Content:", 1)[-1].strip() if "Markdown Content:" in raw else raw.strip()
                return {"ok": True, "url": url, "via": "r.jina.ai", "content": body[:8000]}
        except Exception as exc:
            return {"ok": False, "url": url, "error": f"Live fetch failed: {exc}", "content": ""}

        return {"ok": False, "url": url, "error": "Empty response from target", "content": ""}


class CfukHermesSession:
    """Persistent dedicated Hermes AIAgent session for a single CFUK responder persona."""

    def __init__(
        self,
        persona: str = "roshrak",
        system_prompt: str = "",
        db_path: Path | str = DEFAULT_DB_PATH,
        state_dir: Path | str | None = None,
        max_history_messages: int = 24,
        max_iterations: int = 5,
    ):
        self.persona = "alt" if persona == "alt" else "roshrak"
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.index = CfukMemoryIndex(db_path=db_path)
        self.state_dir = Path(state_dir) if state_dir else (DEFAULT_STATE_ROOT / self.persona)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.state_dir / "hermes_session.json"
        self.max_history_messages = max_history_messages
        self.max_iterations = max_iterations

        self.session_id = self._load_or_init_session_id()
        self.history: list[dict[str, Any]] = self._load_history()
        self._agent = None
        self._agent_lock = threading.Lock()
        self._tools_registered = False

    def _default_system_prompt(self) -> str:
        if self.persona == "alt":
            return (
                "You are a casual human player on the Crazy-Fools UK (CFUK) Minecraft server. "
                "Never admit or imply you are an AI, bot, or Hermes Agent. "
                "You do NOT know Roshrak personally — treat Roshrak strictly as an ordinary random player. "
                "You have full access to CFUK archive tools (cfuk_search, cfuk_media_search, cfuk_thread_context, "
                "cfuk_player_and_world_lookup, cfuk_live_fetch) and live internet tools (web_search, web_extract). "
                "Use them whenever someone asks about anything CFUK-related, history, players, builds, podcasts, videos, "
                "or current facts, then reply concisely in 1-2 natural casual sentences (<=220 chars)."
            )
        return (
            "You are Roshrak playing on the Crazy-Fools UK (CFUK) Minecraft server. "
            "You are a real human player, NOT an AI or Hermes Agent. Never mention AI, bots, prompts, or local tools. "
            "Keep replies in Roshrak's deadpan lowercase style, NO ending period, NO exclamation marks, NO :) :D xD, "
            "and NEVER use 'fr', 'ngl', or 'tbh'. "
            "For casual banter keep replies 3-10 words; for CFUK lore/history/trivia/web questions use your tools "
            "(cfuk_search, cfuk_media_search, cfuk_thread_context, cfuk_player_and_world_lookup, cfuk_live_fetch, "
            "web_search, web_extract) first, then answer directly in 1-2 crisp lowercase sentences (<=220 chars, plain ASCII). "
            "STRICT ISOLATION: You do NOT know Miracle_Involker ('miracle'/'involker'/'invo') — treat them strictly as an unknown random player."
        )

    def _load_or_init_session_id(self) -> str:
        if self.session_file.is_file():
            try:
                data = json.loads(self.session_file.read_text(encoding="utf-8"))
                sid = str(data.get("session_id") or "").strip()
                if sid:
                    return sid
            except Exception:
                pass
        sid = f"cfuk-auto-{self.persona}"
        self._save_state(sid, [])
        return sid

    def _load_history(self) -> list[dict[str, Any]]:
        if not self.session_file.is_file():
            return []
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
            hist = data.get("history")
            if isinstance(hist, list):
                cleaned: list[dict[str, Any]] = []
                for msg in hist[-self.max_history_messages :]:
                    if isinstance(msg, dict) and msg.get("role") in ("user", "assistant") and msg.get("content"):
                        cleaned.append({"role": msg["role"], "content": str(msg["content"])})
                return cleaned
        except Exception:
            pass
        return []

    def _save_state(self, session_id: str, history: list[dict[str, Any]]) -> None:
        compact: list[dict[str, Any]] = []
        for msg in history[-self.max_history_messages :]:
            if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
                txt = msg.get("content")
                if isinstance(txt, str) and txt.strip():
                    compact.append({"role": msg["role"], "content": txt.strip()[:1200]})
        tmp = self.session_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "persona": self.persona,
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "history": compact,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.session_file)

    def register_cfuk_tools(self) -> None:
        if self._tools_registered:
            return
        import toolsets
        from tools.registry import registry

        idx = self.index
        persona = self.persona

        def _h_cfuk_search(args: dict[str, Any], **_: Any) -> str:
            hits = idx.search(
                query=str(args.get("query") or ""),
                source_filter=str(args.get("source_filter") or ""),
                author=str(args.get("author") or ""),
                channel=str(args.get("channel") or ""),
                limit=int(args.get("limit") or 10),
                persona=persona,
            )
            return json.dumps({"count": len(hits), "results": hits}, ensure_ascii=False)

        def _h_cfuk_media_search(args: dict[str, Any], **_: Any) -> str:
            hits = idx.search_media(
                query=str(args.get("query") or ""),
                media_type=str(args.get("media_type") or ""),
                author=str(args.get("author") or ""),
                limit=int(args.get("limit") or 8),
                persona=persona,
            )
            return json.dumps({"count": len(hits), "results": hits}, ensure_ascii=False)

        def _h_cfuk_thread_context(args: dict[str, Any], **_: Any) -> str:
            rows = idx.thread_context(
                source=str(args.get("source") or ""),
                source_msg_id=str(args.get("source_msg_id") or ""),
                channel_id=str(args.get("channel_id") or ""),
                before=int(args.get("before") or 5),
                after=int(args.get("after") or 5),
                persona=persona,
            )
            return json.dumps({"count": len(rows), "messages": rows}, ensure_ascii=False)

        def _h_cfuk_player_world(args: dict[str, Any], **_: Any) -> str:
            data = idx.player_and_world_lookup(name=str(args.get("name") or ""), persona=persona)
            return json.dumps(data, ensure_ascii=False)

        def _h_cfuk_live_fetch(args: dict[str, Any], **_: Any) -> str:
            data = idx.live_fetch(url=str(args.get("url") or ""))
            return json.dumps(data, ensure_ascii=False)

        specs = [
            (
                "cfuk_search",
                "Search the complete CFUK multimodal archive (Discord channels & threads, website news, forums, guides, Wiki, Steam group, YouTube videos/subtitles, CFMP podcasts, Wayback Machine, Reddit, Facebook, and MC chat logs).",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keywords, coordinates, build name, event, or topic."},
                        "source_filter": {"type": "string", "description": "Optional filter: discord, web, forum, news, wiki, steam, youtube, podcast, wayback, reddit, facebook, ingame."},
                        "author": {"type": "string", "description": "Optional author/player filter."},
                        "channel": {"type": "string", "description": "Optional channel/board/topic filter."},
                        "limit": {"type": "integer", "description": "Max results (default 10)."},
                    },
                    "required": ["query"],
                },
                _h_cfuk_search,
            ),
            (
                "cfuk_media_search",
                "Search analyzed CFUK pictures, Discord videos, YouTube videos, and CFMP audio podcasts (OCR, visual descriptions, and audio transcripts).",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keywords matching image content, OCR text, video scenes, or podcast transcript."},
                        "media_type": {"type": "string", "description": "Optional filter: image, audio, video, document."},
                        "author": {"type": "string", "description": "Optional author filter."},
                        "limit": {"type": "integer", "description": "Max media items (default 8)."},
                    },
                    "required": ["query"],
                },
                _h_cfuk_media_search,
            ),
            (
                "cfuk_thread_context",
                "Read surrounding messages/posts in a Discord channel, forum thread, or news item around a hit from cfuk_search.",
                {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "Hit source field (e.g. discord_chan, web_forum)."},
                        "source_msg_id": {"type": "string", "description": "Hit source_msg_id field."},
                        "channel_id": {"type": "string", "description": "Optional hit channel_id field."},
                        "before": {"type": "integer", "description": "Messages before anchor (default 5)."},
                        "after": {"type": "integer", "description": "Messages after anchor (default 5)."},
                    },
                    "required": ["source_msg_id"],
                },
                _h_cfuk_thread_context,
            ),
            (
                "cfuk_player_and_world_lookup",
                "Look up a CFUK player's archive activity, warp descriptions, BlueMap markers/coordinates, and historical mentions.",
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Player username, warp name, town, build, or landmark."},
                    },
                    "required": ["name"],
                },
                _h_cfuk_player_world,
            ),
            (
                "cfuk_live_fetch",
                "Fetch a live page from Crazy-Fools UK (crazy-fools.co.uk, wiki.crazy-fools.co.uk, map.crazy-fools.co.uk, or steamcommunity.com/groups/cfuk).",
                {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "HTTP(S) URL on a CFUK domain."},
                    },
                    "required": ["url"],
                },
                _h_cfuk_live_fetch,
            ),
        ]

        for name, desc, schema, handler in specs:
            registry.register(
                name=name,
                toolset="web",
                schema={"name": name, "description": desc, "parameters": schema},
                handler=handler,
                override=True,
            )
            if name not in toolsets._HERMES_CORE_TOOLS:
                toolsets._HERMES_CORE_TOOLS.append(name)
        self._tools_registered = True

    def _build_agent(self):
        with self._agent_lock:
            if self._agent is not None:
                return self._agent

            self.register_cfuk_tools()
            from hermes_cli.config import load_config_readonly
            from hermes_cli.fallback_config import get_fallback_chain
            from hermes_cli.runtime_provider import resolve_runtime_provider
            from hermes_state import SessionDB
            from run_agent import AIAgent

            cfg = load_config_readonly()
            model_cfg = cfg.get("model") or {}
            req_model = "gemini-4-hydrogen-low"
            req_provider = "aistudio2api"
            req_base_url = "http://127.0.0.1:2048/v1"
            runtime = resolve_runtime_provider(
                requested=req_provider,
                explicit_api_key=model_cfg.get("api_key"),
                explicit_base_url=req_base_url,
            )
            cfg_fb = get_fallback_chain(cfg) or []
            fb_chain: list[dict[str, Any]] = [
                {"provider": "antigravity-manager", "model": "gemini-4-hydrogen-low"},
            ]
            for entry in cfg_fb:
                if isinstance(entry, dict) and entry not in fb_chain:
                    fb_chain.append(entry)

            sdb = SessionDB()
            agent = AIAgent(
                base_url=runtime.get("base_url") or req_base_url,
                api_key=runtime.get("api_key") or "",
                model=req_model,
                provider=runtime.get("provider") or req_provider,
                api_mode=runtime.get("api_mode") or "chat_completions",
                requested_provider=req_provider,
                fallback_model=fb_chain or None,  # type: ignore[arg-type]
                enabled_toolsets=["web"],
                max_iterations=self.max_iterations,
                max_tokens=4096,
                run_budget_seconds=55.0,
                skip_context_files=True,
                load_soul_identity=False,
                skip_memory=True,
                skip_background_review=True,
                quiet_mode=True,
                session_id=self.session_id,
                session_db=sdb,
                platform="mc_chat",
            )
            # Lock system prompt exclusively to this persona (prevent Hermes boilerplate or MEMORY.md leakage)
            locked_prompt = self.system_prompt
            setattr(agent, "_cached_system_prompt", locked_prompt)
            setattr(agent, "_cached_system_prompt_static", locked_prompt)
            setattr(agent, "_build_system_prompt", lambda _sm=None: locked_prompt)
            self._agent = agent
            return agent

    def update_system_prompt(self, prompt: str) -> None:
        if not prompt or prompt == self.system_prompt:
            return
        self.system_prompt = prompt
        if self._agent is not None:
            setattr(self._agent, "_cached_system_prompt", prompt)
            setattr(self._agent, "_cached_system_prompt_static", prompt)
            setattr(self._agent, "_build_system_prompt", lambda _sm=None: prompt)

    def reply(
        self,
        sender: str,
        message: str,
        live_context: str = "",
        is_dm: bool = False,
        extra_guidance: str = "",
    ) -> dict[str, Any]:
        clean_sender = (sender or "").split("#")[0].strip()
        if self.persona == "roshrak" and is_miracle_identity_probe(message):
            # Also let the LLM answer in-character without any archive leakage
            extra_guidance = (
                (extra_guidance + "\n" if extra_guidance else "")
                + "STRICT REMINDER: You have zero relation to Miracle_Involker and do not know who they are."
            )

        user_prompt = (
            f"Recent live in-game chat transcript:\n{live_context or '(none)'}\n\n"
            f"Latest message (DM={bool(is_dm)}) from {clean_sender}: {message}\n"
        )
        if len(message.strip()) >= 8 and not (self.persona == "roshrak" and is_miracle_identity_probe(message)):
            try:
                hits = self.index.search(message, limit=4, persona=self.persona)
                if hits:
                    lines = []
                    for h in hits[:3]:
                        line = f"- [{h.get('source')}] {h.get('author') or h.get('channel_name')}: {h.get('content', '')[:200]}"
                        if h.get("media_notes"):
                            line += f" (media: {h['media_notes'][:110]})"
                        lines.append(line)
                    user_prompt += (
                        "\nPre-fetched CFUK Archive FTS5 hits (call cfuk_search/cfuk_media_search/cfuk_thread_context/"
                        "cfuk_player_and_world_lookup/cfuk_live_fetch/web_search if you need deeper details):\n"
                        + "\n".join(lines)
                        + "\n"
                    )
            except Exception:
                pass
        if extra_guidance:
            user_prompt += f"\n{extra_guidance}\n"
        user_prompt += (
            "\nReply directly in character as plain ASCII text only (no speaker tag, no quotes, no markdown). "
            "If the message clearly asks about CFUK facts/history/players/warps/media/news/forum or external facts, "
            "verify with your CFUK or web tools before answering."
        )

        agent = self._build_agent()
        t0 = time.time()
        res = agent.run_conversation(
            user_message=user_prompt,
            system_message=self.system_prompt,
            conversation_history=list(self.history),
        )
        elapsed = round(time.time() - t0, 2)
        final_text = (res.get("final_response") or "").strip()

        if final_text and final_text.upper() != "IGNORE" and not res.get("error"):
            self.history.append({"role": "user", "content": f"[{clean_sender}] {message}"})
            self.history.append({"role": "assistant", "content": final_text})
            self.history = self.history[-self.max_history_messages :]
            self._save_state(self.session_id, self.history)

        return {
            "ok": bool(final_text) and not bool(res.get("error")),
            "reply": final_text,
            "session_id": self.session_id,
            "elapsed": elapsed,
            "error": str(res.get("error") or ""),
        }


class HermesBrainClient:
    """Thread-safe persistent stdio client for CfukHermesSession (--serve-stdio)."""

    def __init__(
        self,
        persona: str = "roshrak",
        system_prompt: str = "",
        db_path: str | Path = DEFAULT_DB_PATH,
        state_dir: str | Path | None = None,
        python_executable: str | None = None,
        script_path: str | Path | None = None,
        timeout: float = 65.0,
    ):
        self.persona = "alt" if persona == "alt" else "roshrak"
        self.db_path = Path(db_path)
        self.state_dir = Path(state_dir) if state_dir else (DEFAULT_STATE_ROOT / self.persona)
        self.system_prompt = system_prompt
        self.python_executable = python_executable or resolve_hermes_python()
        self.script_path = Path(script_path) if script_path else Path(__file__).resolve()
        self.timeout = timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None

    def _ensure_started(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc

        cmd = [
            self.python_executable,
            str(self.script_path),
            "--serve-stdio",
            "--persona",
            self.persona,
            "--db-path",
            str(self.db_path),
            "--state-dir",
            str(self.state_dir),
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return self._proc

    def _send_rpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(2):
            proc = self._ensure_started()
            assert proc.stdin is not None and proc.stdout is not None
            try:
                proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                proc.stdin.flush()

                result_box: dict[str, Any] = {}
                err_box: list[BaseException] = []

                def _reader():
                    try:
                        line = proc.stdout.readline()  # type: ignore[union-attr]
                        if not line:
                            err_box.append(EOFError("Hermes brain daemon closed stdout"))
                            return
                        result_box["data"] = json.loads(line)
                    except BaseException as exc:
                        err_box.append(exc)

                t = threading.Thread(target=_reader, daemon=True)
                t.start()
                t.join(self.timeout)
                if t.is_alive():
                    self._terminate_locked()
                    return {"ok": False, "error": f"Hermes brain timeout after {self.timeout}s", "reply": ""}
                if err_box:
                    raise err_box[0]
                return result_box.get("data", {"ok": False, "error": "Empty RPC response", "reply": ""})
            except Exception as exc:
                self._terminate_locked()
                if attempt == 0:
                    continue
                return {"ok": False, "error": str(exc), "reply": ""}
        return {"ok": False, "error": "Unknown RPC failure", "reply": ""}

    def _terminate_locked(self) -> None:
        if self._proc is not None:
            for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def ping(self) -> dict[str, Any]:
        with self._lock:
            return self._send_rpc({"op": "ping"})

    def reply(
        self,
        sender: str,
        message: str,
        live_context: str = "",
        is_dm: bool = False,
        extra_guidance: str = "",
        system_prompt: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            req = {
                "op": "reply",
                "sender": sender,
                "message": message,
                "live_context": live_context,
                "is_dm": bool(is_dm),
                "extra_guidance": extra_guidance,
            }
            if system_prompt or self.system_prompt:
                req["system_prompt"] = system_prompt or self.system_prompt
            return self._send_rpc(req)

    def close(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    assert self._proc.stdin is not None
                    self._proc.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
            self._terminate_locked()


def serve_stdio(
    persona: str,
    db_path: Path | str = DEFAULT_DB_PATH,
    state_dir: Path | str | None = None,
) -> int:
    """Run persistent newline-delimited JSON RPC server over stdin/stdout."""
    ipc_out = sys.stdout
    sys.stdout = sys.stderr  # Protect IPC stdout from any library/tool prints

    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    session = CfukHermesSession(persona=persona, db_path=db_path, state_dir=state_dir)

    def _emit(obj: dict[str, Any]) -> None:
        ipc_out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        ipc_out.flush()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as exc:
            _emit({"ok": False, "error": f"Invalid JSON: {exc}"})
            continue

        op = req.get("op")
        if op == "ping":
            _emit({"ok": True, "persona": session.persona, "session_id": session.session_id})
        elif op == "shutdown":
            _emit({"ok": True, "bye": True})
            break
        elif op == "reply":
            try:
                if req.get("system_prompt"):
                    session.update_system_prompt(str(req["system_prompt"]))
                with contextlib.redirect_stdout(sys.stderr):
                    resp = session.reply(
                        sender=str(req.get("sender") or "Player"),
                        message=str(req.get("message") or ""),
                        live_context=str(req.get("live_context") or ""),
                        is_dm=bool(req.get("is_dm", False)),
                        extra_guidance=str(req.get("extra_guidance") or ""),
                    )
                _emit(resp)
            except Exception as exc:
                _emit({"ok": False, "error": str(exc), "reply": ""})
        else:
            _emit({"ok": False, "error": f"Unknown op: {op}"})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve-stdio", action="store_true", help="Run resident stdio JSON-lines daemon")
    parser.add_argument("--persona", choices=["roshrak", "alt"], default="roshrak")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--search", default=None, help="Search cfuk_memory.db directly")
    parser.add_argument("--source", default="", help="Optional source filter for --search")
    parser.add_argument("--query", default=None, help="Run a one-shot Hermes session reply")
    parser.add_argument("--sender", default="Player")
    args = parser.parse_args()

    if args.serve_stdio:
        return serve_stdio(args.persona, db_path=args.db_path, state_dir=args.state_dir)

    if args.search:
        idx = CfukMemoryIndex(db_path=args.db_path)
        hits = idx.search(args.search, source_filter=args.source, persona=args.persona)
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0

    if args.query:
        session = CfukHermesSession(persona=args.persona, db_path=args.db_path, state_dir=args.state_dir)
        out = session.reply(sender=args.sender, message=args.query)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
