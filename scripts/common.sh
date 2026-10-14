# shellcheck shell=bash
# Shared helpers for export.sh, install.sh and the secret checks.
# Sourced, never executed directly.

if [ -t 2 ]; then _b=$'\033[1m'; _r=$'\033[31m'; _y=$'\033[33m'; _g=$'\033[32m'; _0=$'\033[0m'; else _b=; _r=; _y=; _g=; _0=; fi

step() { printf '%s==>%s %s%s%s\n' "$_g" "$_0" "$_b" "$*" "$_0" >&2; }
info() { printf '    %s\n' "$*" >&2; }
warn() { printf '%swarning:%s %s\n' "$_y" "$_0" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$_r" "$_0" "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not on PATH"; }

# Print the manifest entries of a list file: strips comments and blank lines.
manifest_entries() { sed -e 's/[[:space:]]*#.*$//' -e '/^[[:space:]]*$/d' "$1"; }

# Run a command with gitleaks available, from PATH or through nix.
with_gitleaks() {
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks "$@"
  else
    nix --extra-experimental-features 'nix-command flakes' shell nixpkgs#gitleaks -c gitleaks "$@"
  fi
}
