"""Snapshot workspace isolation, baseline tracking, drift detection, and collision prevention."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from factory_security import (
    ALWAYS_FORBIDDEN,
    SecurityError,
    assert_no_untracked_collisions,
    assert_safe_parent_chain,
    assert_safe_patch_targets,
    is_forbidden_path,
    normalize_path,
)

MAX_FILES = 20_000
MAX_BYTES = 512 * 1024 * 1024
MAX_DEPTH = 128

EXCLUDED_DIR_NAMES = {
    ".git",
    ".ssh",
    ".aws",
    ".gnupg",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "dist-test",
    "build",
    "coverage",
    ".cache",
    ".next",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".gradle",
    ".turbo",
    ".parcel-cache",
    ".tox",
    ".nox",
    ".yarn",
    ".pnpm-store",
    ".dart_tool",
    ".bundle",
}


class SnapshotError(SecurityError):
    """Raised when snapshot creation, baseline validation, or apply fails."""
    def __init__(self, message: str, category: str = "snapshot") -> None:
        super().__init__(message, category=category)


@dataclass
class SnapshotBaseline:
    files: dict[str, dict[str, Any]]
    directories: list[str]
    fingerprint: str
    base_commit: str


def is_excluded_from_snapshot(relative_path: str) -> bool:
    """Check if relative path matches any directory, credential, or cache exclusions."""
    normalized = relative_path.replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    segments = [s for s in normalized.split("/") if s]
    if not segments:
        return False

    for i, segment in enumerate(segments):
        is_last = (i == len(segments) - 1)
        seg_lower = segment.lower()
        if seg_lower in EXCLUDED_DIR_NAMES:
            return True
        if is_forbidden_path(segment) or is_forbidden_path(normalized):
            return True
        if is_last:
            if seg_lower.startswith("id_") and (seg_lower.endswith(".pub") or "rsa" in seg_lower or "ed25519" in seg_lower):
                return True
            for ext in (".pem", ".key", ".pfx", ".p12"):
                if seg_lower.endswith(ext):
                    return True

    return False


def bounded_file_digest(file_path: Path) -> dict[str, Any]:
    """Calculate SHA256, size, and mode without following symlinks."""
    if file_path.is_symlink():
        raise SnapshotError(f"file is a symlink: {file_path}")

    # Use O_NOFOLLOW if available
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(str(file_path), flags)
    except OSError as exc:
        raise SnapshotError(f"could not open file safely: {file_path}: {exc}") from exc

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SnapshotError(f"target is not a regular file: {file_path}")
        if st.st_nlink > 1:
            raise SnapshotError(f"hard-linked files are refused: {file_path}")
        if st.st_size > MAX_BYTES:
            raise SnapshotError(f"file exceeds {MAX_BYTES} bytes: {file_path}")

        hasher = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as f:
            while chunk := f.read(1024 * 1024):
                hasher.update(chunk)
        return {
            "sha256": hasher.hexdigest(),
            "size": st.st_size,
            "mode": st.st_mode & 0o777,
        }
    finally:
        os.close(fd)


def copy_workspace_tree(source_root: Path, destination_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Safely copy workspace files into destination, calculating baseline digests."""
    files: dict[str, dict[str, Any]] = {}
    directories: set[str] = set()
    total_bytes = 0
    resolved_source = source_root.resolve()

    def walk_and_copy(current_dir: Path, rel_dir: str = "") -> None:
        nonlocal total_bytes
        try:
            entries = sorted(os.scandir(current_dir), key=lambda e: e.name)
        except OSError as exc:
            raise SnapshotError(f"could not read directory: {current_dir}: {exc}") from exc

        for entry in entries:
            rel_path = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            if is_excluded_from_snapshot(rel_path):
                continue

            if entry.is_symlink():
                raise SnapshotError(f"symlinks are forbidden in snapshot mode: {rel_path}")

            if entry.is_dir(follow_symlinks=False):
                parts = rel_path.split("/")
                if len(parts) > MAX_DEPTH:
                    raise SnapshotError(f"directory depth exceeds {MAX_DEPTH}: {rel_path}")
                directories.add(rel_path)
                dest_dir = destination_root / rel_path
                dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                walk_and_copy(Path(entry.path), rel_path)
                continue

            if not entry.is_file(follow_symlinks=False):
                raise SnapshotError(f"non-regular file forbidden in snapshot mode: {rel_path}")

            if len(files) >= MAX_FILES:
                raise SnapshotError(f"file count exceeds maximum of {MAX_FILES}")

            info = bounded_file_digest(Path(entry.path))
            total_bytes += info["size"]
            if total_bytes > MAX_BYTES:
                raise SnapshotError(f"total workspace size exceeds {MAX_BYTES} bytes")

            dest_file = destination_root / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

            shutil.copy2(entry.path, dest_file, follow_symlinks=False)
            files[rel_path] = info

    walk_and_copy(resolved_source, "")
    return files, sorted(directories)


def create_snapshot_workspace(source_root: Path, destination_root: Path) -> SnapshotBaseline:
    """Create an isolated private Git repository containing a safe snapshot of source_root."""
    resolved_source = source_root.resolve()
    resolved_dest = destination_root.resolve()

    if resolved_dest == resolved_source or str(resolved_dest).startswith(f"{resolved_source}{os.sep}"):
        raise SnapshotError("snapshot destination must be outside the source workspace")
    if resolved_source == resolved_dest or str(resolved_source).startswith(f"{resolved_dest}{os.sep}"):
        raise SnapshotError("snapshot destination must not contain the source workspace")

    if not resolved_source.is_dir():
        raise SnapshotError(f"snapshot source is not a directory: {source_root}")

    if resolved_dest.exists():
        if resolved_dest.is_symlink():
            raise SnapshotError(f"snapshot destination must not be a symlink: {destination_root}")
        raise SnapshotError(f"snapshot destination must not already exist: {destination_root}")

    resolved_dest.mkdir(parents=True, mode=0o700)
    try:
        files, directories = copy_workspace_tree(resolved_source, resolved_dest)

        if not files:
            raise SnapshotError("no safe regular files found in source workspace to snapshot")

        # Initialize a private Git repo inside the snapshot destination
        def git_cmd(*args: str) -> str:
            res = subprocess.run(
                ["git", *args],
                cwd=resolved_dest,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if res.returncode != 0:
                raise SnapshotError(f"git {' '.join(args)} failed in snapshot: {(res.stderr or res.stdout).strip()}")
            return res.stdout.strip()

        git_cmd("init", "-q")
        git_cmd("add", "--all")
        git_cmd(
            "-c", "user.name=Hermes Snapshot Mode",
            "-c", "user.email=hermes-factory@localhost",
            "-c", "commit.gpgsign=false",
            "commit", "-qm", "Hermes software factory snapshot baseline"
        )
        base_commit = git_cmd("rev-parse", "HEAD")

        manifest = json.dumps({"directories": directories, "files": files}, sort_keys=True)
        fingerprint = hashlib.sha256(manifest.encode("utf-8")).hexdigest()

        return SnapshotBaseline(
            files=files,
            directories=directories,
            fingerprint=fingerprint,
            base_commit=base_commit,
        )
    except Exception:
        shutil.rmtree(resolved_dest, ignore_errors=True)
        raise


def assert_snapshot_baseline(
    source_root: Path,
    baseline: dict[str, dict[str, Any]],
    changed_paths: Iterable[str],
    baseline_directories: list[str] | None = None,
) -> None:
    """Verify that source workspace has not drifted or collided before applying candidate changes."""
    resolved_source = source_root.resolve()
    if baseline_directories is not None:
        base_dirs = set(baseline_directories)
    else:
        base_dirs = set()
        for f in baseline.keys():
            p_parts = PurePosixPath(f).parts[:-1]
            for idx in range(1, len(p_parts) + 1):
                base_dirs.add("/".join(p_parts[:idx]))

    for raw_path in changed_paths:
        rel_path = normalize_path(raw_path)
        assert_safe_parent_chain(resolved_source, rel_path)

        # Check parent directories
        parts = PurePosixPath(rel_path).parts[:-1]
        for i in range(1, len(parts) + 1):
            parent_rel = "/".join(parts[:i])
            parent_path = resolved_source / parent_rel
            if parent_rel in base_dirs:
                if not parent_path.is_dir() or parent_path.is_symlink():
                    raise SnapshotError(f"original parent directory modified or missing: {parent_rel}", "isolation")
            else:
                if parent_path.exists():
                    raise SnapshotError(f"new target parent collision: {parent_rel}", "isolation")

        source_path = resolved_source / rel_path
        expected = baseline.get(rel_path)

        if expected is None:
            # File did not exist in baseline: ensure it doesn't exist now (no collision)
            if source_path.exists() or source_path.is_symlink():
                raise SnapshotError(f"newly created file collides with existing file: {rel_path}", "isolation")
        else:
            # File existed in baseline: ensure it hasn't drifted
            if not source_path.exists():
                raise SnapshotError(f"original file was removed during run: {rel_path}", "isolation")
            if source_path.is_symlink() or not source_path.is_file():
                raise SnapshotError(f"original file changed type: {rel_path}", "isolation")

            actual = bounded_file_digest(source_path)
            if actual["sha256"] != expected["sha256"] or actual["size"] != expected["size"]:
                raise SnapshotError(f"original file modified during run (source drift): {rel_path}", "isolation")


def apply_snapshot_patch(
    source_root: Path,
    patch_content: str,
    baseline_files: dict[str, dict[str, Any]],
    changed_paths: Iterable[str],
    baseline_directories: list[str] | None = None,
) -> None:
    """Safely apply patch to source workspace after strict drift and collision checks."""
    assert_safe_patch_targets(source_root, patch_content)
    assert_snapshot_baseline(source_root, baseline_files, changed_paths, baseline_directories=baseline_directories)
    assert_no_untracked_collisions(source_root, changed_paths)

    is_git = (source_root / ".git").exists()
    if is_git:
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "--binary", "-"],
            input=patch_content,
            cwd=source_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            err_msg = (proc.stderr or proc.stdout).strip() or f"git apply failed with exit code {proc.returncode}"
            raise SnapshotError(f"git apply failed: {err_msg}", "git")
    else:
        git_env = dict(os.environ)
        git_env["GIT_CEILING_DIRECTORIES"] = str(source_root.resolve().parent)
        proc = subprocess.run(
            ["git", "apply", "--no-index", "--whitespace=nowarn", "--binary", "-"],
            input=patch_content,
            cwd=source_root,
            env=git_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            err_msg = (proc.stderr or proc.stdout).strip() or f"patch apply failed with exit code {proc.returncode}"
            raise SnapshotError(f"patch apply failed: {err_msg}", "git")
