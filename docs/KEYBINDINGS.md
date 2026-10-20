# Keybindings

One set of keys, the same in every session: Sway, Niri, MangoWC, Hyprland, KDE Plasma, GNOME and XFCE.
`Super` is the Windows key (`Meta` in KDE).

The compositor sessions define the set. KDE, GNOME and XFCE copy it, so a key that does something in
Sway does the same thing on the other desktops. The application behind a key can differ where a desktop
has its own (the file manager, the settings app). The key does not.

| Keys | Action | KDE | GNOME | XFCE |
|---|---|---|---|---|
| `Super+Return` | terminal (kitty) | kitty | kitty | kitty |
| `Super+Space` | launcher | KRunner | Activities search | rofi launcher |
| `Super+S` | control center | System Settings | quick settings | settings manager |
| `Super+,` | settings | System Settings | GNOME Settings | settings manager |
| `Super+E` | files | Dolphin | Nautilus | Thunar |
| `Super+Z` | browser | Chromium | Chromium | Chromium |
| `Super+V` | clipboard history | Klipper | clipboard-indicator | Clipman |
| `Alt+Z` | toggle input method | fcitx5 | fcitx5 | fcitx5 |
| `Super+Escape` | lock screen | lock | lock | lock |
| `Super+Shift+E` | session menu | logout screen | logout dialog | logout dialog |
| `Super+Shift+Alt+M` | log out now (`slogout`) | `slogout` | `slogout` | `slogout` |
| `Print` | screenshot, region | Spectacle | GNOME screenshot UI | xfce4-screenshooter |
| `Super+Print` | screenshot, whole screen | yes | yes | yes |
| `Ctrl+Print` | screenshot, active window | yes | yes | yes |
| `Super+Q`, `Super+Shift+Q` | close window | yes | yes | yes |
| `Super+F` | fullscreen | yes | yes | yes |
| `Super+M` | maximize | yes | yes | yes |
| `Alt+Tab` | window switcher | yes | yes | yes |
| `Super+Tab` | next window | yes | yes | yes |
| `Super+O` | overview | Overview | Overview | xfdashboard |
| `Super+H/J/K/L`, `Super+arrows` | focus the window left/down/up/right | yes | yes | yes |
| `Super+Shift+H/J/K/L`, `Super+Ctrl+H/J/K/L` | move the window 80 px | yes | yes | yes |
| `Super+1`..`9` | go to workspace 1..9 | yes | yes | yes |
| `Super+Shift+1`..`9` | send window to workspace 1..9 | yes | yes | yes |
| `Super+Ctrl+Left/Right` | previous/next workspace | yes | yes | yes |
| `Super+drag`, `Super+right-drag` | move / resize a window | yes | yes | yes |
| media, volume, brightness keys | as usual | yes | yes | yes |

## Commands and aliases

`install.sh` puts these in `~/.local/bin` (from `agents/bin` and `agents/softfac/bin`) and in the shell
(`nixos/modules/home/programs/shell.nix`), so they exist on every desktop:

| Command | What it does |
|---|---|
| `slogout` | log out of any session: `gnome-session-quit` on GNOME, `loginctl terminate-session` on the others (`xfce4-session-logout` on XFCE when there is no session id). Bound to `Super+Shift+Alt+M` on KDE, GNOME and XFCE |
| `remote-mode on\|off\|status` | keep the laptop awake with the lid closed and run Sunshine |
| `softfac`, `hermes-code-factory` | the Software Factory |
| `steam` | Steam started silent |
| `xdg-open` | opens links from headless services on the right display |
| `agy`, `opencode` (shell aliases) | start with permission prompts off (`--dangerously-skip-permissions`, `--auto`) |
| `agy_telegram_bot.py`, `gpu_market_search.py`, `ytmusic_control.py`, `npu-python`, `paddleocr-mcp-local` | helpers used by the agents |

The theme commands (`apply-theme-profile`, `save-theme-profile`, `sync-active-theme`, `noctalia-profile`, the `*-session-guarded`
launchers) come from the NixOS config itself.

## What does not carry over

- **Tiling-only keys** have no meaning on a stacking desktop: layout toggles (`Super+N`, `Super+B`, `Super+W`),
  `Super+Shift+F` / `Super+Shift+Space` (float toggle), `Super+R` (reload), and the tiling "move in layout"
  meaning of `Super+Shift+H/J/K/L`. There, those keys move the window 80 px.
- **`Super+Shift+arrows`** (move window to another monitor) works in the compositors, KDE and GNOME. XFCE does
  not bind it.
- **`Super+Alt+arrows`** (focus another monitor) is a compositor key. KDE binds it to "switch window".
- **`Super+arrows` as tiling** in KDE and XFCE is gone: those keys now focus a window, as in Sway, Niri and
  Hyprland.
- **`Super+L` no longer locks the screen** in KDE and XFCE. It focuses the window on the right, as it does in
  the compositors. Lock is `Super+Escape` everywhere.
- KDE and GNOME keep `Alt+F4`, and KDE keeps its `Meta+Alt+number` alias for "send window to workspace".

## Where each desktop gets its keys

| Desktop | Source |
|---|---|
| Sway, Niri, MangoWC, Hyprland | `nixos/home/files/config/` and `nixos/modules/desktop/sessions/hyprland/` |
| KDE Plasma | `home/.config/kglobalshortcutsrc` and `kwinrc`, placed by `tonelico-restore`; `Super+Shift/Ctrl+H/J/K/L` come from a KWin script and `Alt+Z` / `Super+S` from two shortcut entries, both in `sessions/plasma.nix` |
| GNOME | `sessions/gnome.nix` (system defaults), `home/desktop/gnome.nix` (custom commands), and the `tonelico-window-rules` extension (directional focus and move) |
| XFCE | `sessions/xfce.nix`: `xfce-apply-shared-keybindings` runs at every XFCE login, and `xfce-window-direction` does the focus and move |

## Checked, and not checked

Checked in a headless run:
- **KDE:** KWin and the shortcut daemon, with the shipped config. Every key above is registered to the action
  listed and no key is used twice. The move script moved a window by 80 px in each direction. `Super+3` switched
  workspace, `Super+Left` moved focus, and there are nine workspaces.
- **XFCE:** a virtual X server with XFWM. `xfce-window-direction` moved focus left, right, up and down and stopped
  at the edge. It moved a window 80 px and back exactly. `Super+<number>` switched workspace, `Super+drag` moved
  a window, and `Super+Left` no longer tiles.
- **GNOME:** the generated settings contain the new `Super+Shift+Q` and `Super+Shift+Alt+M` entries. GNOME Shell
  was not started.

Not checked:
- A real login to each desktop, and real key presses on the laptop.
- XFCE: the keys that run a command (`Super+H/J/K/L`, `Super+Shift+H/J/K/L`) were registered correctly, but the
  virtual session never ran a command from a key press, so the key-to-command step is unverified. `Super+Q`
  closing a window was not confirmed there either, although that key was already bound before this change.
- KDE: `Super+Return` and `Super+Z` use desktop entries from the user's own account, so they were not part of the
  headless run.
