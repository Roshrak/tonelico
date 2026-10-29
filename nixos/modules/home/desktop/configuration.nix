{ ... }:
{
  homeManager.desktop-configuration =
    { config, lib, pkgs, ... }:
    let
      portable =
        path: lib.replaceStrings [ "/home/aesc" ] [ config.home.homeDirectory ] (builtins.readFile path);
    in
    {
      # Preserve the existing grammars and package/session ownership. In
      # particular Hyprland uses Lua; the ordinary HM text config generator would
      # change that grammar. NixOS still owns compositor and greeter integration.
      xdg.configFile."niri/config.kdl".text =
        lib.replaceStrings
          [ ''include "colors.kdl"'' ]
          [ ''include "${config.xdg.configHome}/niri/colors.kdl"'' ]
          (portable ../../../home/files/config/niri/config.kdl);
      xdg.configFile."sway/config".text = portable ../../../home/files/config/sway/config;
      xdg.configFile."sway/noctalia".text = portable ../../../home/files/config/sway/noctalia;
      xdg.configFile."hypr/hyprland.lua".text =
        portable ../../desktop/sessions/hyprland/hyprland.lua;

      # Mango's animation helper, Noctalia, Fcitx, GTK and Plasma write their
      # own runtime settings. Seed portable defaults only on a new machine; never
      # replace existing user state or make those targets read-only symlinks.
      home.activation.seedDesktopDefaults = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        seed() {
          source="$1" target="$2"
          if [ ! -e "$target" ] && [ ! -L "$target" ]; then
            run ${pkgs.coreutils}/bin/mkdir -p -- "$(${pkgs.coreutils}/bin/dirname "$target")"
            run ${pkgs.coreutils}/bin/cp --no-clobber -- "$source" "$target"
            run ${pkgs.coreutils}/bin/chmod u+rw -- "$target"
          fi
        }
        seed ${pkgs.writeText "mango-config.conf" (portable ../../../home/files/config/mango/config.conf)} "$HOME/.config/mango/config.conf"
        seed ${pkgs.writeText "mango-noctalia.conf" (portable ../../../home/files/config/mango/noctalia.conf)} "$HOME/.config/mango/noctalia.conf"
        seed ${pkgs.writeText "mango-monitor-layout.conf" (portable ../../../home/files/config/mango/monitor-layout.conf)} "$HOME/.config/mango/monitor-layout.conf"
        seed ${../../../home/files/config/niri/colors.kdl} "$HOME/.config/niri/colors.kdl"
        seed ${../../../home/files/config/sway/colors} "$HOME/.config/sway/colors"
        seed ${../../../home/files/config/kitty/default-theme.conf} "$HOME/.config/kitty/themes/default.conf"
      '';
    }
  ;
}
