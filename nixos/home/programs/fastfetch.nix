{ config, lib, ... }:
let
  portable =
    path: lib.replaceStrings [ "/home/aesc" ] [ config.home.homeDirectory ] (builtins.readFile path);
in
{
  programs.fastfetch.enable = true;
  xdg.configFile."fastfetch/config.jsonc".text = portable ../files/config/fastfetch/config.jsonc;
}
