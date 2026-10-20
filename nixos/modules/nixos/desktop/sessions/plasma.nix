# KDE Plasma 6 (Wayland) as a second session beside MangoWC + Noctalia.
# Strictly additive: no existing Mango/Noctalia/greetd behaviour is altered.
{ pkgs, ... }:

let
  # Super+Shift/Ctrl+H/J/K/L nudges the active window, matching the GNOME
  # extension and the XFCE helper (80 px per press). KWin has no built-in
  # keyboard move-by-step action.
  windowKeys = pkgs.runCommand "tonelico-kwin-window-keys" { } ''
    dir=$out/share/kwin/scripts/tonelico-window-keys
    mkdir -p $dir/contents/code
    cat > $dir/metadata.json <<'JSON'
    {
      "KPackageStructure": "KWin/Script",
      "KPlugin": {
        "Id": "tonelico-window-keys",
        "Name": "Tonelico window keys",
        "Description": "Move the active window with Super+Shift+H/J/K/L or Super+Ctrl+H/J/K/L",
        "EnabledByDefault": true,
        "License": "MIT",
        "Version": "1"
      },
      "X-Plasma-API": "javascript",
      "X-Plasma-MainScript": "code/main.js"
    }
    JSON
    cat > $dir/contents/code/main.js <<'JS'
    const STEP = 80;

    function nudge(dx, dy) {
        const window = workspace.activeWindow;
        if (!window || !window.normalWindow || !window.moveable || window.fullScreen) {
            return;
        }
        const g = window.frameGeometry;
        window.frameGeometry = { x: g.x + dx, y: g.y + dy, width: g.width, height: g.height };
    }

    const directions = [
        ["H", "left", -STEP, 0],
        ["L", "right", STEP, 0],
        ["K", "up", 0, -STEP],
        ["J", "down", 0, STEP],
    ];
    for (const [key, name, dx, dy] of directions) {
        for (const [modifier, label] of [["Shift", "Shift"], ["Ctrl", "Ctrl"]]) {
            registerShortcut(
                "Tonelico Move Window " + name + " (" + label + ")",
                "Move window " + name + " (Super+" + label + "+" + key + ")",
                "Meta+" + modifier + "+" + key,
                () => nudge(dx, dy)
            );
        }
    }
    JS
  '';

  # Global shortcuts that KDE can only bind to a desktop entry. The defaults
  # live in the entry so a fresh account has them before it saves its own file.
  kglobalaccelEntry = name: title: exec: keys: pkgs.writeTextDir "share/kglobalaccel/${name}.desktop" ''
    [Desktop Entry]
    Type=Application
    Name=${title}
    Exec=${exec}
    Icon=preferences-system
    NoDisplay=true
    OnlyShowIn=KDE;
    X-KDE-Shortcuts=${keys}
  '';
in
{
  # ---- Plasma 6 desktop (Wayland session) ---------------------------------
  services.desktopManager.plasma6.enable = true;
  # SDDM deliberately NOT enabled: greetd + noctalia-greeter stays the login screen.

  # Plasma's lock screen authenticates via PAM service "kde", which only
  # exists when SDDM is enabled. Provide it so kscreenlocker works under greetd.
  security.pam.services.kde = { };

  # DrKonqi's package socket is available to the lingering user manager even
  # at the greeter. Its GUI launcher otherwise crashes while reporting a
  # non-Plasma crash before a display exists, recursively creating new dumps.
  # Keep systemd-coredump itself active; launch only Plasma's GUI reporter in
  # a Plasma session.
  systemd.user.services."drkonqi-coredump-launcher@" = {
    description = "Launch DrKonqi for a systemd-coredump crash in Plasma";
    unitConfig = {
      PartOf = "graphical-session.target";
      ConditionUser = "!@system";
      ConditionEnvironment = "THEME_PROFILE=kde";
    };
    serviceConfig = {
      WorkingDirectory = "%T";
      ExecStart = "${pkgs.kdePackages.drkonqi}/libexec/drkonqi-coredump-launcher";
      Slice = "app.slice";
      Restart = "no";
    };
  };

  # Noctalia Greeter session catalogue now lives in ../shared/session-catalog.nix
  # and is an explicit 11-session allowlist.

  # ---- Minimal application set ---------------------------------------------
  # Remove obvious duplicates; kitty / nautilus / file-roller / seahorse /
  # mpv remain the global tools. Core Plasma pieces (Dolphin, Spectacle,
  # KRunner, System Settings, Info Center) are kept.
  environment.plasma6.excludePackages = with pkgs.kdePackages; [
    konsole # terminal -> kitty
    kate # editor   -> neovim / nano
    gwenview # images   -> existing workflow
    okular # PDFs     -> existing workflow
    elisa # music    -> mpv
    ark # archives -> file-roller
    khelpcenter # docs     -> web
    discover # store/updater not wanted
  ];

  # Portal ownership is declared centrally in ../shared/portals.nix using the
  # NixOS typed xdg.portal.config option. The evaluated Plasma config selects
  # KDE for desktop interfaces and KWallet for Secret; it does not own the
  # login manager and cannot override the per-session routes of other desktops.

  # Shortcuts shared with every other session (see docs/KEYBINDINGS.md).
  environment.systemPackages = [
    windowKeys
    (kglobalaccelEntry "tonelico-fcitx-toggle" "Toggle input method" "fcitx5-remote -t" "Alt+Z")
    (kglobalaccelEntry "tonelico-control-center" "Control center" "systemsettings" "Meta+S")
    (kglobalaccelEntry "tonelico-logout" "Log out now" "slogout" "Meta+Shift+Alt+M")
  ];

  # Graphics, audio, networking, input method, keyring: intentionally absent -
  # all already configured system-wide in configuration.nix and shared by both
  # sessions (PipeWire, NetworkManager, BlueZ, iHD VA-API, fcitx5, gvfs, dconf).
  # File extraction does not need a display connection after session handoff.
  # Scope the platform to Baloo and its children; retain indexing policy.
  systemd.user.services.kde-baloo = {
    overrideStrategy = "asDropin";
    environment.QT_QPA_PLATFORM = "offscreen";
  };

}
