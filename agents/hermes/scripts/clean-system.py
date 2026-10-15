#!/usr/bin/env python3
"""Tiered cache/temp/Trash retention with no-follow, handle-relative deletion.

Retention (a file is only ever removed when it is older than its tier):
  /tmp (this user's entries)        3 days   never files a process has open or uses as cwd
  uv / npm caches, Hermes logs     14 days
  Hermes media caches, cron output 30 days
  Trash, thumbnails, Chromium      30 days
  Docker (rootless)                dangling images, build cache older than 7 days
  Nix store                        dead (unreferenced) paths only, and only when the disk
                                   is low; the weekly nix.gc timer does the routine work.
                                   Generations are never deleted here.

Cooperative locking prevents this cleaner racing itself. Private quarantine and
identity checks protect normal concurrent cache replacements. This cannot stop
an arbitrary same-UID writer holding an already-open file/directory descriptor;
it is not a security boundary against that process. The cooperative lock is
valid only while its pathname continues to identify the locked inode: a same-UID
process can rename/replace that lock path and bypass cooperation. Unknown quarantine conflicts
remain preserved with a visible error. Reports, sandboxes, Hermes sessions and
state are not cleaned here.
"""
from __future__ import annotations
import argparse
import ctypes
import datetime as dt
import errno
import fcntl
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

RETENTION_DAYS = 30          # Trash, thumbnails, browser and Hermes media caches
CACHE_DAYS = 14              # package-manager caches and Hermes logs
TMP_DAYS = 3                 # this user's entries in /tmp
DOCKER_BUILD_CACHE_HOURS = 168
LOW_SPACE_BYTES = 40 * 1024**3
DAY_SECONDS = 24 * 60 * 60
BROWSER_PROCESS_NAMES = {"chromium", "chromium-browser", "chrome", "google-chrome", "google-chrome-stable"}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
# Names in /tmp that belong to a running session, a game or a service.
TMP_PROTECTED_PREFIXES = (
    "claude-", "lwjgl", "ssh-", "systemd-private-", "runtime-", "hsperfdata", "sddm",
    "dbus-", "pulse", "pipewire", ".X", ".ICE", ".font", ".XIM", ".wine", "pyright",
)

@dataclass
class TargetResult:
    label: str
    examined: int = 0
    eligible: int = 0
    removed: int = 0
    estimated_bytes: int = 0
    removed_bytes: int = 0
    partial_removals: int = 0
    in_use: int = 0
    skipped: str = ""
    note: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

class Preserved(OSError):
    """A changed, linked or unowned selection must not be deleted."""

class PartialRemoval(OSError):
    """Recursive removal failed after it may have deleted some descendants."""

def identity(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_size, s.st_mtime_ns, s.st_nlink)

def open_directory(path: Path) -> int:
    """Pin every absolute path component without following any symlink."""
    path = Path(os.path.abspath(path))
    fd = os.open('/', DIR_FLAGS)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            s = os.fstat(fd)
            if s.st_uid not in {0, os.geteuid()}:
                raise Preserved('directory is not owned by this user or root')
            # Root-owned sticky /tmp is a legitimate fixture ancestor, not a
            # selected root. Other writable ancestors are not trusted.
            if s.st_mode & 0o022 and not (s.st_uid == 0 and s.st_mode & stat.S_ISVTX):
                raise Preserved('directory has unsafe group/other write permission')
        if os.fstat(fd).st_uid != os.geteuid():
            raise Preserved('selected root is not owned by the current user')
        return fd
    except BaseException:
        os.close(fd)
        raise

def path_is_real_directory(path: Path) -> bool:
    try:
        fd = open_directory(path)
        os.close(fd)
        return True
    except OSError:
        return False

def _walk_files(fd, errors):
    """Yield pinned parent handles and non-followed, owned regular selections."""
    try:
        names = sorted(os.listdir(fd))
    except OSError as exc:
        errors.append(f'Could not enumerate pinned cache directory: {exc}')
        return
    for name in names:
        if name.startswith('.hermes-clean-quarantine-'):
            errors.append('Unresolved previous cleanup quarantine preserved')
            continue
        try:
            s = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if s.st_uid != os.geteuid():
                errors.append('Unowned cache entry preserved')
                continue
            if stat.S_ISDIR(s.st_mode):
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (s.st_dev, s.st_ino) or opened.st_mode & 0o022:
                        raise Preserved('cache directory changed or has unsafe permissions')
                    yield from _walk_files(child, errors)
                finally:
                    os.close(child)
            elif stat.S_ISREG(s.st_mode):
                if s.st_nlink != 1:
                    errors.append('Hard-linked cache file preserved')
                    continue
                yield fd, name, s
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f'Cache entry preserved: {exc}')

def rename_noreplace(source_fd, source_name, destination_fd, destination_name):
    """Linux renameat2: never overwrite a destination, including a symlink."""
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, 'renameat2', None)
    if fn is None:
        raise OSError(errno.ENOTSUP, 'atomic no-replace rename unavailable')
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(source_fd, os.fsencode(source_name), destination_fd, os.fsencode(destination_name), 1):
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e))

def quarantine(parent_fd, name, selected, cutoff=None):
    """Move then verify a selected object; restore mismatches without overwrite."""
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if identity(current) != identity(selected) or current.st_ctime_ns != selected.st_ctime_ns:
        raise Preserved('selected object changed before quarantine')
    if cutoff is not None and current.st_mtime >= cutoff:
        raise Preserved('selected file is no longer expired')
    qname = '.hermes-clean-quarantine-' + uuid.uuid4().hex
    os.mkdir(qname, mode=0o700, dir_fd=parent_fd)
    qfd = os.open(qname, DIR_FLAGS, dir_fd=parent_fd)
    moved = False
    try:
        rename_noreplace(parent_fd, name, qfd, 'item')
        moved = True
        actual = os.stat('item', dir_fd=qfd, follow_symlinks=False)
        if identity(actual) != identity(selected) or (cutoff is not None and actual.st_mtime >= cutoff):
            raise Preserved('selected object was replaced or refreshed while quarantining')
        return qfd, qname
    except BaseException:
        try:
            if moved:
                rename_noreplace(qfd, 'item', parent_fd, name)
            os.rmdir(qname, dir_fd=parent_fd)
        except OSError as exc:
            raise Preserved(f'Quarantine conflict preserved at {qname}: {exc}')
        finally:
            os.close(qfd)
        raise

def restore_quarantine(parent_fd, original_name, qfd, qname, errors):
    try:
        rename_noreplace(qfd, 'item', parent_fd, original_name)
        os.rmdir(qname, dir_fd=parent_fd)
    except OSError as exc:
        errors.append(f'Quarantine preserved for recovery at {qname}; original path was not overwritten: {exc}')
    finally:
        os.close(qfd)

def finish_quarantine(parent_fd, qfd, qname):
    os.rmdir(qname, dir_fd=parent_fd)
    os.close(qfd)

def _tree_size(fd, name):
    s = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISDIR(s.st_mode):
        if not (stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode)) or s.st_uid != os.geteuid():
            raise Preserved('unsupported or unowned Trash entry')
        return s.st_size
    child = os.open(name, DIR_FLAGS, dir_fd=fd)
    try:
        if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (s.st_dev, s.st_ino):
            raise Preserved('Trash directory changed')
        if s.st_uid != os.geteuid() or s.st_mode & 0o022:
            raise Preserved('unowned or unsafe Trash directory')
        return sum(_tree_size(child, n) for n in os.listdir(child))
    finally:
        os.close(child)

def _remove_quarantined(qfd, selected):
    actual = os.stat('item', dir_fd=qfd, follow_symlinks=False)
    if identity(actual) != identity(selected):
        raise Preserved('quarantined object was changed; deletion refused')
    if stat.S_ISDIR(actual.st_mode):
        if not shutil.rmtree.avoids_symlink_attacks:
            raise Preserved('safe descriptor-relative directory removal unavailable')
        try:
            shutil.rmtree('item', dir_fd=qfd)
        except OSError as exc:
            raise PartialRemoval(f'Trash directory removal interrupted; some contents may already be gone and removed bytes are unknown: {exc}') from exc
    elif stat.S_ISREG(actual.st_mode) or stat.S_ISLNK(actual.st_mode):
        os.unlink('item', dir_fd=qfd)
    else:
        raise Preserved('unsupported quarantined entry type')

def _read_metadata(fd, name):
    leaf = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    try:
        selected = os.fstat(leaf)
        if not stat.S_ISREG(selected.st_mode) or selected.st_uid != os.geteuid() or selected.st_nlink != 1:
            raise Preserved('unowned, linked or nonregular Trash metadata')
        data = os.read(leaf, 65537)
        if len(data) > 65536 or identity(os.fstat(leaf)) != identity(selected):
            raise Preserved('Trash metadata changed or exceeds bounded size')
        return selected, data
    finally:
        os.close(leaf)

def _deletion_date(data):
    dates = [line.split('=', 1)[1].strip() for line in data.decode('utf-8', errors='replace').splitlines() if line.startswith('DeletionDate=')]
    if len(dates) != 1:
        return None
    try:
        parsed = dt.datetime.fromisoformat(dates[0])
        return parsed.astimezone() if parsed.tzinfo is None else parsed
    except ValueError:
        return None

def open_inodes(proc_root: Path = Path("/proc")) -> set[int]:
    """Inodes that any process has open, mapped, or as its working directory.

    Matching on the inode alone (not the device) can only over-protect, never
    under-protect, so a file in this set is simply left alone.
    """
    inodes: set[int] = set()
    try:
        pids = [p for p in proc_root.iterdir() if p.name.isdigit()]
    except OSError:
        return inodes
    for proc in pids:
        for link in ("cwd", "root"):
            try:
                inodes.add(os.stat(proc / link).st_ino)
            except OSError:
                pass
        try:
            for fd in os.listdir(proc / "fd"):
                try:
                    inodes.add(os.stat(proc / "fd" / fd).st_ino)
                except OSError:
                    pass
        except OSError:
            pass
        try:
            with open(proc / "maps", encoding="utf-8", errors="replace") as maps:
                for line in maps:
                    parts = line.split()
                    if len(parts) >= 5 and parts[4] != "0":
                        inodes.add(int(parts[4]))
        except (OSError, ValueError):
            pass
    return inodes


def snapshot_dir_mtimes(root: Path) -> dict[int, float]:
    """inode -> mtime for every real directory under root, read before cleaning so that
    deleting a directory's expired files does not make it look freshly modified."""
    seen: dict[int, float] = {}
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            seen[st.st_ino] = st.st_mtime
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    try:
        st = os.stat(root, follow_symlinks=False)
        seen[st.st_ino] = st.st_mtime
    except OSError:
        pass
    return seen


def prune_empty_dirs(parent_fd, name, cutoff, dry_run, result, protect=frozenset(), mtimes=None) -> bool:
    """Remove empty, expired, user-owned directories bottom-up. True if `name` is gone
    (or, in a dry run, would be). rmdir cannot remove a directory that gained content."""
    try:
        s = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.geteuid() or s.st_mode & 0o022:
            return False
        child = os.open(name, DIR_FLAGS, dir_fd=parent_fd)
    except OSError:
        return False
    empty = True
    try:
        opened = os.fstat(child)
        if (opened.st_dev, opened.st_ino) != (s.st_dev, s.st_ino):
            return False
        for entry in sorted(os.listdir(child)):
            if entry.startswith('.hermes-clean-quarantine-'):
                empty = False
                continue
            if not prune_empty_dirs(child, entry, cutoff, dry_run, result, protect, mtimes):
                empty = False
    except OSError:
        return False
    finally:
        os.close(child)
    # Judge the directory by its mtime from before this run emptied it.
    before = (mtimes or {}).get(s.st_ino, s.st_mtime)
    if not empty or before >= cutoff or s.st_ino in protect:
        return False
    result.examined += 1
    result.eligible += 1
    if dry_run:
        return True
    try:
        again = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (again.st_dev, again.st_ino) != (s.st_dev, s.st_ino):
            return False
        os.rmdir(name, dir_fd=parent_fd)
        result.removed += 1
        return True
    except OSError:
        return False


def clean_tmp(tmp_root: Path, cutoff: float, dry_run: bool, protect: set[int], browsers: list[str]) -> TargetResult:
    """Expire this user's old entries in a shared, sticky /tmp."""
    result = TargetResult(f"/tmp entries older than {TMP_DAYS} days")
    try:
        tmp_fd = os.open(tmp_root, DIR_FLAGS)
    except OSError as exc:
        result.skipped = f"/tmp not available: {exc}"
        return result
    try:
        for name in sorted(os.listdir(tmp_fd)):
            if name.startswith(TMP_PROTECTED_PREFIXES) or name.startswith('.hermes-clean-quarantine-'):
                continue
            if browsers and 'chromium' in name.lower():
                continue
            try:
                s = os.stat(name, dir_fd=tmp_fd, follow_symlinks=False)
            except OSError:
                continue
            if s.st_uid != os.geteuid():
                continue
            if stat.S_ISREG(s.st_mode):
                if s.st_nlink != 1 or s.st_mtime >= cutoff:
                    continue
                result.examined += 1
                if s.st_ino in protect:
                    result.in_use += 1
                    continue
                result.eligible += 1
                result.estimated_bytes += s.st_size
                if dry_run:
                    continue
                try:
                    again = os.stat(name, dir_fd=tmp_fd, follow_symlinks=False)
                    if identity(again) != identity(s):
                        continue
                    os.unlink(name, dir_fd=tmp_fd)
                    result.removed += 1
                    result.removed_bytes += s.st_size
                except OSError as exc:
                    result.warnings.append(f'/tmp file preserved: {exc}')
            elif stat.S_ISDIR(s.st_mode):
                if s.st_mode & 0o022:
                    continue
                mtimes = snapshot_dir_mtimes(tmp_root / name)
                sub = clean_old_cache_files(name, tmp_root / name, cutoff, dry_run, protect)
                result.examined += sub.examined
                result.eligible += sub.eligible
                result.removed += sub.removed
                result.estimated_bytes += sub.estimated_bytes
                result.removed_bytes += sub.removed_bytes
                result.partial_removals += sub.partial_removals
                result.in_use += sub.in_use
                # Files other users or hard links keep alive are expected in /tmp;
                # count them instead of reporting each as an error.
                for message in sub.errors:
                    if message.startswith(('Unowned', 'Hard-linked', 'Cache entry preserved')):
                        result.in_use += 1
                    else:
                        result.errors.append(message)
                if sub.skipped and 'absent' not in sub.skipped:
                    result.in_use += 1
                prune_empty_dirs(tmp_fd, name, cutoff, dry_run, result, protect, mtimes)
    finally:
        os.close(tmp_fd)
    return result


def clean_old_cache_files(label, root: Path, cutoff: float, dry_run: bool, protect=frozenset()) -> TargetResult:
    result = TargetResult(label)
    try:
        root_fd = open_directory(root)
    except FileNotFoundError:
        result.skipped = 'Cache directory is absent'
        return result
    except OSError as exc:
        result.skipped = f'Cache root preserved: {exc}'
        return result
    try:
        for parent_fd, name, selected in _walk_files(root_fd, result.errors):
            result.examined += 1
            if selected.st_mtime >= cutoff:
                continue
            if selected.st_ino in protect:
                result.in_use += 1
                continue
            result.eligible += 1
            result.estimated_bytes += selected.st_size
            if dry_run:
                continue
            qfd = None
            try:
                qfd, qname = quarantine(parent_fd, name, selected, cutoff)
                _remove_quarantined(qfd, selected)
                result.removed += 1
                result.removed_bytes += selected.st_size
                finish_quarantine(parent_fd, qfd, qname)
                qfd = None
            except OSError as exc:
                result.errors.append(f'Cache file preserved or removal failed: {exc}')
                if qfd is not None:
                    restore_quarantine(parent_fd, name, qfd, qname, result.errors)
    finally:
        os.close(root_fd)
    # Empty directories are retained: their owner may still be using them.
    return result

def clean_expired_trash(trash_root: Path, cutoff: float, dry_run: bool) -> TargetResult:
    result = TargetResult(f'Trash entries older than {RETENTION_DAYS} days')
    opened = []
    try:
        trash_fd = open_directory(trash_root); opened.append(trash_fd)
        info_fd = os.open('info', DIR_FLAGS, dir_fd=trash_fd); opened.append(info_fd)
        files_fd = os.open('files', DIR_FLAGS, dir_fd=trash_fd); opened.append(files_fd)
        for fd in (info_fd, files_fd):
            s = os.fstat(fd)
            if s.st_uid != os.geteuid() or s.st_mode & 0o022:
                raise Preserved('unsafe Trash subdirectory')
    except FileNotFoundError:
        for fd in reversed(opened): os.close(fd)
        result.skipped = 'Trash metadata/files directory is absent'
        return result
    except OSError as exc:
        for fd in reversed(opened): os.close(fd)
        result.skipped = f'Trash root preserved: {exc}'
        return result
    try:
        for name in sorted(os.listdir(info_fd)):
            if name.startswith('.hermes-clean-quarantine-'):
                result.errors.append('Previous Trash quarantine preserved for recovery')
                continue
            if not name.endswith('.trashinfo'):
                continue
            item_name = name[:-len('.trashinfo')]
            if item_name in {'', '.', '..'} or '/' in item_name or '\\' in item_name:
                result.errors.append('Unsafe Trash item name preserved')
                continue
            qmeta = qitem = None
            payload_removed = metadata_removed = False
            try:
                metadata, data = _read_metadata(info_fd, name)
                result.examined += 1
                deleted = _deletion_date(data)
                if deleted is None:
                    result.warnings.append('Malformed Trash metadata preserved')
                    continue
                if deleted.timestamp() >= cutoff:
                    continue
                try:
                    selected = os.stat(item_name, dir_fd=files_fd, follow_symlinks=False)
                    size = _tree_size(files_fd, item_name)
                except FileNotFoundError:
                    selected = None
                    size = 0
                result.eligible += 1
                result.estimated_bytes += size + metadata.st_size
                if dry_run:
                    continue
                # Both objects must pass quarantine verification before either
                # is deleted. A refusal restores the pair, never overwriting.
                qmeta = quarantine(info_fd, name, metadata)
                _, current_data = _read_metadata(qmeta[0], 'item')
                if current_data != data or _deletion_date(current_data).timestamp() >= cutoff:
                    raise Preserved('Trash metadata changed or is no longer expired')
                if selected is not None:
                    qitem = quarantine(files_fd, item_name, selected)
                    _tree_size(qitem[0], 'item')
                else:
                    try:
                        os.stat(item_name, dir_fd=files_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise Preserved('New Trash data appeared; metadata preserved')
                if qitem is not None:
                    _remove_quarantined(qitem[0], selected)
                    payload_removed = True
                    result.removed_bytes += size
                    finish_quarantine(files_fd, *qitem); qitem = None
                _remove_quarantined(qmeta[0], metadata)
                metadata_removed = True
                result.removed += 1
                result.removed_bytes += metadata.st_size
                finish_quarantine(info_fd, *qmeta); qmeta = None
            except FileNotFoundError:
                result.errors.append('Trash selection disappeared during cleanup; remainder preserved')
            except OSError as exc:
                if isinstance(exc, PartialRemoval):
                    result.partial_removals += 1
                    result.errors.append(f'Possibly partial Trash deletion: remaining pair will be restored where possible, but original directory contents cannot be certified intact and removed bytes are unknown: {exc}')
                elif payload_removed or metadata_removed:
                    result.errors.append(f'Partial Trash cleanup: deletion already occurred ({result.removed_bytes} bytes recorded); remaining metadata/quarantine preserved: {exc}')
                else:
                    result.errors.append(f'Trash deletion refused before any removal; pair restored where no conflicting path exists: {exc}')
            finally:
                if qitem is not None:
                    if payload_removed:
                        os.close(qitem[0])
                        result.errors.append(f'Empty payload quarantine retained after cleanup failure: {qitem[1]}')
                    else:
                        restore_quarantine(files_fd, item_name, *qitem, result.errors)
                if qmeta is not None:
                    if metadata_removed:
                        os.close(qmeta[0])
                        result.errors.append(f'Empty metadata quarantine retained after cleanup failure: {qmeta[1]}')
                    else:
                        restore_quarantine(info_fd, name, *qmeta, result.errors)
    finally:
        for fd in reversed(opened): os.close(fd)
    return result


def running_browser_processes(proc_root: Path = Path("/proc")) -> list[str]:
    found: list[str] = []
    try:
        processes = list(proc_root.iterdir())
    except OSError:
        return ["browser state unavailable"]
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            name = (process / "comm").read_text(encoding="utf-8", errors="replace").strip().lower()
        except OSError:
            continue
        if name in BROWSER_PROCESS_NAMES:
            found.append(name)
    return sorted(set(found))


def disk_available(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def _tool(name: str) -> str:
    return shutil.which(name) or f"/run/current-system/sw/bin/{name}"


def docker_prune(dry_run: bool) -> TargetResult:
    """Rootless Docker: dangling images and old build cache only. Never containers or volumes."""
    result = TargetResult(f"Docker: dangling images and build cache older than {DOCKER_BUILD_CACHE_HOURS // 24} days")
    host = os.environ.get("DOCKER_HOST") or f"unix:///run/user/{os.geteuid()}/docker.sock"
    sock = Path(host[len("unix://"):]) if host.startswith("unix://") else None
    if sock is not None and not sock.exists():
        result.skipped = "Docker is not running"
        return result
    if dry_run:
        result.skipped = "dry run: Docker is only pruned in a real run"
        return result
    env = dict(os.environ, DOCKER_HOST=host)
    reclaimed = []
    for args in (["image", "prune", "-f"],
                 ["builder", "prune", "-f", "--filter", f"until={DOCKER_BUILD_CACHE_HOURS}h"]):
        try:
            done = subprocess.run([_tool("docker"), *args], env=env, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result.errors.append(f"docker {args[0]} prune did not run: {exc}")
            continue
        if done.returncode != 0:
            result.errors.append(f"docker {args[0]} prune failed: {done.stderr.strip()[:160]}")
            continue
        for line in done.stdout.splitlines():
            if line.lower().startswith("total reclaimed space"):
                reclaimed.append(line.split(":", 1)[1].strip())
    result.note = "reclaimed " + " + ".join(reclaimed) if reclaimed else "nothing to prune"
    return result


def nix_garbage(free_now: int | None, dry_run: bool) -> TargetResult:
    """Report dead Nix paths; collect them only when the disk is low. Never deletes generations."""
    result = TargetResult("Nix store (dead paths only; generations are never touched)")
    try:
        listed = subprocess.run([_tool("nix-store"), "--gc", "--print-dead"],
                                capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.warnings.append(f"could not list dead Nix paths: {exc}")
        return result
    if listed.returncode != 0:
        result.warnings.append(f"could not list dead Nix paths: {listed.stderr.strip()[:160]}")
        return result
    dead = len([line for line in listed.stdout.splitlines() if line.startswith("/nix/store/")])
    result.examined = dead
    low = free_now is not None and free_now < LOW_SPACE_BYTES
    if not low or dead == 0 or dry_run:
        why = "disk space is fine" if not low else "dry run"
        result.note = f"{dead} unreferenced path(s); not collecting now ({why}); the weekly nix-gc timer handles them"
        return result
    try:
        done = subprocess.run([_tool("nix-store"), "--gc"], capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.errors.append(f"nix-store --gc did not finish: {exc}")
        return result
    if done.returncode != 0:
        result.errors.append(f"nix-store --gc failed: {done.stderr.strip()[:160]}")
        return result
    summary = next((l for l in reversed(done.stdout.splitlines() + done.stderr.splitlines())
                    if "store paths deleted" in l), "collected")
    result.note = f"low disk space ({format_bytes(free_now)} free): {summary.strip()}"
    return result


def _run_cleanup_unlocked(
    home: Path, data_home: Path, cache_home: Path, dry_run: bool,
    tmp_root: Path | None = None, system_wide: bool = True,
) -> tuple[int, list[TargetResult], int | None, int | None]:
    started = time.time()
    cutoff = started - RETENTION_DAYS * DAY_SECONDS
    cache_cutoff = started - CACHE_DAYS * DAY_SECONDS
    tmp_cutoff = started - TMP_DAYS * DAY_SECONDS
    before = disk_available(home)
    results: list[TargetResult] = []
    protect = open_inodes()
    browsers = running_browser_processes()

    results.append(clean_tmp(tmp_root or Path("/tmp"), tmp_cutoff, dry_run, protect, browsers))

    results.append(clean_expired_trash(data_home / "Trash", cutoff, dry_run))

    results.append(
        clean_old_cache_files(
            f"Thumbnails older than {RETENTION_DAYS} days", cache_home / "thumbnails", cutoff, dry_run, protect
        )
    )

    chromium = cache_home / "chromium"
    if browsers and chromium.exists():
        result = TargetResult("Chromium cache retention")
        result.skipped = "Chromium is running or browser state is unavailable; cache is untouched"
        results.append(result)
    else:
        results.append(
            clean_old_cache_files(
                f"Chromium cache files older than {RETENTION_DAYS} days", chromium, cutoff, dry_run, protect
            )
        )

    for label, root in (("uv cache", cache_home / "uv"), ("npm cache", home / ".npm" / "_cacache")):
        results.append(
            clean_old_cache_files(f"{label} files older than {CACHE_DAYS} days", root, cache_cutoff, dry_run, protect)
        )

    hermes = home / ".hermes"
    for cache_name in ("audio_cache", "image_cache"):
        results.append(
            clean_old_cache_files(
                f"Hermes {cache_name} files older than {RETENTION_DAYS} days",
                hermes / cache_name, cutoff, dry_run, protect,
            )
        )
    results.append(
        clean_old_cache_files(
            f"Hermes cron output older than {RETENTION_DAYS} days", hermes / "cron" / "output", cutoff, dry_run, protect
        )
    )
    results.append(
        clean_old_cache_files(
            f"Hermes logs older than {CACHE_DAYS} days", hermes / "logs", cache_cutoff, dry_run, protect
        )
    )

    if system_wide:
        results.append(docker_prune(dry_run))
        results.append(nix_garbage(disk_available(home), dry_run))

    after = disk_available(home)
    return (1 if any(result.errors for result in results) else 0), results, before, after


def run_cleanup(home, data_home, cache_home, dry_run, tmp_root=None, system_wide=True):
    if dry_run:
        return _run_cleanup_unlocked(home, data_home, cache_home, dry_run, tmp_root, system_wide)
    root_fd = lock_fd = None
    try:
        root_fd = open_directory(home)
        lock_fd = os.open('.hermes-clean-system.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
        s = os.fstat(lock_fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.geteuid() or s.st_nlink != 1 or s.st_mode & 0o077:
            raise Preserved('unsafe cleanup lock preserved')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run_cleanup_unlocked(home, data_home, cache_home, dry_run, tmp_root, system_wide)
    except BlockingIOError:
        r = TargetResult('Cleanup run lock'); r.errors.append('Another cleanup is running; no cleanup started')
        return 75, [r], None, None
    except OSError as exc:
        r = TargetResult('Cleanup run lock'); r.errors.append(f'Cleanup did not start: {exc}')
        return 1, [r], None, None
    finally:
        if lock_fd is not None: os.close(lock_fd)
        if root_fd is not None: os.close(root_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely expire old caches and Trash entries.")
    parser.add_argument("--dry-run", action="store_true", help="show eligible items without deleting them")
    parser.add_argument(
        "--home",
        type=Path,
        help="isolated home override for fixture testing; scheduled runs must omit this option",
    )
    args = parser.parse_args(argv)

    if args.home is not None:
        home = args.home.expanduser().absolute()
        if not path_is_real_directory(home):
            print(f"ERROR: isolated home does not exist as a real directory: {home}", file=sys.stderr)
            return 2
        data_home = home / ".local" / "share"
        cache_home = home / ".cache"
        tmp_root = home / "tmp"
        system_wide = False
    else:
        home = Path.home()
        data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", str(home / ".cache")))
        tmp_root = Path("/tmp")
        system_wide = True

    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    mode = "DRY RUN — no files will be removed" if args.dry_run else "CLEANUP — conservative retention enabled"
    exit_code, results, before, after = run_cleanup(home, data_home, cache_home, args.dry_run, tmp_root, system_wide)

    print("🧹 **Hermes 12-hour disk cleanse**")
    print(f"• Checked: {now}")
    print(f"• Mode: **{mode}**")
    print(f"• Policy: /tmp **{TMP_DAYS}d** · package caches and logs **{CACHE_DAYS}d** · Trash, browser and media caches **{RETENTION_DAYS}d**; in-use files are never touched")
    if before is not None and after is not None:
        low = "  ⚠️ LOW" if after < LOW_SPACE_BYTES else ""
        print(f"• Root filesystem free before/after: {format_bytes(before)} → {format_bytes(after)}{low}")
    print("")
    print("**Areas checked**")
    total_estimated = 0
    total_removed = 0
    for result in results:
        total_estimated += result.estimated_bytes
        total_removed += result.removed
        if result.skipped:
            detail = f"⏭️ {result.skipped}"
        elif result.errors:
            detail = f"⚠️ {len(result.errors)} issue(s); see details below"
        elif result.warnings:
            detail = f"⚠️ {len(result.warnings)} item(s) preserved for review"
        elif result.note:
            detail = result.note
        elif args.dry_run:
            detail = f"{result.eligible} eligible item(s), about {format_bytes(result.estimated_bytes)}"
        else:
            detail = f"{result.removed} item(s) removed, about {format_bytes(result.removed_bytes)}"
        if result.in_use and not result.skipped:
            detail += f" ({result.in_use} in use or shared, left alone)"
        print(f"• {result.label}: {detail}")
        for error in result.errors[:10]:
            print(f"  • ⚠️ {error}")
        for warning in result.warnings[:10]:
            print(f"  • ⚠️ {warning}")
        if len(result.errors) > 10:
            print(f"  • … {len(result.errors) - 10} additional issue(s) omitted")
        if len(result.warnings) > 10:
            print(f"  • … {len(result.warnings) - 10} additional preserved item(s) omitted")

    print("")
    if args.dry_run:
        eligible = sum(result.eligible for result in results)
        print(f"**Dry-run total:** {eligible} eligible item(s), approximately {format_bytes(total_estimated)}")
    elif exit_code == 0:
        removed_bytes = sum(result.removed_bytes for result in results)
        print(f"**Completed:** {total_removed} item(s) removed; file data removed {format_bytes(removed_bytes)}")
    else:
        removed_bytes = sum(result.removed_bytes for result in results)
        print(f"**Completed with errors:** {total_removed} complete item(s) removed; confirmed removed data {format_bytes(removed_bytes)}")
        partial = sum(result.partial_removals for result in results)
        if partial:
            print(f"• {partial} interrupted recursive deletion(s): additional removed bytes are unknown; remaining data/metadata was preserved where possible.")
    print("• Nix generations, Hermes sessions/state, reports and sandboxes are never touched.")
    print("• Free-space change is informational; filesystem activity can affect the measurement.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
