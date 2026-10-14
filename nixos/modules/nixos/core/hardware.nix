{ ... }:
{
  # Portable graphics and firmware defaults. CPU/GPU vendor-specific settings
  # live under hosts/<flake-attribute>/default.nix.
  hardware.enableRedistributableFirmware = true;
  hardware.graphics = {
    enable = true;
    enable32Bit = true;
  };
  # Laptop services.
  zramSwap = {
    enable = true;
    memoryPercent = 50;
  };
  services.fwupd.enable = true;
  services.fstrim.enable = true;
  hardware.bluetooth = {
    enable = true;
    powerOnBoot = true;
  };
  services.upower.enable = true;
  services.power-profiles-daemon.enable = true;
}
