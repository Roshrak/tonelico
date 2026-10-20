# File picker

The window that opens when an app asks you to attach, open or save a file (Discord, browsers, Telegram,
anything that goes through the desktop portal) is **Yazi in a Kitty window**, the same in every session.
It replaces the GTK picker.

What it does that the GTK picker did not:

- **It opens where you were last time.** The folder you ended up in is remembered between picks and between apps.
- **You can pick files from several folders at once.** The selection stays when you move to another folder, so one
  `Enter` returns all of them. No more attach one, find the folder again, attach the next.
- **You find things by typing**, not by walking the tree.
- **Newest first.** What you want to send is nearly always what you just made.

## How it looks

- **Colours come from your Kitty theme.** Nothing in the picker is a fixed colour, so it changes with the theme.
- **A bar at the bottom** shows how many files you have selected and the keys for this kind of request
  (choose files, choose a folder, save), so there is nothing to remember.
- **Selected files get a solid check badge** at the start of the row, in every folder you visit.
- **Every row shows size and date.** The cursor row is a soft highlight rather than a reversed block.
- **The find and recent lists** (`f` `F` `r` `R`) show short `~/...` paths, a preview of the highlighted folder or
  file on the right, and the keys in a one-line header. Find-folder ranks short paths first. Find-files and recent
  files list the newest first and keep that order while you type.
- **No frame.** The window has no border and no shadow on Sway, Niri, MangoWC and Hyprland, so it does not carry the
  coloured floating-window outline.
- **The window** has a little more padding and is slightly more opaque than your normal terminals, so file names
  stay readable over a busy wallpaper.

## Keys

| Key | Does |
|---|---|
| `Space` | select / unselect the file under the cursor (stays selected when you change folder) |
| `Ctrl+A` / `Ctrl+D` | select everything in this folder / clear the selection |
| `Enter` | confirm. On a folder it opens the folder. With nothing selected it takes the file under the cursor |
| `f` | find a folder anywhere under your home by typing part of its name |
| `F` | find files anywhere under your home; `Tab` marks several, `Enter` selects them all |
| `r` | jump to a recent folder |
| `R` | select recently used files again |
| `g` then `d` `p` `s` `v` `m` `o` `h` `t` | Downloads, Pictures, Screenshots, Videos, Music, Documents, home, /tmp |
| `h` `j` `k` `l` / arrows | move; `l` or `Enter` opens a folder, `h` goes up |
| `Esc` | cancel |
| `F1` | all of Yazi's keys |

The key reminders are also shown at the top right of the window.

Folder requests ("choose a folder"): open the folder, then press `q`.
Save requests: go to the folder, press `q`, then type the name (it starts filled in with the app's suggestion).
`Enter` on an existing file saves over it, after asking.

## How it is wired

| Piece | Where |
|---|---|
| the picker, its Yazi config, the find/recent helpers | `nixos/modules/desktop/shared/file-picker.nix` |
| every session uses it for `FileChooser` | `nixos/modules/desktop/shared/portals.nix` |
| apps are told to use the portal (`GTK_USE_PORTAL=1`) | `file-picker.nix`, and the Discord and Chromium launchers in `nixos/modules/home/scripts.nix` |
| the window floats and is centred on Sway, Niri, MangoWC, Hyprland | the compositor configs under `nixos/home/files/config/` and `sessions/hyprland/` |
| what it remembers | `~/.local/state/tonelico/file-picker/` (`last-dir`, `recent-dirs`, `recent-files`) |

Chromium and Electron apps (Discord included) only use the portal picker when `GTK_USE_PORTAL=1` is set. Without
it they open their own GTK dialog, which is why this has to be set for the new picker to appear at all.

Your own Yazi (`~/.config/yazi`) is not touched: the picker uses its own config.

KDE, GNOME and XFCE float the window by themselves. Qt apps that use their own dialog (Dolphin, Kate, ...) keep it.

## Checked, and not checked

Checked in a private session (virtual X server, the real portal and the real backend):
- A multi-file request returned files from two folders after one `Enter`.
- The next request opened in the folder the last one ended in.
- `F` (find files), `f` (find folder) and `R` (recent files) worked, including picking two files with `Tab`.
- Single-file, folder and save requests worked. Save pre-fills the suggested name, accepts a typed name and asks
  before replacing a file. `Esc` cancels each of them.
- Chromium with `GTK_USE_PORTAL=1` opened this picker from a file input and showed "2 files" afterwards.
  Without that variable it did not open the picker.
- The Sway and MangoWC rules floated and centred the window in a headless instance of each. The Niri and Hyprland
  rules passed their configuration checks.

The restyle was checked by rendering the real picker in a virtual X server and reading screenshots of the file list,
the selected badges, the folder, save and find screens. Selecting two files from the find list and confirming returned
exactly those two paths.

Not checked: Discord itself (it is Chromium underneath), a real login to any desktop, the Niri and Hyprland rules in a
running compositor, and how it looks on the laptop screen with the compositor's transparency and your per-session
Kitty theme (the screenshots used Kitty's default theme with no compositor).
