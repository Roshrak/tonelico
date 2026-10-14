"""Security and integrity validation for Hermes Code Factory v2."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable, Set, Tuple


class FactoryError(RuntimeError):
    """Expected factory failure with a stable category."""

    def __init__(self, message: str, category: str = "failed") -> None:
        super().__init__(message)
        self.category = category


class SecurityError(FactoryError):
    """Raised when a security invariant or boundary is violated."""

    def __init__(self, message: str, category: str = "scope") -> None:
        super().__init__(message, category=category)


ALWAYS_FORBIDDEN = [
    re.compile(r"(^|/)\.git(?:/|$)", re.I),
    re.compile(r"(^|/)\.env(?:\..+)?$", re.I),
    re.compile(r"(^|/)\.ssh(?:/|$)", re.I),
    re.compile(r"(^|/)\.aws(?:/|$)", re.I),
    re.compile(r"(^|/)\.gnupg(?:/|$)", re.I),
    re.compile(r"(^|/)\.(?:netrc|npmrc|pypirc|dockercfg)$", re.I),
    re.compile(r"(^|/)\.docker(?:/|$)", re.I),
    re.compile(r"(^|/)\.kube(?:/|$)", re.I),
    re.compile(r"(^|/)\.(?:gitconfig|git-credentials)$", re.I),
    re.compile(r"(^|/)\.(?:azure|gcloud)(?:/|$)", re.I),
    re.compile(r"(^|/)\.vault-token$", re.I),
    re.compile(r"(^|/)\.cargo/(?:credentials(?:\.toml)?|config(?:\.toml)?)$", re.I),
    re.compile(r"(^|/)\.terraform(?:\.d)?(?:/|$)", re.I),
    re.compile(r"(^|/)\.(?:bashrc|bash_profile|zshrc|profile|bash_history|zsh_history)$", re.I),
    re.compile(r"(^|/)\.(?:htpasswd|s3cfg|yarnrc(?:\.ya?ml)?)$", re.I),
    re.compile(r"\.(?:pem|pfx|p12|key|keystore|jks|ovpn)$", re.I),
    re.compile(r"(^|/).*?(?:secret|credential|private[_-]?key).*?(?:/|$|\.)", re.I),
    re.compile(r"(^|/)id_(?:rsa|ed25519|dsa|ecdsa)(?:\.pub)?$", re.I),
]

SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY(?: BLOCK)?-----[\s\S]*?-----END (?:[A-Z0-9_-]+ )?PRIVATE KEY(?: BLOCK)?-----", re.I)),
    ("authorization_header", re.compile(r"((?:authorization|proxy-authorization)\s*:\s*(?:bearer\s+)?)[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("api_key", re.compile(r"((?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|client[_-]?secret|auth[_-]?token|secret[_-]?key|password)\s*[:=]\s*['\"]?)[A-Za-z0-9._~+/=-]{8,}['\"]?", re.I)),
    ("service_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{82}|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,40}|hf_[A-Za-z0-9]{34}|npm_[A-Za-z0-9]{36}|pypi-[A-Za-z0-9_-]{50,}|(?:sk|pk)_(?:live|test)_[0-9a-zA-Z]{24,99}|SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}|SK[0-9a-fA-F]{32}|[MN][A-Za-z\d]{23,26}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,38})\b")),
    ("slack_webhook", re.compile(r"https://hooks\.slack\.com/services/T[A-Za-z0-9_]+/B[A-Za-z0-9_]+/[A-Za-z0-9_]+")),
    ("telegram_token", re.compile(r"\b[0-9]{8,10}:[A-Za-z0-9_-]{30,40}\b")),
]


def is_forbidden_path(normalized_path: str) -> bool:
    """Check if normalized path matches any sensitive pattern."""
    for pattern in ALWAYS_FORBIDDEN:
        if pattern.search(normalized_path):
            return True
    return False


def normalize_path(raw: str) -> str:
    """Validate and normalize a repository-relative path with strict security checks."""
    if not isinstance(raw, str):
        raise SecurityError("file paths must be strings", "contract")
    if re.search(r"[\x00-\x1f\x7f]", raw):
        raise SecurityError(f"file path contains control characters: {raw!r}", "contract")
    value = raw.strip().replace("\\", "/")
    if not value:
        raise SecurityError("file path must not be empty", "contract")
    if re.match(r"^[A-Za-z]:", value):
        raise SecurityError(f"Windows drive letter paths are not allowed: {raw!r}", "contract")
    if value.startswith("/"):
        raise SecurityError(f"absolute paths are not allowed: {raw!r}", "contract")
    if value.endswith("/"):
        raise SecurityError(f"file paths must not end with a slash: {raw!r}", "contract")
    path = PurePosixPath(value)
    if not path.parts or ".." in path.parts or ".git" in path.parts:
        raise SecurityError(f"unsafe repository-relative path: {raw!r}", "contract")
    dos_pattern = re.compile(r"^(?:CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
    for part in path.parts:
        if dos_pattern.match(part):
            raise SecurityError(f"DOS device names are forbidden: {raw!r}", "contract")
        if ":" in part:
            raise SecurityError(f"file path contains forbidden colon: {raw!r}", "contract")
        if part.endswith(" ") or (part.endswith(".") and part not in {".", ".."}):
            raise SecurityError(f"file path components must not end with spaces or dots: {raw!r}", "contract")
    normalized = path.as_posix()
    if normalized in {".", ".git"}:
        raise SecurityError(f"unsafe repository-relative path: {raw!r}", "contract")
    if is_forbidden_path(normalized):
        raise SecurityError(f"sensitive path is not allowed: {normalized!r}", "scope")
    return normalized


def normalized_paths(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = normalize_path(value)
        if path not in seen:
            result.append(path)
            seen.add(path)
    if not result:
        raise SecurityError("at least one allowed file is required", "contract")
    return result


def assert_safe_parent_chain(root: Path, relative_path: str) -> None:
    """Ensure no parent directory in the path is a symlink or non-directory."""
    resolved_root = root.resolve()
    current = resolved_root
    parts = PurePosixPath(relative_path).parts[:-1]
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise SecurityError(f"parent directory in path is a symlink: {current.relative_to(resolved_root)}", "scope")
        if current.exists() and not current.is_dir():
            raise SecurityError(f"parent component in path is not a directory: {current.relative_to(resolved_root)}", "scope")


def ensure_paths_confined(repo: Path, paths: Iterable[str]) -> None:
    """Reject directories, non-regular files, symlinks, and directory escapes."""
    root = repo.resolve()
    for relative in paths:
        candidate = repo / relative
        if candidate.is_symlink():
            raise SecurityError(f"allowed path may not be a symlink: {relative}", "scope")
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(root)
        except ValueError as exc:
            raise SecurityError(f"allowed path escapes repository through a symlink: {relative}", "scope") from exc
        assert_safe_parent_chain(repo, relative)
        if candidate.exists():
            if candidate.is_dir():
                raise SecurityError(f"allowed path is a directory, not a file: {relative}", "scope")
            if not candidate.is_file():
                raise SecurityError(f"allowed path is not a regular file: {relative}", "scope")


def ensure_head_paths_not_symlinks(repo: Path, paths: Iterable[str]) -> None:
    """Reject files that are symlinks or submodules in the committed HEAD snapshot."""
    if not (repo / ".git").exists():
        return
    seen_candidates: set[str] = set()
    for relative in paths:
        parts = PurePosixPath(relative).parts
        prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
        for candidate in prefixes:
            if candidate in seen_candidates:
                continue
            seen_candidates.add(candidate)
            try:
                proc = subprocess.run(
                    ["git", "ls-tree", "HEAD", "--", candidate],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=30,
                )
                entry = proc.stdout.strip()
                if entry:
                    for line in entry.splitlines():
                        mode = line.split(maxsplit=1)[0]
                        if mode == "120000":
                            raise SecurityError(f"allowed path is a symlink in HEAD: {candidate}", "scope")
                        if mode == "160000":
                            raise SecurityError(f"allowed path is a submodule in HEAD: {candidate}", "scope")
            except subprocess.SubprocessError:
                pass


def redact_secrets(text: str) -> Tuple[str, Set[str]]:
    """Redact known secret patterns and return detected secret labels."""
    detected_labels: Set[str] = set()
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            detected_labels.add(label)
    cleaned = text
    for label, pattern in SECRET_PATTERNS:
        if label in detected_labels:
            if label == "authorization_header":
                cleaned = pattern.sub(r"\1[REDACTED]", cleaned)
            elif label == "api_key":
                cleaned = pattern.sub(r"\1[REDACTED]", cleaned)
            elif label == "private_key":
                cleaned = pattern.sub("[REDACTED PRIVATE KEY]", cleaned)
            else:
                cleaned = pattern.sub("[REDACTED TOKEN]", cleaned)
    return cleaned, detected_labels


def scan_patch_for_secrets(patch_content: str) -> Set[str]:
    """Inspect patch diff lines for secret leakage."""
    detected: Set[str] = set()
    added_lines: list[str] = []
    for line in patch_content.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            if re.search(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY(?: BLOCK)?-----", content, re.I):
                detected.add("private_key")
            added_lines.append(content)
            _, labels = redact_secrets(content)
            detected.update(labels)
    if added_lines:
        _, multi_labels = redact_secrets("\n".join(added_lines))
        detected.update(multi_labels)
    return detected


def unquote_git_path(raw: str) -> str:
    """Decode Git C-style quoted and octal-escaped paths."""
    s = raw.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    if "\\" in s:
        try:
            import codecs
            decoded_bytes, _ = codecs.escape_decode(s.encode("latin-1"))
            return decoded_bytes.decode("utf-8")
        except Exception:
            return s
    return s


def parse_diff_git_header(rest: str) -> tuple[str, str] | None:
    """Parse git diff line rest (a/... b/...) handling spaces and octal quotes."""
    if '"' in rest:
        import shlex
        try:
            toks = shlex.split(rest)
            if len(toks) == 2:
                return toks[0], toks[1]
        except Exception:
            pass
    # If unquoted, check if paths are symmetric (a/<P> b/<P>)
    if rest.startswith("a/"):
        target = " b/"
        idx = -1
        while True:
            idx = rest.find(target, idx + 1)
            if idx == -1:
                break
            p1 = rest[:idx]
            p2 = rest[idx + 1:]
            if p1.startswith("a/") and p2.startswith("b/") and p1[2:] == p2[2:]:
                return p1, p2
    idx = rest.rfind(" b/")
    if idx != -1:
        p1 = rest[:idx]
        p2 = rest[idx + 1:]
        if p1.startswith("a/") and p2.startswith("b/"):
            return p1, p2
    match_std = re.match(r"^a/(.*?) b/(.*?)$", rest)
    if match_std:
        return "a/" + match_std.group(1), "b/" + match_std.group(2)
    return None


def patch_paths(patch_content: str) -> list[str]:
    """Parse diff headers to extract all target paths and verify mode changes."""
    paths: set[str] = set()
    for line in patch_content.splitlines():
        if re.search(r"^(?:new file mode|old mode|new mode|deleted file mode)\s+(?:120000|160000)$", line.strip()):
            raise SecurityError("patch attempts to create or alter symlinks or submodules", "security")
        line_s = line.strip()
        if line_s.startswith("diff --git "):
            rest = line_s[11:].strip()
            parts = parse_diff_git_header(rest)
            if parts:
                old_p = unquote_git_path(parts[0])
                new_p = unquote_git_path(parts[1])
                if old_p.startswith("a/"):
                    old_p = old_p[2:]
                if new_p.startswith("b/"):
                    new_p = new_p[2:]
                if old_p and old_p != "/dev/null":
                    paths.add(normalize_path(old_p))
                if new_p and new_p != "/dev/null":
                    paths.add(normalize_path(new_p))
        elif line_s.startswith("--- ") and not line_s.startswith("--- /dev/null"):
            p = unquote_git_path(line_s[4:].split("\t")[0].strip())
            if p.startswith("a/"):
                p = p[2:]
            if p and p != "/dev/null":
                try:
                    paths.add(normalize_path(p))
                except Exception:
                    pass
        elif line_s.startswith("+++ ") and not line_s.startswith("+++ /dev/null"):
            p = unquote_git_path(line_s[4:].split("\t")[0].strip())
            if p.startswith("b/"):
                p = p[2:]
            if p and p != "/dev/null":
                try:
                    paths.add(normalize_path(p))
                except Exception:
                    pass
    return sorted(paths)


def assert_safe_patch_targets(repo_root: Path, patch_content: str) -> list[str]:
    """Validate that all patch paths are safe and targets/parents are not symlinks."""
    paths = patch_paths(patch_content)
    for rel_path in paths:
        assert_safe_parent_chain(repo_root, rel_path)
        target = repo_root / rel_path
        if target.is_symlink():
            raise SecurityError(f"patch target is a symlink: {rel_path}", "security")
    return paths


def assert_no_untracked_collisions(repo_root: Path, changed_paths: Iterable[str]) -> None:
    """Ensure patch targets do not collide with untracked files in the working directory."""
    if not (repo_root / ".git").exists():
        return
    paths = [p for p in changed_paths if p]
    if not paths:
        return
    BATCH_SIZE = 100
    for i in range(0, len(paths), BATCH_SIZE):
        batch = paths[i : i + BATCH_SIZE]
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--others", "--exclude-standard", "--", *batch],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            colliding = [p for p in proc.stdout.split("\0") if p]
            if colliding:
                raise SecurityError(f"patch target collides with untracked file: {colliding[0]}", "isolation")
