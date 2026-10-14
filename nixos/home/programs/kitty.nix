{ config, lib, ... }:
let
  portable =
    path: lib.replaceStrings [ "/home/aesc" ] [ config.home.homeDirectory ] (builtins.readFile path);
in
{
  programs.kitty = {
    enable = true;
    shellIntegration.enableBashIntegration = false;
    shellIntegration.mode = null; # Preserve Kitty's existing automatic integration.
    extraConfig = portable ../files/config/kitty/kitty.conf;
  };
  xdg.configFile."kitty/common.conf".text = portable ../files/config/kitty/common.conf;
  xdg.configFile."kitty/tonelico-comic-mono.conf".source =
    ../files/config/kitty/tonelico-comic-mono.conf;
}
