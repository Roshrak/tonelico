{ config, ... }:
{
  nixos.boot =
    { pkgs, ... }:
    {
      imports = [ config.nixos.recovery config.nixos.fast-reboot ];

      # NixOS only on the 1 GiB EFI partition.
      # Preserve the existing five-entry limit and explicit recovery entries.
      boot.loader.systemd-boot = {
        enable = true;
        editor = false;
        configurationLimit = 5;
      };
      boot.loader.efi.canTouchEfiVariables = true;
      # Boot straight into the default generation; hold Space at power-on (or run
      # `systemctl reboot --boot-loader-menu=10`) to get the menu and older generations.
      boot.loader.timeout = 0;
      boot.kernelPackages = pkgs.linuxPackages_latest;
      # Never expose the physical PC-speaker bell. Desktop/media audio continues
      # through PipeWire; these modules are only for legacy console beeps.
      boot.blacklistedKernelModules = [
        "pcspkr"
        "snd_pcsp"
      ];
    }
  ;
}
