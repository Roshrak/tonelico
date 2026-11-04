{ ... }:
{
  homeManager.communication =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        (discord.override { commandLineArgs = "--ozone-platform=wayland"; })
        telegram-desktop
      ];
    }
  ;
}
