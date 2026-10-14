{
  pkgs,
  lib,
  host,
  ...
}:
let
  # Explicit opaque store contexts retain existing immutable recovery objects.
  store =
    path:
    builtins.appendContext path {
      ${path} = {
        path = true;
      };
    };
in
lib.mkIf (host.retainLocalRecovery or false) {
  # Recovery store paths are local to this machine; fresh hosts leave this off.
  # Keep the user-accepted generations reachable independently of profile pruning.
  system.extraDependencies = [
    (store "/nix/store/zwwx7k1daydzxa9q4hkgyncwvr3vcg1r-nixos-system-tonelico-nix-26.05.20260927.cf5e765")
    (store "/nix/store/iiqszz4m6859cl2q80pl606j7va32gk1-nixos-system-tonelico-nix-26.05.20260927.cf5e765")
    (store "/nix/store/zh9i0hirgcvkxyyj4h0m086fsnmyz8hz-nixos-system-tonelico-nix-26.05.20261002.774debe")
  ];
  boot.loader.systemd-boot.extraEntries = {
    "nixos-fallback-1-generation-129.conf" =
      builtins.readFile ../../../recovery/fallback-1-generation-129.conf;
    "nixos-fallback-2-generation-135.conf" =
      builtins.readFile ../../../recovery/fallback-2-generation-135.conf;
    "nixos-generation-129.conf" = builtins.readFile ../../../recovery/gen129.conf;
    "nixos-generation-128.conf" = builtins.readFile ../../../recovery/gen128.conf;
  };
  boot.loader.systemd-boot.extraFiles = {
    "EFI/nixos/1bkxyl7i129iwah46phnzv8sb683ia7n-initrd-linux-7.2.8-initrd.efi" =
      (store "/nix/store/1bkxyl7i129iwah46phnzv8sb683ia7n-initrd-linux-7.2.8") + "/initrd";
    "EFI/nixos/bv3hys3v0lpndipr6wp7qahq2kpffb61-linux-7.2.8-bzImage.efi" =
      (store "/nix/store/bv3hys3v0lpndipr6wp7qahq2kpffb61-linux-7.2.8") + "/bzImage";
  };
  # Quarantine only the two rejected generations; preserve all forensic bytes.
  boot.loader.systemd-boot.extraInstallCommands = ''
    ${pkgs.python3}/bin/python3 ${../../../recovery/quarantine.py}
  '';
}
