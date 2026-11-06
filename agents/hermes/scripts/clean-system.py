#!/usr/bin/env python3
"""Hermes & System 12h Disk Cleanup Script.

Runs twice daily (09:00 and 21:00, 12h apart):
1. FreeDesktop Trash items older than 12 hours (~/.local/share/Trash/{files,info,expunged})
2. Desktop thumbnails older than 7 days (~/.cache/thumbnails)
3. Chromium web, bytecode & GPU cache (~/.cache/chromium/*/{Cache,Code Cache,GPUCache})
4. User temporary files in /tmp older than 2 days (excluding sockets, pipes & active sessions)
5. Nix store garbage collection (nix-collect-garbage --delete-older-than 7d, skipped if a Nix build is active)
6. Hermes temporary caches (audio_cache, image_cache, sandboxes >2d, cron/output >3d, scratch/terminal-output >1d)
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

HOUR = 3600
DAY = 86400
TRASH_MAX_AGE = 12 * HOUR
PROTECTED_TMP_PREFIXES = (
    "claude-", "lwjgl", "ssh-", "systemd-private-", "runtime-", "hsperfdata",
    "sddm", "dbus-", "pulse", "pipewire", ".X", ".ICE", ".font", ".XIM",
    ".wine", "pyright", "sway-", "hypr", "wayland-",
)


def fmt_bytes(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 MB (< 1 MB change)"
    mb = num_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB ({int(mb)} MB)"
    if mb >= 1:
        return f"{int(round(mb))} MB"
    kb = max(1, int(round(num_bytes / 1024)))
    return f"{kb} KB"


def fmt_gib(num_bytes: int) -> str:
    return f"{num_bytes / (1024 ** 3):.2f} GiB"


def active_camoufox_profiles() -> set[str]:
    active: set[str] = set()
    proc = Path("/proc")
    try:
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().decode("utf-8", errors="ignore").split("\x00")
                for i, arg in enumerate(cmdline):
                    if arg == "-profile" and i + 1 < len(cmdline):
                        active.add(Path(cmdline[i + 1]).name)
            except OSError:
                continue
    except OSError:
        pass
    return active


def is_nix_build_active() -> bool:
    proc = Path("/proc")
    try:
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().decode("utf-8", errors="ignore")
                if any(k in cmdline for k in ("nixos-rebuild", "update-system.sh", "nix\x00build", "nix\x00flake\x00update")):
                    return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def remove_item(item: Path) -> None:
    st = item.lstat()
    if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
        shutil.rmtree(item, ignore_errors=True)
    else:
        item.unlink(missing_ok=True)


def remove_tree_contents(directory: Path, max_age_seconds: float | None = None, now: float | None = None) -> int:
    if not directory.is_dir():
        return 0
    if now is None:
        now = time.time()
    removed = 0
    for item in list(directory.iterdir()):
        try:
            st = item.lstat()
            if max_age_seconds is not None and (now - st.st_mtime) < max_age_seconds:
                continue
            remove_item(item)
            removed += 1
        except OSError:
            continue
    return removed


def parse_trashinfo_time(info_file: Path) -> float | None:
    try:
        for line in info_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("DeletionDate="):
                raw = line.split("=", 1)[1].strip()
                parsed = dt.datetime.fromisoformat(raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
                return parsed.timestamp()
    except Exception:
        pass
    try:
        return info_file.lstat().st_mtime
    except OSError:
        return None


def clean_trash(trash_dir: Path, max_age_seconds: float, now: float) -> int:
    files_dir = trash_dir / "files"
    info_dir = trash_dir / "info"
    expunged_dir = trash_dir / "expunged"
    for d in (files_dir, info_dir, expunged_dir):
        d.mkdir(parents=True, exist_ok=True)

    removed = 0
    for item in list(files_dir.iterdir()):
        try:
            info_path = info_dir / f"{item.name}.trashinfo"
            trashed_at = parse_trashinfo_time(info_path) if info_path.exists() else item.lstat().st_ctime
            if trashed_at is None or (now - trashed_at) < max_age_seconds:
                continue
            remove_item(item)
            info_path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue

    for info_path in list(info_dir.iterdir()):
        if not info_path.name.endswith(".trashinfo"):
            continue
        stem = info_path.name[:-10]
        if (files_dir / stem).exists():
            continue
        trashed_at = parse_trashinfo_time(info_path)
        if trashed_at is not None and (now - trashed_at) >= max_age_seconds:
            info_path.unlink(missing_ok=True)
            removed += 1

    removed += remove_tree_contents(expunged_dir, max_age_seconds=max_age_seconds, now=now)
    return removed


def clean_older_files(directory: Path, max_age_seconds: float, now: float) -> int:
    if not directory.is_dir():
        return 0
    removed = 0
    for root, dirs, files in os.walk(directory, topdown=False):
        root_path = Path(root)
        for fname in files:
            fpath = root_path / fname
            try:
                st = fpath.lstat()
                if (now - st.st_mtime) >= max_age_seconds:
                    fpath.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        for dname in dirs:
            dpath = root_path / dname
            try:
                if not any(dpath.iterdir()):
                    dpath.rmdir()
            except OSError:
                continue
    return removed


def clean_tmp(now: float) -> int:
    tmp_dir = Path("/tmp")
    uid = os.getuid()
    active_profiles = active_camoufox_profiles()
    removed = 0
    if not tmp_dir.is_dir():
        return 0

    for item in list(tmp_dir.iterdir()):
        name = item.name
        if name.startswith(PROTECTED_TMP_PREFIXES):
            continue
        if name.startswith("aistudio-camoufox-") and name in active_profiles:
            continue
        try:
            st = item.lstat()
            if st.st_uid != uid:
                continue
            if stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode):
                continue
            age_limit = (6 * HOUR) if name.startswith("aistudio-camoufox-") else (2 * DAY)
            if (now - st.st_mtime) < age_limit:
                continue
            remove_item(item)
            removed += 1
        except OSError:
            continue
    return removed


def main() -> int:
    home = Path.home()
    xdg_data = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", str(home / ".cache")))
    hermes_dir = home / ".hermes"
    now = time.time()

    env = dict(os.environ)
    env["PATH"] = (
        f"/run/current-system/sw/bin:/etc/profiles/per-user/{os.environ.get('USER', 'aesc')}/bin:"
        f"{home / '.nix-profile/bin'}:{home / '.local/bin'}:{env.get('PATH', '')}"
    )

    start_free = shutil.disk_usage("/").free

    # 0. Pre-cleanup Memory Vault verification & backup
    guard_bin = home / ".local" / "bin" / "hermes-memory-guard"
    if guard_bin.exists():
        subprocess.run([str(guard_bin), "--backup-db"], env=env, capture_output=True, text=True, check=False)

    # 1. FreeDesktop Trash (>12 hours in Trash)
    trash_removed = clean_trash(xdg_data / "Trash", TRASH_MAX_AGE, now)

    # 2. Desktop thumbnails older than 7 days
    thumbs_removed = clean_older_files(xdg_cache / "thumbnails", 7 * DAY, now)

    # 3. Chromium web, bytecode & GPU cache
    chromium_removed = 0
    chromium_dir = xdg_cache / "chromium"
    if chromium_dir.is_dir():
        for profile in chromium_dir.iterdir():
            if not profile.is_dir():
                continue
            for cache_sub in ("Cache", "Code Cache", "GPUCache"):
                cdir = profile / cache_sub
                if cdir.is_dir():
                    chromium_removed += remove_tree_contents(cdir)

    # 4. Temporary files in /tmp older than 2 days (+ orphaned Camoufox profiles > 6h)
    tmp_removed = clean_tmp(now)

    # 5. Nix store garbage collection (older than 7d + dead store paths, skipped if a Nix build is active)
    nix_gc_bin = shutil.which("nix-collect-garbage", path=env["PATH"]) or "/run/current-system/sw/bin/nix-collect-garbage"
    if is_nix_build_active():
        nix_summary = "skipped (active NixOS build/update in progress)"
    elif Path(nix_gc_bin).exists():
        try:
            proc = subprocess.run(
                [nix_gc_bin, "--delete-older-than", "7d"],
                env=env,
                capture_output=True,
                text=True,
                timeout=1800,
            )
            combined = "\n".join([proc.stdout or "", proc.stderr or ""]).splitlines()
            deleted_line = next((l.strip() for l in reversed(combined) if "store paths deleted" in l), None)
            nix_summary = deleted_line if deleted_line else "completed"
        except Exception as exc:
            nix_summary = f"warning ({exc})"
    else:
        nix_summary = "skipped (nix-collect-garbage not found)"

    # 6. Hermes internal temporary caches
    hermes_removed = 0
    for sub in ("audio_cache", "image_cache"):
        hermes_removed += remove_tree_contents(hermes_dir / sub)
    hermes_removed += remove_tree_contents(hermes_dir / "sandboxes", max_age_seconds=2 * DAY, now=now)
    hermes_removed += remove_tree_contents(hermes_dir / "cron" / "output", max_age_seconds=3 * DAY, now=now)
    hermes_removed += remove_tree_contents(hermes_dir / "cache" / "scratch", max_age_seconds=1 * DAY, now=now)
    hermes_removed += remove_tree_contents(hermes_dir / "cache" / "terminal-output", max_age_seconds=1 * DAY, now=now)

    # 7. Antigravity Manager SQLite log compaction (prevent proxy_logs.db bloat)
    agm_logs_db = home / ".antigravity_tools" / "proxy_logs.db"
    if agm_logs_db.is_file() and agm_logs_db.stat().st_size > 10 * 1024 * 1024:
        try:
            import sqlite3
            with sqlite3.connect(str(agm_logs_db), timeout=5.0) as conn:
                conn.execute(
                    "DELETE FROM request_logs WHERE rowid NOT IN ("
                    "SELECT rowid FROM request_logs ORDER BY rowid DESC LIMIT 30)"
                )
                conn.commit()
                conn.execute("VACUUM")
        except Exception:
            pass

    end_usage = shutil.disk_usage("/")
    end_free = end_usage.free
    freed_bytes = max(0, end_free - start_free)
    completion_time = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    print("🧹 **Hermes & System 12h Cleanup Completed**")
    print(f"• **Completed at:** {completion_time}")
    print(f"• **Space freed:** {fmt_bytes(freed_bytes)}")
    print(f"• **Disk free (`/`):** {fmt_gib(start_free)} → {fmt_gib(end_free)}")
    print("• **Cleaned targets:**")
    print(f"  - FreeDesktop Trash >12h (`~/.local/share/Trash`): {trash_removed} item(s)")
    print(f"  - Desktop thumbnails >7d (`~/.cache/thumbnails`): {thumbs_removed} file(s)")
    print(f"  - Chromium cache (`Cache`, `Code Cache`, `GPUCache`): {chromium_removed} entry(s)")
    print(f"  - Temporary `/tmp` files (>2d): {tmp_removed} item(s)")
    print(f"  - Nix store garbage (>7d): {nix_summary}")
    print(f"  - Hermes temp caches (audio, image, scratch, sandboxes, cron output): {hermes_removed} item(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
