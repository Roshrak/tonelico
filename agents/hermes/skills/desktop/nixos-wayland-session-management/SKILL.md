---
name: nixos-wayland-session-management
description: "Use when configuring or debugging NixOS Wayland sessions."
version: 1.1.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [nixos, wayland, niri, umbriel, sway, hyprland, mango, noctalia, xdg-desktop-portal, bluetooth, libinput, uhid]
---

# NixOS Wayland Session & Compositor Management

## When to Use
- Installing, configuring, theming, or troubleshooting Wayland compositor sessions (`niri`, `umbriel`, `mango`, `sway`, `hyprland`, `plasma`) on this Tonelico NixOS machine.
- Editing compositor configs (`~/.config/niri/config.kdl`, `~/.config/umbriel/config.toml`, `~/.config/sway/config`, `~/.config/mango/config.conf`) or syncing `/home/aesc/tonelico/nixos` with `/etc/nixos`.

## Procedure

### 1. Flake Inputs & Binary Caches (`flake.nix` & `modules/system/base.nix`)
1. Check upstream branches with `git ls-remote <repo_url>` before pinning a flake input.
   - **Pitfall**: Track the upstream `cachix` branch (e.g. `github:noctalia-dev/umbriel/cachix`, `github:noctalia-dev/noctalia/cachix`) without `inputs.nixpkgs.follows = "nixpkgs"` when a project publishes a Cachix binary cache — overriding `nixpkgs` changes the input closure hash and forces a full local C++/Rust build instead of fetching prebuilt store paths.
2. Add the substituter URL and public key to both `nixConfig` in `flake.nix` and `nix.settings` in `modules/system/base.nix`.
3. Pass `--option extra-substituters "..." --option extra-trusted-public-keys "..."` explicitly on the first `nixos-rebuild switch` before the new cache is active in `/etc/nix/nix.conf`.

### 2. Multi-Compositor NixOS Module Wiring
When adding or modifying a Wayland session, update all coordinated modules together:
1. **Session module (`modules/desktop/sessions/<name>.nix`)**:
   - Import the upstream NixOS module if provided and enable the compositor (`programs.<name>.enable = true`).
   - **Pitfall**: Disable the upstream module's default portal wiring (`portalPackage = null` or `enableDefaultPortal = false`) — `modules/desktop/shared/portals.nix` uses `lib.mkForce` on `xdg.portal.extraPortals` to deduplicate portals across compositors, so portal packages and `xdg.portal.config.<name>` must be declared centrally in `portals.nix`.
2. **Desktop aggregate (`modules/aggregates/desktop.nix`)**:
   - Add `"<name>"` to the `sessions` list.
3. **Curated Greeter catalog (`modules/desktop/shared/session-catalog.nix`)**:
   - Add `"<name>"` to `waylandNames`, add the session package to `packagePaths`, rewrite `Exec=` in the generated `.desktop` entry to `/run/current-system/sw/bin/<name>-session-guarded`, and update the `builtins.length waylandNames` assertion count.
4. **Session lifecycle & Kanshi (`modules/desktop/shared/session-lifecycle.nix` & `monitor-layout.nix`)**:
   - Add `environment.etc."kanshi/<name>.conf".source = mkKanshiConfig "<name>";` in `monitor-layout.nix`.
   - Add the compositor's output-focus IPC command to `desktop-main-pointer` in `session-lifecycle.nix` (e.g. `niri msg action focus-monitor "$target"` for Niri, `umbriel msg output-focus "$target"` for Umbriel).
   - Include any compositor-specific environment variables (`NIRI_SOCKET`, `UMBRIEL_SOCKET`, `WAYLAND_SOCKET`, `LIBEI_SOCKET`, `SWAYSOCK`, `HYPRLAND_INSTANCE_SIGNATURE`) in the session cleanup unset lists.
5. **Isolated Theme Profiles (`modules/desktop/shared/theme-profiles.nix`, `modules/home/desktop/configuration.nix`, `home/files/bin/save-theme-profile`)**:
   - Register the profile name in `noctalia-profile`, `theme-profile-activate`, `theme-profile-sync`, `theme-session-cleanup`, `save-theme-profile`, and `<name>-session-guarded`.
   - Seed `~/.config/theme-profiles/<name>`, `~/.local/state/theme-profiles/<name>`, and `~/.config/kitty/profiles/<name>` so GTK/Qt/Kitty/Noctalia themes stay isolated per compositor.
   - In `modules/home/desktop/configuration.nix`, link the static compositor config via `xdg.configFile` and rewrite relative dynamic color includes (`colors.kdl` or `noctalia.toml`) to mutable paths under `${config.xdg.configHome}` seeded by `home.activation.tonelicoMutableThemeOutputs`.

### 3. Validating Compositor Configurations Offline
1. Always inspect the installed binary's built-in schema and validator before writing or patching compositor configs:
   - **Umbriel**:
     ```bash
     umbriel config schema --json | jq '.options[] | select(.path | startswith("layout."))'
     umbriel config validate -c /home/aesc/tonelico/nixos/home/files/config/umbriel/config.toml
     ```
   - **Niri**:
     ```bash
     niri validate -c /home/aesc/tonelico/nixos/home/files/config/niri/config.kdl
     ```
   - **Pitfall**: Never rely on web-scraped READMEs or subagent summaries for config syntax or keybind action names — upstream docs frequently lag behind the binary schema (e.g. Umbriel uses `[include] files = [...]`, `gap`, `extent_presets`, and hyphenated actions like `window-focus-left`, `column-move-left`, `window-cycle-primary-extent`, `config-reload`, which `umbriel config validate` verifies with zero guesswork).
2. Read the live reference config (`/home/aesc/tonelico/nixos/home/files/config/niri/config.kdl` and `colors.kdl`) directly when matching look and feel across compositors:
   - Tonelico Niri visual baseline: scrolling layout, `gap = 2`, `default_extent_fraction = 0.62`, `center_focused = "never"`, `corner_radius = 0` (square corners), `border_width = 1`, shadows disabled, title bars disabled, `prefer_no_csd = true`, black overview backdrop (`#000000`), `HDMI-A-1` at `[0, 60]` (left) and `eDP-1` at `[1920, 0]` (right, focused at startup).

### 4. Staging in `/home/aesc/tonelico/nixos`, Syncing to `/etc/nixos`, and Exporting
1. **Pitfall**: Direct `write_file`/`patch` calls to `/etc/nixos/*` are blocked by the tool sandbox (`Refusing to write to sensitive system path`). Always edit files under `/home/aesc/tonelico/nixos` first.
2. Update the flake lock if inputs changed:
   ```bash
   nix flake lock --update-input <input_name> /home/aesc/tonelico/nixos
   ```
3. Sync `/home/aesc/tonelico/nixos` to `/etc/nixos` without overwriting machine-local hardware and host files:
   ```bash
   sudo rsync -a --delete \
     --exclude='.git' \
     --exclude='hosts/tonelico/host.nix' \
     --exclude='hardware-configuration.nix' \
     --exclude='hosts/tonelico/hardware-configuration.nix' \
     --exclude='modules/features/tonelico-restore.nix' \
     /home/aesc/tonelico/nixos/ /etc/nixos/
   ```
   - **Pitfall**: `/home/aesc/tonelico/nixos/hosts/tonelico/host.nix` is the portable export variant (includes `tonelico-restore`), whereas `/etc/nixos/hosts/tonelico/host.nix` is the live host definition (`retainLocalRecovery = true; features = [ "virtualization" ];`) and `/etc/nixos` tracks `hardware-configuration.nix` locally. Overwriting those breaks the live host evaluation.
4. Stage any newly added files in `/etc/nixos` so Nix flake evaluation sees them:
   ```bash
   sudo git -C /etc/nixos add -N <new_paths>
   ```
5. Activate and verify:
   ```bash
   sudo nixos-rebuild switch --flake /etc/nixos#tonelico
   ```
6. Add any new `~/.config/<compositor>` directory to `/home/aesc/tonelico/manifest/home.list` and run `/home/aesc/tonelico/export.sh` so the portable export repository stays in sync and passes secret/gitleaks checks.

### 5. Troubleshooting Bluetooth LE Mice/Keyboards (HoG / `uhid`) in Wayland Sessions
When a Bluetooth LE mouse or keyboard shows `Connected: yes` in `bluetoothctl` or the Noctalia bar but does not move the cursor or send keys in a Wayland session:
1. Check `/proc/bus/input/devices` and `/dev/input/event*` for a `uhid` kernel input node (`Sysfs=/devices/virtual/misc/uhid/...`) before inspecting the compositor:
   ```bash
   cat /proc/bus/input/devices | grep -A 8 -i "uhid"
   ```
   - **Pitfall**: Do not debug the Wayland compositor's `libinput` backend when `/proc/bus/input/devices` has no `uhid` entry for the Bluetooth device — Wayland compositors only consume kernel `/dev/input/event*` nodes created by BlueZ's `uhid` driver.
2. Inspect `journalctl -u bluetooth -n 50 --no-pager` for HoG errors:
   - `profiles/input/hog-lib.c:report_map_read_cb() Report Map read failed: Attribute requires authentication before read/write`
   - `profiles/input/hog-lib.c:proto_mode_read_cb() ATT protocol error`
   - **Pitfall (BlueZ 5.86 `bt_hog` In-Memory Wedge)**: In BlueZ `profiles/input/hog-lib.c`, if `report_map_read_cb()` fails once on an unauthenticated connection before SMP pairing finishes, `hog->get_rep_id` remains non-zero in memory and `hog->reports` is already populated. On subsequent reconnects (even after pairing completes), `remove_gatt_req()` skips reading the GATT `Report Map` (`0x2A4B`) and never calls `uhid_create()`, leaving the mouse `Connected: yes` with no `/dev/input/event*` node for the rest of `bluetoothd`'s lifetime.
3. Recover the device without re-pairing:
   - Confirm the bond and `[LongTermKey]` exist (`bluetoothctl info <MAC>` shows `Paired: yes`, `Bonded: yes`, `Trusted: yes`; redact any raw LTK/IRK values as `[REDACTED]` if inspecting `/var/lib/bluetooth`).
   - Restart `bluetooth.service` to clear the wedged in-memory `bt_hog` state in `bluetoothd`:
     ```bash
     sudo systemctl restart bluetooth.service
     ```
   - Wake the BLE mouse/keyboard (move/click it so it advertises, or run `bluetoothctl connect <MAC>`) and verify the new `/devices/virtual/misc/uhid/...` node appears in `/proc/bus/input/devices` and `sudo dmesg | tail -n 20`.
   - **Pitfall**: If capturing HCI packets with `btmon`, stop it with `sudo pkill -x btmon` (exact process name) rather than `sudo pkill -f btmon` — `-f` matches the parent shell command line and kills the subshell with `SIGTERM`.
