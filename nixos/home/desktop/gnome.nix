{ lib, ... }:
let
  commands = [
    { name = "Terminal"; command = "kitty"; binding = "<Super>Return"; }
    { name = "Files"; command = "nautilus"; binding = "<Super>e"; }
    { name = "Browser"; command = "chromium"; binding = "<Super>z"; }
    { name = "Settings"; command = "gnome-control-center"; binding = "<Super>comma"; }
    { name = "Fcitx toggle"; command = "fcitx5-remote -t"; binding = "<Alt>z"; }
    { name = "Logout menu"; command = "gnome-session-quit --logout-dialog"; binding = "<Super><Shift>e"; }
  ];
  paths = lib.genList (i: "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom${toString i}/") (builtins.length commands);
in
{
  dconf.settings = {
    "org/gnome/settings-daemon/plugins/media-keys".custom-keybindings = paths;
    "org/gnome/shell".enabled-extensions = [
      "clipboard-indicator@tudmotu.com" "tonelico-window-rules@aesc"
    ];
    "org/gnome/shell/extensions/clipboard-indicator" = {
      toggle-menu = [ "<Super>v" ];
      open-at-cursor = true;
    };
  } // lib.listToAttrs (lib.imap0 (i: item: {
    name = "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom${toString i}";
    value = { inherit (item) name command binding; };
  }) commands);
}
