{ pkgs, lib, ... }:
{
  hardware.keyboard.qmk.enable = true;

  environment.systemPackages = with pkgs; [
    via
  ];

  services.udev.packages =
    with pkgs;
    lib.mkBefore [
      via
    ];
}
