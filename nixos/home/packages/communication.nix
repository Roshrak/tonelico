{ pkgs, ... }:
{
  home.packages = with pkgs; [
    (discord.override { commandLineArgs = "--ozone-platform=x11"; })
    telegram-desktop
  ];
}
