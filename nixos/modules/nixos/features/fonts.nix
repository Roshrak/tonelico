{ pkgs, lib, ... }:
{
  imports = [ ../../../comic-mono.nix ];

  fonts.packages =
    with pkgs;
    lib.mkBefore [
      nerd-fonts.jetbrains-mono
      noto-fonts
      noto-fonts-cjk-sans
      noto-fonts-color-emoji
    ];
}
