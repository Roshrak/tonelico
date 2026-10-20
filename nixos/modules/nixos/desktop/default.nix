{ ... }:
{
  imports = [
    ./sessions/mango.nix
    ./shared/noctalia.nix
    ./sessions/plasma.nix
    ./sessions/niri.nix
    ./sessions/sway.nix
    ./shared/monitor-layout.nix
    ./sessions/xfce.nix
    ./sessions/xfwm4-fix.nix
    ./sessions/hyprland.nix
    ./sessions/gnome.nix
    ./shared/overview.nix
    ./shared/portals.nix
    ./shared/file-picker.nix
    ./shared/session-lifecycle.nix
    ./shared/session-catalog.nix
    ./shared/theme-profiles.nix
    ./shared/environment.nix
    ./shared/preferences.nix
  ];
}
