{ pkgs, lib, ... }:
{
  home.packages = with pkgs; [
    prismlauncher
    (lib.setPrio 3 jdk8)
    (lib.setPrio 4 jdk17)
    jdk21
    mangohud
  ];
}
