"""Disposable Linux filesystem and credential boundary for the AGY CLI.

The host keyring is queried for AGY's one OAuth item.  A private Secret
Service is populated inside a Bubblewrap PID/mount namespace; neither the
host session bus nor the host home directory is visible to the builder.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from typing import Iterator


class LinuxBoundaryError(RuntimeError):
    pass


def _store_binary(name: str, glob: str | None = None) -> Path:
    found = shutil.which(name)
    candidates = [Path(found).resolve()] if found else []
    if glob:
        candidates.extend(sorted(Path("/nix/store").glob(glob)))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK) and "/nix/store/" in str(candidate):
            return candidate
    raise LinuxBoundaryError(f"required Nix-store executable is unavailable: {name}")


def _approved_oauth_token(secret_tool: Path) -> bytes:
    try:
        result = subprocess.run(
            [str(secret_tool), "lookup", "service", "gemini", "username", "antigravity"],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LinuxBoundaryError("AGY OAuth credential lookup failed") from exc
    data = result.stdout.strip()
    if result.returncode or not data or len(data) > 64 * 1024:
        raise LinuxBoundaryError("AGY OAuth credential is unavailable or malformed")
    try:
        payload = json.loads(data)
    except (UnicodeError, ValueError) as exc:
        raise LinuxBoundaryError("AGY OAuth credential is malformed") from exc
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, dict) or not isinstance(token.get("access_token"), str) or not token["access_token"]:
        raise LinuxBoundaryError("AGY OAuth credential has no access token")
    return data


@contextmanager
def linux_agy_command(workspace: Path, agy_executable: Path, agy_args: list[str]) -> Iterator[tuple[list[str], dict[str, str]]]:
    """Yield a bounded AGY command; destroy the one-item guest keyring after use."""
    if not workspace.is_dir() or workspace.is_symlink():
        raise LinuxBoundaryError("disposable AGY workspace is unavailable")
    bwrap = _store_binary("bwrap")
    bash = _store_binary("bash")
    dbus = _store_binary("dbus-run-session")
    keyring = _store_binary("gnome-keyring-daemon", "*-gnome-keyring-*/bin/gnome-keyring-daemon")
    secret_tool = _store_binary("secret-tool", "*-libsecret-*/bin/secret-tool")
    if not agy_executable.is_file() or not os.access(agy_executable, os.X_OK):
        raise LinuxBoundaryError("pinned AGY executable is unavailable")
    token = _approved_oauth_token(secret_tool)

    with tempfile.TemporaryDirectory(prefix="softfac-linux-boundary-") as raw_root:
        root = Path(raw_root)
        token_file = root / "oauth-item.json"
        token_file.write_bytes(token)
        token_file.chmod(0o600)
        passwd = root / "passwd"
        passwd.write_text(f"agy:x:{os.getuid()}:{os.getgid()}:AGY:/home/agy:/bin/sh\n", encoding="utf-8")
        group = root / "group"
        group.write_text(f"agy:x:{os.getgid()}:\n", encoding="utf-8")
        entry = root / "entry.sh"
        entry.write_text(
            "set -euo pipefail\n"
            "printf '\\n' | " + shlex.quote(str(keyring)) + " --login --components=secrets --control-directory /run/agy/keyring >/dev/null\n"
            + shlex.quote(str(keyring)) + " --start --components=secrets --control-directory /run/agy/keyring >/dev/null\n"
            + shlex.quote(str(secret_tool)) + " store --label='SoftFac AGY credential' service gemini username antigravity < /auth/oauth-item.json\n"
            "exec \"$@\"\n",
            encoding="utf-8",
        )
        entry.chmod(0o600)

        tool_names = ("git", "rg", "python3", "cat", "ls", "find", "sed", "head", "tail")
        tool_dirs = []
        for name in tool_names:
            try:
                tool_dirs.append(str(_store_binary(name).parent))
            except LinuxBoundaryError:
                continue
        path = ":".join(dict.fromkeys([*(str(item.parent) for item in (bash, dbus, keyring, secret_tool, agy_executable)), *tool_dirs]))
        command = [
            str(bwrap), "--unshare-all", "--share-net", "--die-with-parent",
            "--tmpfs", "/", "--dir", "/nix", "--ro-bind", "/nix/store", "/nix/store",
            "--proc", "/proc", "--dev", "/dev", "--dir", "/tmp",
            "--dir", "/workspace", "--bind", str(workspace), "/workspace",
            "--dir", "/auth", "--ro-bind", str(token_file), "/auth/oauth-item.json",
            "--ro-bind", str(entry), "/entry.sh", "--dir", "/home", "--dir", "/home/agy",
            "--dir", "/run", "--dir", "/run/agy", "--dir", "/etc",
            "--ro-bind", "/etc/dbus-1", "/etc/dbus-1",
            "--ro-bind", str(passwd), "/etc/passwd", "--ro-bind", str(group), "/etc/group",
            "--dir", "/etc/ssl", "--dir", "/etc/ssl/certs",
            "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
            "--ro-bind", "/etc/hosts", "/etc/hosts",
            "--ro-bind", "/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/certs/ca-certificates.crt",
            "--setenv", "HOME", "/home/agy", "--setenv", "XDG_RUNTIME_DIR", "/run/agy",
            "--setenv", "SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "PYTHONPYCACHEPREFIX", "/tmp/pycache",
            "--setenv", "PYTEST_ADDOPTS", "-o cache_dir=/tmp/pytest-cache",
            "--setenv", "XDG_CACHE_HOME", "/tmp/cache",
            "--setenv", "PATH", path, "--chdir", "/workspace",
        ]
        guest_agy = str(agy_executable)
        if not guest_agy.startswith("/nix/store/"):
            command.extend(["--ro-bind", guest_agy, "/agy"])
            guest_agy = "/agy"
        command.extend([str(dbus), "--", str(bash), "/entry.sh", guest_agy, *agy_args])
        environment = {
            "PATH": path,
            "HOME": "/home/agy",
            "LANG": "C.UTF-8",
            "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": "/tmp/pycache",
            "PYTEST_ADDOPTS": "-o cache_dir=/tmp/pytest-cache",
            "XDG_CACHE_HOME": "/tmp/cache",
        }
        yield command, environment
