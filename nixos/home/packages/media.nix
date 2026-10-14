{ pkgs, ... }:
{
  home.packages = with pkgs; [
    mpv
    vlc
    pavucontrol
    swappy
    easyeffects
    obs-studio
  ];
}
