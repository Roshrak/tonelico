{ ... }:
{
  nixos.recovery =
    { pkgs, lib, host, ... }:
    lib.mkIf (host.retainLocalRecovery or false) {
      # The only fallback is the system profile system-profiles/fallback: its profile
      # link pins the closure, and the boot builder generates its entry from it.
      # Validate that entry on every install; quarantine the two rejected generations
      # and preserve all forensic bytes. Fresh hosts leave this off.
      boot.loader.systemd-boot.extraInstallCommands = ''
        ${pkgs.python3}/bin/python3 ${../../recovery/quarantine.py}
      '';
    }
  ;
}
