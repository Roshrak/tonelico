#!/usr/bin/env python3
"""Unit tests for cfuk_hermes_brain.py."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

BIN_DIR = Path(__file__).resolve().parent
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import cfuk_hermes_brain as brain  # noqa: E402


def _seed_test_db(db_path: Path, warps_path: Path, bluemap_dir: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE cfuk_messages (
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
            media_notes TEXT DEFAULT '',
            UNIQUE(source, source_msg_id)
        );
        CREATE VIRTUAL TABLE cfuk_messages_fts USING fts5(
            author, channel_name, content, media_notes,
            content='cfuk_messages', content_rowid='id', tokenize='porter unicode61'
        );
        CREATE TABLE cfuk_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            media_key TEXT NOT NULL UNIQUE,
            msg_id TEXT DEFAULT '',
            channel_id TEXT DEFAULT '',
            channel_name TEXT DEFAULT '',
            ts_iso TEXT DEFAULT '',
            ts_unix REAL DEFAULT 0,
            author TEXT DEFAULT '',
            media_type TEXT NOT NULL,
            filename TEXT DEFAULT '',
            url TEXT DEFAULT '',
            local_path TEXT DEFAULT '',
            analysis TEXT DEFAULT '',
            analyzed_at TEXT DEFAULT ''
        );
        """
    )

    rows = [
        ("discord_chan", "d1", "c_gen", "general", "2026-10-01T12:00:00+00:00", 1790856000.0, "BRooNiE", "broonie", "Nuclear snowball crate was buried near -364 35 998", 1, "[image: snow.png]"),
        ("discord_chan", "d2", "c_gen", "general", "2026-10-01T12:05:00+00:00", 1790856300.0, "Shield543", "shield543", "Museum display copy is at Spawn25 -5386 96 -2642", 0, ""),
        ("web_forum", "f1", "tid_9248", "server-discussion/informational", "2012-03-10T10:00:00+00:00", 1331373600.0, "Aconan", "aconan", "Skyrail 2012 connects all main regions across survival", 0, ""),
        ("podcast_cfmp", "p5", "cfmp", "cfmp-podcast", "2011-08-01T20:00:00+00:00", 1312228800.0, "Beagrie", "beagrie", "CFMP Episode 5 We're Hacked Off discussing plugins", 1, "Audio transcript: BRooNiE and Beagrie discuss server uptime"),
        ("ingame_live", "m1", "", "ingame:asDFasfd", "2026-11-10T01:00:00+00:00", 1794272400.0, "Miracle_Involker", "miracle_involker", "secret alt chat message", 0, ""),
        ("discord_chan", "d_sec", "c_sec", "general", "2026-11-11T01:00:00+00:00", 1794358800.0, "Trong", "trong", "sk-1234567890abcdef1234567890abcdef /home/aesc/.hermes/config.yaml", 0, ""),
    ]
    for src, smid, cid, cname, ts_iso, ts_unix, auth, anorm, cont, hm, mnotes in rows:
        cur = conn.execute(
            """INSERT INTO cfuk_messages
               (source, source_msg_id, channel_id, channel_name, ts_iso, ts_unix, author, author_norm, content, is_dm, has_media, media_json, media_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, '[]', ?)""",
            (src, smid, cid, cname, ts_iso, ts_unix, auth, anorm, cont, hm, mnotes),
        )
        conn.execute(
            "INSERT INTO cfuk_messages_fts(rowid, author, channel_name, content, media_notes) VALUES (?, ?, ?, ?, ?)",
            (cur.lastrowid, auth, cname, cont, mnotes),
        )

    media_rows = [
        ("discord", "att:d1:0", "d1", "c_gen", "general", "2026-10-01T12:00:00+00:00", 1790856000.0, "BRooNiE", "image", "snow.png", "https://example.com/snow.png", "OCR shows Edi__ crater sign at -364 35 998"),
        ("podcast_cfmp", "cfmp:5", "p5", "cfmp", "cfmp-podcast", "2011-08-01T20:00:00+00:00", 1312228800.0, "Beagrie", "audio", "Cfmp5.ogg", "https://archive.org/Cfmp5.ogg", "Podcast audio: hacked off episode about permissions"),
        ("youtube", "yt:vid1", "y1", "yt", "youtube", "2020-05-01T12:00:00+00:00", 1588334400.0, "CFUK", "video", "tour.mp4", "https://youtube.com/watch?v=vid1", "Video walkthrough of Crystal Spawn and PistonBlocker"),
    ]
    for m in media_rows:
        conn.execute(
            """INSERT INTO cfuk_media
               (source, media_key, msg_id, channel_id, channel_name, ts_iso, ts_unix, author, media_type, filename, url, analysis, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-11-16')""",
            m,
        )
    conn.commit()
    conn.close()

    warps_path.write_text(json.dumps({"glavia": {"desc": "Snow biome town near spawn", "x": 120, "z": -340}}), encoding="utf-8")
    bluemap_dir.mkdir(parents=True, exist_ok=True)
    (bluemap_dir / "overworld.json").write_text(
        json.dumps({"shops": {"label": "Shops", "markers": {"m1": {"label": "Bazaar", "detail": "<b>Heck shop</b>", "position": {"x": 10, "y": 64, "z": 20}}}}}),
        encoding="utf-8",
    )


class CfukHermesBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "cfuk_memory.db"
        self.warps_path = self.root / "warps.json"
        self.bluemap_dir = self.root / "bluemap"
        _seed_test_db(self.db_path, self.warps_path, self.bluemap_dir)
        self.idx = brain.CfukMemoryIndex(self.db_path, self.warps_path, self.bluemap_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_search_across_all_sources_and_punctuation_fallback(self):
        hits = self.idx.search("nuclear snowball", persona="roshrak")
        self.assertTrue(any(h["source_msg_id"] == "d1" for h in hits))

        forum_hits = self.idx.search("Skyrail", source_filter="forum", persona="roshrak")
        self.assertEqual(len(forum_hits), 1)
        self.assertEqual(forum_hits[0]["author"], "Aconan")

        # Punctuation / coordinate query triggers LIKE fallback without raising
        coord_hits = self.idx.search("-364 35", persona="roshrak")
        self.assertTrue(any("-364" in h["content"] for h in coord_hits))

    def test_media_search_image_audio_video(self):
        img = self.idx.search_media("crater", media_type="image")
        aud = self.idx.search_media("permissions", media_type="audio")
        vid = self.idx.search_media("Crystal Spawn", media_type="video")
        self.assertEqual(img[0]["filename"], "snow.png")
        self.assertEqual(aud[0]["filename"], "Cfmp5.ogg")
        self.assertEqual(vid[0]["filename"], "tour.mp4")

    def test_thread_context_orders_surrounding_messages(self):
        ctx = self.idx.thread_context("discord_chan", "d2", before=2, after=2)
        self.assertEqual([c["source_msg_id"] for c in ctx], ["d1", "d2"])
        self.assertTrue(ctx[1]["is_anchor"])

    def test_player_and_world_lookup_combines_db_warps_and_bluemap(self):
        bazaar = self.idx.player_and_world_lookup("Bazaar")
        self.assertTrue(bazaar["found"])
        self.assertEqual(bazaar["bluemap_markers"][0]["detail"], "Heck shop")

        glavia = self.idx.player_and_world_lookup("glavia")
        self.assertTrue(glavia["warps"])

        aconan = self.idx.player_and_world_lookup("Aconan")
        self.assertEqual(aconan["player_stats"]["total_messages"], 1)

    def test_persona_isolation_blocks_miracle_and_secrets(self):
        self.assertEqual(self.idx.search("Miracle_Involker", persona="roshrak"), [])
        self.assertEqual(self.idx.search("secret alt", persona="roshrak"), [])
        blocked_profile = self.idx.player_and_world_lookup("Miracle_Involker", persona="roshrak")
        self.assertFalse(blocked_profile["found"])

        # Direct credential/path lines referencing Trong/home are filtered for roshrak
        self.assertEqual(self.idx.search("config.yaml", persona="roshrak"), [])
        # Sanitizer itself scrubs tokens & /home paths
        red = brain.sanitize_archive_text("key sk-1234567890abcdef1234567890abcdef at /home/aesc/.hermes/env")
        self.assertNotIn("sk-1234", red)
        self.assertNotIn("/home/aesc", red)

    def test_live_fetch_ssrf_and_domain_allowlist(self):
        bad1 = brain.CfukMemoryIndex.live_fetch("http://127.0.0.1:8080/secret")
        bad2 = brain.CfukMemoryIndex.live_fetch("https://evil.example.com/cfuk")
        bad3 = brain.CfukMemoryIndex.live_fetch("https://steamcommunity.com/id/someone")
        self.assertFalse(bad1["ok"])
        self.assertFalse(bad2["ok"])
        self.assertFalse(bad3["ok"])

        class _FakeResp:
            status = 200

            def __init__(self, payload: bytes):
                self._payload = payload

            def read(self, n: int = -1) -> bytes:
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        html_body = ("<html><body><p>Crazy Fools UK Official News Archive</p>" + " word" * 60 + "</body></html>").encode("utf-8")
        with patch("urllib.request.urlopen", return_value=_FakeResp(html_body)):
            good = brain.CfukMemoryIndex.live_fetch("https://www.crazy-fools.co.uk/news/")
        self.assertTrue(good["ok"])
        self.assertIn("Official News Archive", good["content"])

    def test_stdio_ipc_roundtrip_with_mock_daemon(self):
        mock_srv = self.root / "mock_srv.py"
        mock_srv.write_text(
            "import json, sys\n"
            "for line in sys.stdin:\n"
            "    req = json.loads(line)\n"
            "    if req.get('op') == 'ping':\n"
            "        print(json.dumps({'ok': True, 'persona': 'roshrak'}))\n"
            "    elif req.get('op') == 'reply':\n"
            "        print(json.dumps({'ok': True, 'reply': 'skyrail was built in 2012', 'elapsed': 0.1}))\n"
            "    elif req.get('op') == 'shutdown':\n"
            "        print(json.dumps({'ok': True, 'bye': True})); break\n"
            "    sys.stdout.flush()\n",
            encoding="utf-8",
        )
        client = brain.HermesBrainClient(
            persona="roshrak",
            db_path=self.db_path,
            state_dir=self.root / "state",
            python_executable=sys.executable,
            script_path=mock_srv,
            timeout=5.0,
        )
        try:
            self.assertTrue(client.ping()["ok"])
            r = client.reply("Shield543", "when was skyrail built?")
            self.assertTrue(r["ok"])
            self.assertEqual(r["reply"], "skyrail was built in 2012")
        finally:
            client.close()

    def test_mc_chat_responder_slang_filter_and_hermes_wiring(self):
        import mc_chat_responder as mcr

        mcr.configure_session(user="Roshrak", persona="roshrak")
        styled = mcr.style_as_roshrak("Tbh idk man, ngl fr that spawn25 museum is crazy!")
        self.assertNotIn("tbh", styled.lower().split())
        self.assertNotIn("ngl", styled.lower().split())
        self.assertNotIn("fr", styled.lower().split())
        self.assertNotIn("!", styled)

        class _StubClient:
            def reply(self, **kwargs):
                return {"ok": True, "reply": "at new spawn -5386 96 -2642", "elapsed": 0.2}

        with patch.object(mcr, "get_hermes_brain_client", return_value=_StubClient()):
            out = mcr.query_gemini_brain("Shield543", "where is spawn25 museum?", is_dm=False, reason="open room question")
        self.assertEqual(out, "at new spawn -5386 96 -2642")

    def test_addressee_recognition_and_side_conversation_suppression(self):
        import mc_chat_responder as mcr

        mcr.configure_session(user="Roshrak", persona="roshrak")
        mcr.CHAT_CONTEXT_HISTORY.clear()
        mcr.SIDE_CONVERSATIONS.clear()
        mcr.LAST_DIRECT_TO_US.clear()
        mcr.LAST_BOT_ADDRESSED = ("", 0.0)
        mcr.BOT_SENT_HISTORY.clear()
        mcr.KNOWN_PLAYERS.update({"404thread", "wrb3", "p0licy", "shield543"})

        # 1. Greeting/ack + player alias ("hi wrb", "nice wrb") -> addressed to another player (False)
        mcr.record_chat_context("404thread", "hi wrb")
        ok, reason = mcr.should_respond("404thread", "hi wrb", is_dm=False)
        self.assertFalse(ok, reason)

        # 2. Private 2-player side conversation between wrb3 and 404thread -> suppressed
        mcr.record_chat_context("wrb3", "did you see the frogs near my base")
        ok, reason = mcr.should_respond("wrb3", "did you see the frogs near my base", is_dm=False)
        self.assertFalse(ok, reason)

        mcr.record_chat_context("wrb3", "can i take 10 obsidian from your private stach on the villager island")
        ok, reason = mcr.should_respond("wrb3", "can i take 10 obsidian from your private stach on the villager island", is_dm=False)
        self.assertFalse(ok, reason)

        mcr.record_chat_context("404thread", "ok")
        ok, reason = mcr.should_respond("404thread", "ok", is_dm=False)
        self.assertFalse(ok, reason)

        mcr.record_chat_context("404thread", "nice wrb")
        ok, reason = mcr.should_respond("404thread", "nice wrb", is_dm=False)
        self.assertFalse(ok, reason)

        # 3. Third-person mention prefixed to another player -> False
        ok, _ = mcr.should_respond("404thread", "@wrb3 did roshrak log off?", is_dm=False)
        self.assertFalse(ok)

        # 4. Direct mention -> active 1-on-1 follow-up with us -> True
        mcr.record_chat_context("P0LICY", "roshrak")
        ok, reason = mcr.should_respond("P0LICY", "roshrak", is_dm=False)
        self.assertTrue(ok, reason)
        mcr.LAST_BOT_ADDRESSED = ("p0licy", mcr.time.time())
        mcr.record_chat_context("P0LICY", "give me all your weapons")
        ok, reason = mcr.should_respond("P0LICY", "give me all your weapons", is_dm=False)
        self.assertTrue(ok, reason)

        # 5. Open-room broadcast question & direct DM -> True
        ok, _ = mcr.should_respond("Shield543", "anyone know where spawn25 museum is?", is_dm=False)
        self.assertTrue(ok)
        ok, _ = mcr.should_respond("wrb3", "ok", is_dm=True)
        self.assertTrue(ok)

        # 6. Ambiguous item-noun guard: "hey shield" -> other player (False); "my shield broke" -> not falsely addressed to Shield543
        other, target = mcr.is_addressed_to_other_player("hey shield", "404thread")
        self.assertTrue(other)
        self.assertEqual(target, "shield543")
        other_noun, _ = mcr.is_addressed_to_other_player("my shield broke while fighting", "404thread")
        self.assertFalse(other_noun)

        # 7. Alt isolation & Discord bridge anti-echo remain intact
        ok_self, _ = mcr.should_respond("roshrak#0000", "hello", is_dm=False)
        self.assertFalse(ok_self)

        # 8. Real-log edge cases: "yea both ai", "roshak" typo, "clanker", and 100s side-conv continuation
        ok_both, _ = mcr.should_respond("wrb3", "yea both ai", is_dm=False)
        self.assertTrue(ok_both)
        ok_typo, _ = mcr.should_respond("wrb3", "i tought it was the real roshak", is_dm=False)
        self.assertTrue(ok_typo)
        self.assertTrue(mcr.is_ai_accusation_or_question("holy someone shut that clanker up"))
        # Simulate 100s elapsed since wrb3<->404thread side conversation -> still suppressed (<150s window)
        pair_key = frozenset({"wrb3", "404thread"})
        mcr.SIDE_CONVERSATIONS[pair_key] = mcr.time.time() - 100.0
        mcr.LAST_DIRECT_TO_US.pop("wrb3", None)
        mcr.LAST_BOT_ADDRESSED = ("", 0.0)
        ok_100s, reason_100s = mcr.should_respond("wrb3", "can i take 10 obsidian from your private stach on the villager island", is_dm=False)
        self.assertFalse(ok_100s, reason_100s)


if __name__ == "__main__":
    unittest.main()
