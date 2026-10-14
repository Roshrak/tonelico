#!/usr/bin/env bash
# Refuses to pass if the repository could leak a secret or personal data.
#
#   scripts/check-secrets.sh [repo-dir]
#
# Four independent checks. Any failure exits non-zero and names the file,
# never the secret value:
#   1. forbidden file names (env files, databases, keys, histories, nested git repos)
#   2. file size (GitHub rejects files over 100 MB)
#   3. gitleaks, a pattern-based secret scanner
#   4. canary: the real secret values stored on THIS machine must not appear anywhere
#      in the tree. This catches secrets that no pattern would recognise.
set -euo pipefail

REPO="$(cd "${1:-$(dirname "${BASH_SOURCE[0]}")/..}" && pwd)"
# shellcheck source=common.sh
. "$REPO/scripts/common.sh"

H="${CANARY_HOME:-$HOME}"
fail=0

# --- 1. forbidden names -----------------------------------------------------
step "check 1/4: forbidden file names"
bad="$(find "$REPO" -path "$REPO/.git" -prune -o \( \
    -name '.env' -o -name '.env.*' -o -name 'secrets.env' -o -name 'auth.json' -o -name 'auth.lock' \
    -o -name '*.db' -o -name '*.db-*' -o -name '*.sqlite*' \
    -o -name 'id_rsa*' -o -name 'id_ed25519*' -o -name '*.pem' -o -name '*.key' -o -name '*.p12' \
    -o -name '*.kdbx' -o -name 'kwalletrc' -o -name '*.kwl' -o -name '.netrc' \
    -o -name '.bash_history' -o -name '.hermes_history' -o -name 'notification_history*' \
    -o -name 'accounts.json' -o -name 'user_tokens*' -o -name 'sunshine_state.json' \
    -o -name '*.log' \) -print \
  | grep -v -E '\.env\.example$|secrets\.example\.env$' || true)"
if [ -n "$bad" ]; then
  printf '%s\n' "$bad" | sed "s|^$REPO/|    |" >&2
  warn "forbidden files found (list above)"; fail=1
fi
nested="$(find "$REPO" -mindepth 2 -name .git -not -path "$REPO/.git/*" -print)"
if [ -n "$nested" ]; then
  printf '%s\n' "$nested" | sed "s|^$REPO/|    |" >&2
  warn "nested git repositories found (they would become broken submodules)"; fail=1
fi

# --- 2. size ----------------------------------------------------------------
step "check 2/4: file size"
big="$(find "$REPO" -path "$REPO/.git" -prune -o -type f -size +90M -print)"
if [ -n "$big" ]; then
  printf '%s\n' "$big" | sed "s|^$REPO/|    |" >&2
  warn "files over 90 MB (GitHub's hard limit is 100 MB)"; fail=1
fi

# --- 3. gitleaks ------------------------------------------------------------
step "check 3/4: gitleaks"
if with_gitleaks dir --no-banner --redact --no-color -c "$REPO/.gitleaks.toml" "$REPO" 2>&1 | sed 's/^/    /' >&2; [ "${PIPESTATUS[0]}" -eq 0 ]; then
  info "no findings"
else
  warn "gitleaks reported findings (above)"; fail=1
fi

# --- 4. canary: real local secrets must not be in the tree -------------------
step "check 4/4: canary against secrets stored on this machine"
patterns="$(mktemp)"
chmod 600 "$patterns"
trap 'rm -f "$patterns"' EXIT

collect_env() {  # secret-looking values from KEY=VALUE files
  [ -f "$1" ] || return 0
  grep -E '^[A-Za-z0-9_]*(KEY|TOKEN|SECRET|PASS|PASSWORD|AUTH)[A-Za-z0-9_]*=' "$1" \
    | sed -e 's/^[^=]*=//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//" || true
}
collect_json() {  # long opaque strings and e-mail addresses from a JSON file
  [ -f "$1" ] || return 0
  jq -r '.. | strings | select((length >= 20 and (test("[[:space:]/]") | not)) or test("^[^@[:space:]]+@[^@[:space:]]+\\.[a-z]+$"))' "$1" 2>/dev/null || true
}
{
  collect_env "$H/.hermes/.env"
  collect_env "$H/agm-docker/.env"
  collect_json "$H/.hermes/auth.json"
  collect_json "$H/.antigravity_tools/accounts.json"
  git config --global user.email 2>/dev/null || true
  command -v gh >/dev/null 2>&1 && gh auth token 2>/dev/null || true
  sed -n 's/^TELEGRAM_ALLOWED_USERS=//p' "$H/.hermes/.env" 2>/dev/null | tr ',' '\n' || true
  [ -f "$H/.config/tonelico/secrets.env" ] && collect_env "$H/.config/tonelico/secrets.env" || true
} | awk 'length($0) >= 6 && $0 !~ /@users\.noreply\.github\.com$/' | sort -u > "$patterns"

count="$(wc -l < "$patterns")"
info "$count secret values loaded for comparison (not printed)"
if [ "$count" -eq 0 ]; then
  warn "no secrets found to compare against; check 4 proved nothing on this machine"
fi
hits="$(grep -rIlF -f "$patterns" --exclude-dir=.git "$REPO" 2>/dev/null || true)"
if [ -n "$hits" ]; then
  printf '%s\n' "$hits" | sed "s|^$REPO/|    |" >&2
  warn "a real secret value from this machine appears in the files above"; fail=1
else
  info "none of them appear in the tree"
fi

if [ "$fail" -ne 0 ]; then
  die "secret check FAILED. Do not commit or push until every item above is resolved."
fi
step "secret check passed"
