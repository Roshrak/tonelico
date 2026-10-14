#!/usr/bin/env bash
# Turn a fresh NixOS KDE Plasma install into this laptop's setup.
#
#   ./install.sh              first run: system, theme, agent files   (then reboot)
#   ./install.sh              second run (after the reboot): services, Docker, MCP clients, checks
#   ./install.sh --post       force the second part
#
# Options:  --yes             never prompt (secrets come from the environment or are left empty)
#           --same-hardware   skip the "is this the Acer Swift SFG16-72" check
#           --skip-agents     install only the system and the theme
#           --overwrite-nixos replace an existing flake config in /etc/nixos (refused by default)
#
# Run as the normal user "aesc", not as root. sudo is used where needed.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# A fresh NixOS install has no git, rsync or jq. Re-run inside a nix shell that provides them.
if [ -z "${TONELICO_BOOTSTRAPPED:-}" ]; then
  missing=0
  for t in git rsync jq curl; do command -v "$t" >/dev/null 2>&1 || missing=1; done
  if [ "$missing" = 1 ]; then
    echo "==> fetching git, rsync, jq and curl through nix first" >&2
    export TONELICO_BOOTSTRAPPED=1
    exec nix --extra-experimental-features 'nix-command flakes' shell \
      nixpkgs#git nixpkgs#rsync nixpkgs#jq nixpkgs#curl --command "${BASH_SOURCE[0]}" "$@"
  fi
fi

# shellcheck source=scripts/common.sh
. "$REPO/scripts/common.sh"
RSYNC="$(command -v rsync)"   # sudo does not see tools that only exist in a nix shell

MODE=auto
ASSUME_YES=0
FORCE_HW=0
SKIP_AGENTS=0
OVERWRITE_NIXOS=0
for arg in "$@"; do
  case "$arg" in
    --post)          MODE=post ;;
    --yes|-y)        ASSUME_YES=1 ;;
    --same-hardware) FORCE_HW=1 ;;
    --skip-agents)   SKIP_AGENTS=1 ;;
    --overwrite-nixos) OVERWRITE_NIXOS=1 ;;
    -h|--help)       sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)               die "unknown option: $arg" ;;
  esac
done
if [ "$MODE" = auto ]; then
  if [ -e /etc/tonelico-installed ]; then MODE=post; else MODE=system; fi
fi

SECRETS="$HOME/.config/tonelico/secrets.env"
NIX_FLAGS=(--extra-experimental-features 'nix-command flakes')
RESULTS=()   # "PASS|FAIL|SKIP<TAB>description" lines for the final report
record() { RESULTS+=("$1"$'\t'"$2"); }

# ---------------------------------------------------------------------------
# Common checks
# ---------------------------------------------------------------------------
preflight() {
  step "pre-flight checks"
  [ "$(id -u)" -ne 0 ] || die "run this as your normal user, not root"
  [ "$(id -un)" = aesc ] || die "the user must be named 'aesc' (this setup contains /home/aesc paths). Create the user with that name in the installer."
  grep -q '^ID=nixos' /etc/os-release || die "this is not NixOS"
  [ -d /sys/firmware/efi ] || die "this machine did not boot in UEFI mode; the config uses systemd-boot"
  if [ "$MODE" = system ] && [ "$OVERWRITE_NIXOS" = 0 ] && [ ! -e /etc/nixos/.tonelico ] \
     && { [ -e /etc/nixos/flake.nix ] || [ -d /etc/nixos/.git ]; }; then
    die "/etc/nixos already contains a flake configuration that this installer did not create.
       This script is for a FRESH install and would replace it. Refusing.
       (If you really mean it, re-run with --overwrite-nixos; your current files are copied to /etc/nixos.pre-tonelico first.)"
  fi
  need git; need rsync; need curl; need sudo
  sudo -v || die "sudo is required"
  if [ "$MODE" = system ]; then
    curl -fsS -o /dev/null --max-time 15 https://cache.nixos.org/nix-cache-info || die "no internet (could not reach cache.nixos.org)"
    local product avail
    product="$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo unknown)"
    if [ "$product" != "Swift SFG16-72" ] && [ "$FORCE_HW" = 0 ]; then
      die "this repository is tuned for the Acer Swift SFG16-72, but this machine reports '$product'.
       Its battery-limit module, touchpad fix and NPU compiler will not fit other hardware.
       Re-run with --same-hardware only if you accept that and will edit nixos/hosts/tonelico/default.nix."
    fi
    avail="$(df --output=avail -BG /nix 2>/dev/null | tail -n1 | tr -dc '0-9')"
    if [ -n "$avail" ] && [ "$avail" -lt 40 ]; then
      die "only ${avail} GB free on /nix; the build needs about 40 GB"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Secrets: asked once, stored only on this machine
# ---------------------------------------------------------------------------
gen_secret() { head -c 24 /dev/urandom | base64 | tr -d '/+=\n' | head -c 32; }

load_secrets() {
  mkdir -p "$(dirname "$SECRETS")"
  if [ ! -f "$SECRETS" ]; then
    step "secrets (stored only in $SECRETS, never uploaded)"
    umask 077
    ask() {  # ask VAR "prompt" secret(0/1)
      local var="$1" prompt="$2" hidden="$3" value="${!1:-}"
      if [ -z "$value" ] && [ "$ASSUME_YES" = 0 ] && [ -t 0 ]; then
        if [ "$hidden" = 1 ]; then read -r -s -p "    $prompt (Enter to skip): " value; echo >&2
        else read -r -p "    $prompt (Enter to skip): " value; fi
      fi
      printf '%s=%q\n' "$var" "$value"
    }
    {
      ask TELEGRAM_BOT_TOKEN   "Telegram bot token for Hermes" 1
      ask TELEGRAM_ALLOWED_USERS "your numeric Telegram user id" 0
      ask BROWSER_USE_API_KEY  "browser-use API key" 1
      printf 'AGY_ROTATOR_API_KEY=%q\n' "${AGY_ROTATOR_API_KEY:-$(gen_secret)}"
      printf 'WEB_PASSWORD=%q\n' "${WEB_PASSWORD:-$(gen_secret)}"
    } > "$SECRETS"
    chmod 600 "$SECRETS"
    info "saved. The rotator API key and web password were generated for you."
  fi
  set -a
  # shellcheck disable=SC1090
  . "$SECRETS"
  set +a
}

# ---------------------------------------------------------------------------
# Part 1: system, theme, agent files
# ---------------------------------------------------------------------------
install_system() {
  step "NixOS configuration -> /etc/nixos"
  if [ ! -e /etc/nixos/.tonelico ] && [ -d /etc/nixos ] && [ ! -e /etc/nixos.pre-tonelico ]; then
    sudo cp -a /etc/nixos /etc/nixos.pre-tonelico
    info "your installer-generated config is kept in /etc/nixos.pre-tonelico"
  fi
  local hw
  hw="$(sudo nixos-generate-config --show-hardware-config)" || die "nixos-generate-config failed"
  sudo install -d -o aesc -g users /etc/nixos
  sudo "$RSYNC" -a --delete --exclude='/.tonelico' --chown=aesc:users "$REPO/nixos"/ /etc/nixos/
  printf '%s\n' "$hw" | sudo tee /etc/nixos/hosts/tonelico/hardware-configuration.nix >/dev/null
  sudo chown aesc:users /etc/nixos/hosts/tonelico/hardware-configuration.nix
  date -u +%FT%TZ | sudo tee /etc/nixos/.tonelico >/dev/null
  info "this machine's own hardware-configuration.nix is in place (disks, encryption, modules)"

  step "building the system with the newest kernel (this takes a while)"
  # 'boot' makes the new system the default for the next start without switching
  # the display manager under a running Plasma session.
  # Some Plasma packages are rebuilt from source (the patched kwin changes every
  # package that depends on it). Several C++ compiles at once can exhaust RAM and
  # get the build killed, so size the parallelism to the memory this machine has
  # and add temporary swap when there is little of it.
  local ram_gb swap_gb cpus cores jobs swapfile=""
  ram_gb=$(awk '/^MemTotal:/ {printf "%d", $2/1048576}' /proc/meminfo)
  swap_gb=$(awk '/^SwapTotal:/ {printf "%d", $2/1048576}' /proc/meminfo)
  cpus=$(nproc)
  cores=$(( cpus < 4 ? cpus : 4 ))
  jobs=$(( ram_gb / 4 )); [ "$jobs" -lt 1 ] && jobs=1
  [ "$jobs" -gt $(( cpus / cores > 0 ? cpus / cores : 1 )) ] && jobs=$(( cpus / cores > 0 ? cpus / cores : 1 ))
  info "RAM ${ram_gb} GB, swap ${swap_gb} GB: building with at most $jobs job(s) of $cores core(s) each"
  if [ $(( ram_gb + swap_gb )) -lt 24 ] && [ ! -e /var/tonelico-build.swap ]; then
    if sudo fallocate -l 16G /var/tonelico-build.swap 2>/dev/null \
       && sudo chmod 600 /var/tonelico-build.swap \
       && sudo mkswap /var/tonelico-build.swap >/dev/null \
       && sudo swapon /var/tonelico-build.swap 2>/dev/null; then
      swapfile=/var/tonelico-build.swap
      info "temporary 16 GB swap enabled for the build, removed afterwards"
    else
      sudo rm -f /var/tonelico-build.swap
      warn "could not create temporary swap; if the build is killed, re-run install.sh (finished work is kept)"
    fi
  fi
  local rc=0
  sudo env NIX_CONFIG=$'experimental-features = nix-command flakes\naccept-flake-config = true' \
    nixos-rebuild boot --flake /etc/nixos#tonelico --max-jobs "$jobs" --cores "$cores" || rc=$?
  if [ -n "$swapfile" ]; then sudo swapoff "$swapfile" 2>/dev/null || true; sudo rm -f "$swapfile"; fi
  [ "$rc" -eq 0 ] || die "the system build failed (exit $rc). Finished work is cached; fix the cause above and run install.sh again."
  record PASS "NixOS system built and set as the next boot entry"
  local kver
  kver="$(basename "$(dirname "$(readlink -f /nix/var/nix/profiles/system/kernel)")" 2>/dev/null | sed -E 's/^[a-z0-9]{32}-linux-//')"
  info "kernel in the new system: ${kver:-unknown}"
}

stage_theme() {
  step "staging the theme and wallpapers for the first boot"
  sudo install -d -m 755 /var/lib/tonelico
  sudo rm -rf /var/lib/tonelico/home
  sudo "$RSYNC" -a --chmod=u+rwX,go+rX "$REPO/home"/ /var/lib/tonelico/home/
  { git -C "$REPO" rev-parse HEAD 2>/dev/null || date +%s; } | sudo tee /var/lib/tonelico/home/.version >/dev/null
  record PASS "theme staged in /var/lib/tonelico/home (placed before the login screen on first boot)"
}

substitute_placeholders() {  # substitute_placeholders FILE...
  local f
  for f in "$@"; do
    [ -f "$f" ] || continue
    sed -i "s/@TELEGRAM_USER_ID@/${TELEGRAM_ALLOWED_USERS:-0}/g" "$f"
  done
}

install_agy_control() {
  step "AGY Control"
  mkdir -p "$HOME/agy-control-mcp"
  rsync -a --chmod=u+rwX,go+rX "$REPO/agents/agy-control-mcp"/ "$HOME/agy-control-mcp"/
  (cd "$HOME/agy-control-mcp" && nix "${NIX_FLAGS[@]}" develop -c bash -c 'npm ci --no-audit --no-fund && npm run build') \
    && record PASS "AGY Control built (dist/index.js)" \
    || { record FAIL "AGY Control build failed (run 'npm ci && npm run build' in ~/agy-control-mcp)"; warn "AGY Control build failed"; }
}

install_softfac() {
  step "Software Factory (softfac)"
  mkdir -p "$HOME/.local/lib" "$HOME/.local/bin" "$HOME/Projects/hermes-softfac-linux" "$HOME/.hermes/software-factory"
  install -m 644 "$REPO"/agents/softfac/lib/*.py "$HOME/.local/lib/"
  install -m 755 "$REPO"/agents/softfac/bin/* "$HOME/.local/bin/"
  ln -sfn hermes-code-factory-v2 "$HOME/.local/bin/softfac"
  rsync -a --chmod=u+rwX,go+rX --exclude='/hermes-software-factory' "$REPO/agents/softfac"/ "$HOME/Projects/hermes-softfac-linux"/
  rsync -a --chmod=u+rwX,go+rX "$REPO/agents/softfac/hermes-software-factory"/ "$HOME/.hermes/software-factory"/
  record PASS "softfac files installed (~/.local/lib, ~/.local/bin/softfac, ~/Projects/hermes-softfac-linux)"
}

install_hermes_files() {
  step "Hermes agent files"
  local h="$HOME/.hermes" fresh=0
  mkdir -p "$h/scripts" "$h/plugins"
  [ -f "$h/config.yaml" ] || fresh=1
  [ -f "$h/config.yaml" ] || install -m 644 "$REPO/agents/hermes/config.yaml" "$h/config.yaml"
  [ -f "$h/SOUL.md" ]     || install -m 644 "$REPO/agents/hermes/SOUL.md" "$h/SOUL.md"
  [ "$fresh" = 1 ] && substitute_placeholders "$h/config.yaml"
  rsync -a --chmod=u+rwX,go+rX "$REPO/agents/hermes/skills"/ "$h/skills"/
  rsync -a --chmod=u+rwX,go+rX "$REPO/agents/hermes/plugins"/ "$h/plugins"/
  install -m 755 "$REPO"/agents/hermes/scripts/* "$h/scripts/"
  if [ ! -f "$h/.env" ]; then
    (
      umask 077
      {
        [ -n "${TELEGRAM_BOT_TOKEN:-}" ]    && printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TELEGRAM_BOT_TOKEN"
        [ -n "${TELEGRAM_ALLOWED_USERS:-}" ] && printf 'TELEGRAM_ALLOWED_USERS=%s\n' "$TELEGRAM_ALLOWED_USERS"
        [ -n "${BROWSER_USE_API_KEY:-}" ]   && printf 'BROWSER_USE_API_KEY=%s\n' "$BROWSER_USE_API_KEY"
        printf 'AGY_ROTATOR_API_KEY=%s\n' "$AGY_ROTATOR_API_KEY"
      } > "$h/.env"
    )
    chmod 600 "$h/.env"
  fi
  # Helper scripts and their units.
  mkdir -p "$HOME/.local/bin"
  install -m 755 "$REPO"/agents/bin/* "$HOME/.local/bin/"
  # Global instructions for the coding clients, only if the user has none yet.
  mkdir -p "$HOME/.claude"
  [ -f "$HOME/.claude/CLAUDE.md" ] || install -m 644 "$REPO/agents/clients/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
  [ -f "$HOME/AGENTS.md" ]         || install -m 644 "$REPO/agents/clients/AGENTS.md" "$HOME/AGENTS.md"
  record PASS "Hermes files, helper scripts and client instructions placed (secrets only in ~/.hermes/.env)"
}

install_rotator_files() {
  step "Antigravity rotator files"
  mkdir -p "$HOME/agm-docker" "$HOME/.antigravity_tools"
  install -m 644 "$REPO/agents/antigravity-manager/compose.yml" "$HOME/agm-docker/compose.yml"
  if [ ! -f "$HOME/agm-docker/.env" ]; then
    ( umask 077; printf 'API_KEY=%s\nWEB_PASSWORD=%s\n' "$AGY_ROTATOR_API_KEY" "$WEB_PASSWORD" > "$HOME/agm-docker/.env" )
  fi
  record PASS "rotator compose file and .env written (container is started after the reboot)"
}

run_system_part() {
  preflight
  load_secrets
  install_system
  stage_theme
  if [ "$SKIP_AGENTS" = 0 ]; then
    install_agy_control
    install_softfac
    install_hermes_files
    install_rotator_files
  fi
  report
  cat >&2 <<EOF

${_b}Next:${_0}
  1. Reboot. The theme and wallpapers are placed before the login screen appears.
  2. Log in, open a terminal and run:   ~/tonelico/install.sh
     That starts the services and Docker rotator, registers AGY Control with your clients,
     and checks everything.
EOF
}

# ---------------------------------------------------------------------------
# Part 2: after the reboot
# ---------------------------------------------------------------------------
hermes_env_path() {
  local f env_path next
  f="$(readlink -f "$(command -v hermes 2>/dev/null || true)" 2>/dev/null || true)"
  for _ in 1 2 3 4; do
    [ -n "$f" ] && [ -f "$f" ] || return 1
    env_path="$(grep -oE '/nix/store/[a-z0-9]{32}-hermes-agent-env' "$f" | head -n1 || true)"
    if [ -n "$env_path" ]; then printf '%s\n' "$env_path"; return 0; fi
    next="$(grep -oE '/nix/store/[a-z0-9]{32}-[^"'"'"' ]*/bin/hermes' "$f" | head -n1 || true)"
    f="$next"
  done
  return 1
}

post_services() {
  step "Hermes Python environment link"
  local env_path
  env_path="$(hermes_env_path || true)"
  if [ -z "$env_path" ]; then
    record FAIL "could not locate the Hermes Python environment (is 'hermes' on PATH?)"
    return 0
  fi
  mkdir -p "$HOME/.local/share/nix-roots"
  ln -sfn "$env_path" "$HOME/.local/share/nix-roots/hermes-agent-env"
  record PASS "nix-roots/hermes-agent-env -> $env_path"

  step "systemd user services"
  mkdir -p "$HOME/.config/systemd/user"
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && ! grep -q '^TELEGRAM_BOT_TOKEN=' "$HOME/.hermes/.env" 2>/dev/null; then
    record SKIP "Telegram services (no bot token configured)"
    return 0
  fi
  install -m 644 "$REPO/agents/systemd/agy-telegram.service" "$HOME/.config/systemd/user/agy-telegram.service"
  sed "s#@HERMES_ENV@#$env_path#g" "$REPO/agents/systemd/hermes-gateway.service" > "$HOME/.config/systemd/user/hermes-gateway.service"
  if systemctl --user daemon-reload 2>/dev/null; then
    systemctl --user enable --now hermes-gateway.service agy-telegram.service 2>&1 | sed 's/^/    /' >&2 || true
    sleep 3
    local svc
    for svc in hermes-gateway agy-telegram; do
      if systemctl --user is-active --quiet "$svc.service"; then record PASS "$svc.service is active"
      else record FAIL "$svc.service is not active (journalctl --user -u $svc)"; fi
    done
  else
    record FAIL "no systemd user session; log in graphically and re-run"
  fi
}

post_cron() {
  step "Hermes scheduled jobs"
  command -v hermes >/dev/null 2>&1 || { record SKIP "cron jobs (hermes not on PATH)"; return 0; }
  local name script sched deliver n=0
  while IFS=$'\t' read -r name script sched deliver; do
    if hermes cron list 2>/dev/null | grep -qF "$name"; then continue; fi
    deliver="${deliver//@TELEGRAM_USER_ID@/${TELEGRAM_ALLOWED_USERS:-}}"
    local args=(--name "$name" --script "$script" --no-agent)
    if [[ "$deliver" == telegram:* && "$deliver" != "telegram:" ]]; then args+=(--deliver "$deliver"); fi
    if hermes cron create "${args[@]}" "$sched" >/dev/null 2>&1; then n=$((n + 1)); else warn "could not create cron job: $name"; fi
  done < <(jq -r '.[] | [.name, .script, .schedule, .deliver] | @tsv' "$REPO/agents/hermes/cron-jobs.json")
  record PASS "Hermes cron jobs present ($n created)"
}

post_rotator() {
  step "Antigravity rotator (Docker)"
  local src="$HOME/agm-docker/src" url rev
  url="$(sed -n 1p "$REPO/agents/antigravity-manager/UPSTREAM")"
  rev="$(sed -n 2p "$REPO/agents/antigravity-manager/UPSTREAM")"
  if [ ! -d "$src/.git" ]; then
    mkdir -p "$src"
    git -C "$src" init -q
    git -C "$src" remote add origin "$url"
  fi
  git -C "$src" fetch -q --depth 1 origin "$rev" && git -C "$src" checkout -q FETCH_HEAD \
    || { record FAIL "could not fetch the rotator source ($url @ $rev)"; return 0; }
  if ! docker info >/dev/null 2>&1; then
    record FAIL "the Docker daemon is not reachable (is DOCKER_HOST set? log out and in once)"
    return 0
  fi
  if (cd "$HOME/agm-docker" && docker compose up -d --build 2>&1 | sed 's/^/    /' >&2); then
    sleep 5
    if curl -fsS -o /dev/null --max-time 10 http://127.0.0.1:8045/; then record PASS "rotator answers on 127.0.0.1:8045"
    else record FAIL "rotator container started but 127.0.0.1:8045 does not answer yet"; fi
  else
    record FAIL "docker compose failed in ~/agm-docker"
  fi
}

post_clients() {
  step "AGY Control -> MCP clients"
  local repo="$HOME/agy-control-mcp"
  if [ ! -f "$repo/dist/index.js" ]; then
    record FAIL "AGY Control is not built; run: cd ~/agy-control-mcp && nix develop -c bash -c 'npm ci && npm run build'"
    return 0
  fi
  local only=() c
  for c in claude codex opencode hermes; do command -v "$c" >/dev/null 2>&1 && only+=("$c"); done
  if [ "${#only[@]}" -eq 0 ]; then record SKIP "no MCP client found on PATH"; return 0; fi
  local list
  list="$(IFS=,; echo "${only[*]}")"
  if (cd "$repo" && node scripts/install-agent-clients.mjs --apply --only "$list" 2>&1 | sed 's/^/    /' >&2); then
    record PASS "AGY Control registered with: ${only[*]}"
  else
    record FAIL "install-agent-clients.mjs failed"
  fi
}

post_verify() {
  step "verification"
  local kernel
  kernel="$(uname -r)"
  record PASS "running kernel: $kernel"
  [ -f "$HOME/.local/state/tonelico/restored" ] && record PASS "theme placed on first boot (version $(head -c 12 "$HOME/.local/state/tonelico/restored"))" \
    || record FAIL "theme was not placed (journalctl -u tonelico-restore)"
  [ "$(ls "$HOME/Pictures/Wallpapers" 2>/dev/null | wc -l)" -gt 0 ] && record PASS "wallpapers present in ~/Pictures/Wallpapers" \
    || record FAIL "no wallpapers in ~/Pictures/Wallpapers"
  [ -x "$HOME/.local/bin/softfac" ] && record PASS "softfac command installed" || record FAIL "softfac command missing"
  command -v hermes >/dev/null 2>&1 && record PASS "hermes: $(hermes --version 2>/dev/null | head -n1)" || record FAIL "hermes is not on PATH"
  command -v agy >/dev/null 2>&1 && record PASS "agy command available" || record FAIL "agy is not on PATH"
}

run_post_part() {
  preflight
  load_secrets
  [ "$SKIP_AGENTS" = 1 ] || { post_services; post_cron; post_rotator; post_clients; }
  post_verify
  report
  cat >&2 <<EOF

${_b}Still manual (logins cannot live in git):${_0}
  - Log in to Claude Code, Codex and AGY; run: hermes auth add openai-codex
  - Open http://127.0.0.1:8045 and add your Antigravity accounts (password: WEB_PASSWORD in $SECRETS)
  - Browser sign-ins; copy your Hermes memories/sessions from a backup if you want them
EOF
}

report() {
  local line status text failed=0
  step "report"
  for line in "${RESULTS[@]}"; do
    status="${line%%$'\t'*}"; text="${line#*$'\t'}"
    case "$status" in
      PASS) printf '    %s[ PASS ]%s %s\n' "$_g" "$_0" "$text" >&2 ;;
      FAIL) printf '    %s[ FAIL ]%s %s\n' "$_r" "$_0" "$text" >&2; failed=1 ;;
      *)    printf '    %s[ SKIP ]%s %s\n' "$_y" "$_0" "$text" >&2 ;;
    esac
  done
  [ "$failed" = 0 ] || warn "some steps failed; the lines above say what to run"
}

# Tests source this file to call single functions.
[ "${TONELICO_SOURCE_ONLY:-0}" = 1 ] && return 0

case "$MODE" in
  system) run_system_part ;;
  post)   run_post_part ;;
esac
