{ pkgs, ... }:
{
  imports = [ ./recovery.nix ];

  # Reuse the existing 1 GiB EFI partition shared with Arch.
  # Preserve the existing five-entry limit and explicit recovery entries.
  boot.loader.systemd-boot = {
    enable = true;
    editor = false;
    configurationLimit = 5;
  };
  boot.loader.efi.canTouchEfiVariables = true;
  boot.kernelPackages = pkgs.linuxPackages_latest;
  # Never expose the physical PC-speaker bell. Desktop/media audio continues
  # through PipeWire; these modules are only for legacy console beeps.
  boot.blacklistedKernelModules = [
    "pcspkr"
    "snd_pcsp"
  ];
}
