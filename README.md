# tonelico

A 1-to-1 copy of my laptop: NixOS 26.05 with the newest kernel, six desktops (Mango, niri,
KDE Plasma 6, Hyprland, Sway, GNOME) behind the Noctalia greeter, the theme and wallpapers,
and the agent stack (AGY Control, Software Factory, Hermes, the Antigravity rotator).

It is built for a **fresh NixOS KDE Plasma install**. One script pulls this repo and turns
that install into the full setup. The theme comes across by itself; nothing is set by hand.

## Install

1. Download the **NixOS 26.05 graphical ISO with KDE Plasma** and install it normally:
   - boot in **UEFI** mode
   - create the user **`aesc`** (the config has `/home/aesc` paths)
   - log in once to the Plasma desktop it gives you
2. Open a terminal and run:

   ```bash
   nix-shell -p git --run 'git clone --depth 1 https://github.com/Roshrak/tonelico ~/tonelico'
   ~/tonelico/install.sh
   ```

   It asks for your secrets once (Enter skips a feature), then builds the system. This takes
   a while and downloads several GB.
3. **Reboot.** The theme and wallpapers are put in place before the login screen appears.
4. Log in and run `~/tonelico/install.sh` again. It starts the services and the Docker
   rotator, registers AGY Control with Claude Code / Codex / OpenCode / Hermes, and prints a
   PASS / FAIL report. Nothing is called done until it has been checked.

### What happens

| Step | What it does |
|---|---|
| System | Copies `nixos/` to `/etc/nixos`, generates **this machine's own** `hardware-configuration.nix` (disks, encryption), runs `nixos-rebuild boot` |
| Kernel | `boot.kernelPackages = pkgs.linuxPackages_latest`: the newest kernel NixOS 26.05 ships (7.2.x at export time) |
| Theme | Staged in `/var/lib/tonelico/home`; the `tonelico-restore` service copies it into `~` **before the display manager starts**, so nothing running can overwrite it and every file stays editable |
| Agents | AGY Control is built with `npm ci && npm run build`; softfac, Hermes and helper scripts are copied to where the units expect them |
| Rotator | Upstream Antigravity-Manager is fetched at the pinned commit and started with `docker compose` |

`nixos-rebuild boot` is used rather than `switch` because switching the display manager from
SDDM to greetd under a running Plasma session would end that session halfway through.

### Hardware

`nixos/hosts/tonelico` is tuned for the **Acer Swift SFG16-72** (battery charge limit, PixArt
touchpad fix, Intel NPU compiler). The installer refuses other hardware unless you pass
`--same-hardware`; then edit `nixos/hosts/tonelico/default.nix` first.

## Keybindings

The same keys work in every session (Sway, Niri, MangoWC, Hyprland, KDE, GNOME, XFCE). See
[docs/KEYBINDINGS.md](docs/KEYBINDINGS.md) for the table and what does not carry over.

## File picker

Attach, open and save windows are Yazi in Kitty in every session: they remember the last folder and take files from
several folders at once. See [docs/FILE-PICKER.md](docs/FILE-PICKER.md).

## Keeping the repo current

On the laptop being copied:

```bash
./export.sh        # copy, scrub placeholders, run the secret checks
git status         # review what changed
git add -A && git commit && git push
```

Only paths listed in `manifest/home.list` and in `export.sh` are copied (an allowlist), so a new
private file cannot slip in by accident. Symlinks into `/nix/store` are skipped because Home
Manager rebuilds them. The checks in `scripts/check-secrets.sh` also run before every push:

1. forbidden file names (env files, databases, keys, histories, nested git repos)
2. file size (GitHub rejects 100 MB)
3. [gitleaks](https://github.com/gitleaks/gitleaks) pattern scan
4. a **canary**: every real secret stored on the exporting machine is searched for in the tree.
   This matters: gitleaks alone did not recognise a Telegram bot token that the canary caught.

## Layout

```
install.sh  export.sh  secrets.example.env
nixos/      /etc/nixos as a flake (hosts/tonelico, modules, Home Manager)
home/       theme, Plasma/Noctalia settings, wallpapers; paths relative to ~
agents/     agy-control-mcp, softfac, hermes, antigravity-manager, bin, systemd, clients
overlay/    files added on top of /etc/nixos during export (the first-boot theme service)
manifest/   the allowlist and exclude patterns
scripts/    check-secrets.sh and shared helpers
docs/       KEYBINDINGS.md (the key set shared by every session), FILE-PICKER.md (the attach/open/save window)
```
