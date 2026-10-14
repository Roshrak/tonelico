{ pkgs, ... }:
{
  home.packages = with pkgs; [
    nautilus
    file-roller
    seahorse
    gnome-disk-utility
    gparted
    wev
    kdePackages.fcitx5-configtool
    nano
    btop
    ripgrep
    fd
    tree
    rclone
    zenity
    fzf
  ];
}
