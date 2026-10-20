# Desktop sessions and their shared pieces. Every session is installed here;
# the greeter session list is curated by desktop/shared/session-catalog.nix.
{ config, ... }:
{
  nixos.desktop = {
    imports = map (name: config.nixos.${name}) [
      "mango"
      "noctalia"
      "plasma"
      "niri"
      "sway"
      "monitor-layout"
      "xfce"
      "xfwm4-fix"
      "hyprland"
      "gnome"
      "overview"
      "portals"
      "file-picker"
      "session-lifecycle"
      "session-catalog"
      "theme-profiles"
      "environment"
      "preferences"
    ];
  };
}
