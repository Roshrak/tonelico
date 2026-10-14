{ ... }:
{
  imports = [
    ./core/base.nix
    ./core/boot.nix
    ./core/hardware.nix
    ./core/networking.nix
    ./core/audio.nix
    ./core/services.nix
    ./core/packages.nix
    ./desktop/default.nix
    ./features/gaming.nix
    ./features/input-methods.nix
    ./features/fonts.nix
    ./features/docker.nix
    ./remote/access.nix
    ./hardware/npu-compiler.nix
  ];
}
