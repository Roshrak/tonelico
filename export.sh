#!/usr/bin/env bash
# Refresh this repository from the live laptop.
#
#   ./export.sh            copy everything, scrub it, run the secret checks
#   ./export.sh --no-check skip the secret checks (never push after this)
#
# Only paths named in manifest/ and in this file are copied. Nothing is
# committed or pushed: review `git status` first, then commit yourself.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
. "$REPO/scripts/common.sh"

H="${EXPORT_HOME:-$HOME}"
NIXOS_SRC="${EXPORT_NIXOS:-/etc/nixos}"
HERMES="$H/.hermes"
RUN_CHECK=1
[ "${1:-}" = "--no-check" ] && RUN_CHECK=0

need rsync
need jq
need git
[ -d "$NIXOS_SRC" ] || die "$NIXOS_SRC not found"

# Files copied out of the Nix store are read-only; make a tree writable before removing it.
clean() { [ -e "$1" ] || return 0; chmod -R u+w -- "$1"; rm -rf -- "$1"; }

# Secret values that must never appear in the repo, replaced by placeholders.
env_value() { [ -f "$1" ] && sed -n "s/^$2=//p" "$1" | head -n1 | sed -e 's/^"//' -e 's/"$//' || true; }
TELEGRAM_UID="$(env_value "$HERMES/.env" TELEGRAM_ALLOWED_USERS | cut -d, -f1)"

# --- 1. NixOS configuration ------------------------------------------------
step "nixos/  <-  $NIXOS_SRC"
mkdir -p "$REPO/nixos"
rsync -a --chmod=u+rwX,go+rX --delete --exclude-from="$REPO/manifest/nixos.exclude" "$NIXOS_SRC"/ "$REPO/nixos"/
rsync -a --chmod=u+rwX,go+rX "$REPO/overlay/nixos"/ "$REPO/nixos"/

host_nix="$REPO/nixos/hosts/tonelico/host.nix"
[ -f "$host_nix" ] || die "hosts/tonelico/host.nix is missing from $NIXOS_SRC"
# A fresh machine does not have this laptop's recovery generations in its store.
sed -i 's/retainLocalRecovery = true;/retainLocalRecovery = false;/' "$host_nix"
grep -q 'retainLocalRecovery = false;' "$host_nix" || die "could not disable retainLocalRecovery in host.nix"
if ! grep -q 'tonelico-restore.nix' "$host_nix"; then
  sed -i 's|^\([[:space:]]*\)\./keyboard\.nix|&\n\1../../modules/nixos/features/tonelico-restore.nix|' "$host_nix"
  grep -q 'tonelico-restore.nix' "$host_nix" || die "could not register tonelico-restore.nix in host.nix"
fi

# --- 2. Theme, desktop settings and wallpapers -----------------------------
step "home/  <-  $H (allowlist: manifest/home.list)"
clean "$REPO/home"
mkdir -p "$REPO/home"
while IFS= read -r entry; do
  if [ ! -e "$H/$entry" ] && [ ! -L "$H/$entry" ]; then
    warn "not present on this machine, skipped: $entry"
    continue
  fi
  if [ -L "$H/$entry" ]; then
    info "symlink (managed elsewhere), skipped: $entry"
    continue
  fi
  # Symlinks that end in /nix/store belong to Home Manager and are rebuilt by
  # it. Symlinks between user files (for example the Noctalia profiles that
  # share ~/.local/state/noctalia) are part of the setup and are kept.
  excl="$(mktemp)"
  cp -- "$REPO/manifest/home.exclude" "$excl"
  if [ -d "$H/$entry" ]; then
    while IFS= read -r -d '' link; do
      case "$(readlink -f -- "$link" 2>/dev/null || true)" in
        /nix/store/*) printf '/%s\n' "${link#"$H"/}" >> "$excl" ;;
      esac
    done < <(find "$H/$entry" -type l -print0)
  fi
  (cd "$H" && rsync -a --chmod=u+rwX,go+rX --relative --prune-empty-dirs --exclude-from="$excl" -- "./$entry" "$REPO/home/")
  rm -f "$excl"
done < <(manifest_entries "$REPO/manifest/home.list")

# Remove links whose target did not make it into the export (caches that the
# application recreates), and assert that no Nix-store link slipped through.
while IFS= read -r -d '' link; do
  target="$(readlink -- "$link")"
  case "$target" in
    "$H"/*) resolved="$REPO/home/${target#"$H"/}" ;;
    /*)     resolved="" ;;
    *)      resolved="$(dirname -- "$link")/$target" ;;
  esac
  if [ -n "$resolved" ] && [ ! -e "$resolved" ]; then
    info "dropped dangling link: ${link#"$REPO"/home/}"
    rm -f -- "$link"
  fi
done < <(find "$REPO/home" -type l -print0)
if [ -n "$(find "$REPO/home" -type l -lname '/nix/store/*' -print -quit)" ]; then
  die "a Nix-store symlink reached home/; refusing to continue"
fi

# --- 3. AGY Control ---------------------------------------------------------
step "agents/agy-control-mcp"
src="$H/agy-control-mcp"
[ -d "$src/.git" ] || die "$src is not a git checkout"
clean "$REPO/agents/agy-control-mcp"
mkdir -p "$REPO/agents/agy-control-mcp"
# Tracked plus untracked-but-not-ignored files: the working tree as it is now,
# without node_modules, dist/ or anything the repo's .gitignore excludes.
(cd "$src" && git ls-files -z -c -o --exclude-standard | while IFS= read -r -d '' f; do
  [ -e "$f" ] && [ ! -L "$f" ] && printf '%s\0' "$f"
done) | rsync -a --chmod=u+rwX,go+rX --from0 --files-from=- "$src"/ "$REPO/agents/agy-control-mcp"/

# --- 4. Software Factory (softfac) -----------------------------------------
step "agents/softfac"
sf="$REPO/agents/softfac"
clean "$sf"
mkdir -p "$sf/lib" "$sf/bin"
for f in "$H"/.local/lib/*.py; do cp -p -- "$f" "$sf/lib/"; done
chmod 644 "$sf"/lib/*.py
for f in hermes-code-factory hermes-code-factory-v2; do
  [ -f "$H/.local/bin/$f" ] && cp -p -- "$H/.local/bin/$f" "$sf/bin/"
done
proj="$H/Projects/hermes-softfac-linux"
if [ -d "$proj" ]; then
  rsync -a --chmod=u+rwX,go+rX --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='lib/' --exclude='bin/' \
    --exclude='.pytest_cache' "$proj"/ "$sf"/
fi
if [ -d "$HERMES/software-factory" ]; then
  mkdir -p "$sf/hermes-software-factory"
  rsync -a --chmod=u+rwX,go+rX --no-links --exclude='runs/' --exclude='*.log' --exclude='*.pdf' --exclude='paper_text.txt' --exclude='__pycache__' --exclude='*.pyc' \
    "$HERMES/software-factory"/ "$sf/hermes-software-factory"/
fi

# --- 5. Hermes agent --------------------------------------------------------
step "agents/hermes"
hm="$REPO/agents/hermes"
clean "$hm"
mkdir -p "$hm/scripts" "$hm/plugins"
cp -p -- "$HERMES/SOUL.md" "$HERMES/config.yaml" "$hm/"
rsync -a --chmod=u+rwX,go+rX --no-links \
  --exclude='.hub/' --exclude='.curator_backups/' --exclude='.usage.json*' --exclude='.locks/' \
  --exclude='__pycache__' --exclude='*.pyc' \
  "$HERMES/skills"/ "$hm/skills"/
rsync -a --chmod=u+rwX,go+rX --no-links --exclude='__pycache__' --exclude='*.pyc' "$HERMES/plugins"/ "$hm/plugins"/
cp -p -- "$HERMES/scripts/clean-system.py" "$hm/scripts/"
# Scheduled jobs: only the definition, never run history. The Drive wallpaper
# sync job is left out because it depends on a personal Google Drive login.
jq '[.jobs[]
     | select(.name != "Google Drive Wallpaper Sync")
     | {name, script, no_agent, schedule: .schedule.display, deliver}]' \
  "$HERMES/cron/jobs.json" > "$hm/cron-jobs.json"

# --- 6. Antigravity rotator (Docker) ----------------------------------------
step "agents/antigravity-manager"
am="$REPO/agents/antigravity-manager"
clean "$am"
mkdir -p "$am"
cp -p -- "$H/agm-docker/compose.yml" "$am/"
{
  git -C "$H/agm-docker/src" remote get-url origin
  git -C "$H/agm-docker/src" rev-parse HEAD
} > "$am/UPSTREAM"

# --- 7. Helper scripts, systemd units, client instructions ------------------
step "agents/bin, agents/systemd, agents/clients"
mkdir -p "$REPO/agents/bin" "$REPO/agents/systemd" "$REPO/agents/clients"
rm -f "$REPO"/agents/bin/* "$REPO"/agents/systemd/* "$REPO"/agents/clients/*
for f in agy_telegram_bot.py gpu_market_search.py ytmusic_control.py remote-mode slogout \
         npu-python paddleocr-mcp-local xdg-open steam; do
  if [ -f "$H/.local/bin/$f" ] && [ ! -L "$H/.local/bin/$f" ]; then
    cp -p -- "$H/.local/bin/$f" "$REPO/agents/bin/"
  fi
done
cp -p -- "$H/.config/systemd/user/agy-telegram.service" "$REPO/agents/systemd/"
sed -E 's#/nix/store/[a-z0-9]{32}-hermes-agent-env#@HERMES_ENV@#g' \
  "$H/.config/systemd/user/hermes-gateway.service" > "$REPO/agents/systemd/hermes-gateway.service"
[ -f "$H/.claude/CLAUDE.md" ] && cp -p -- "$H/.claude/CLAUDE.md" "$REPO/agents/clients/CLAUDE.md"
[ -f "$H/AGENTS.md" ] && cp -p -- "$H/AGENTS.md" "$REPO/agents/clients/AGENTS.md"

# --- 8. Replace personal identifiers with placeholders ----------------------
if [ -n "$TELEGRAM_UID" ]; then
  step "placeholders: Telegram user id -> @TELEGRAM_USER_ID@"
  grep -rIlF -- "$TELEGRAM_UID" "$REPO/agents" "$REPO/nixos" "$REPO/home" 2>/dev/null \
    | while IFS= read -r f; do sed -i "s/$TELEGRAM_UID/@TELEGRAM_USER_ID@/g" "$f"; info "$f"; done || true
fi

# --- 9. Checks --------------------------------------------------------------
if [ "$RUN_CHECK" = 1 ]; then
  "$REPO/scripts/check-secrets.sh"
else
  warn "secret checks skipped. Do not push this tree."
fi

step "export finished"
du -sh "$REPO"/{nixos,home,agents} | sed 's/^/    /' >&2
