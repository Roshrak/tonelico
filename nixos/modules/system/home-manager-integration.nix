# Wires Home Manager into NixOS for the host's primary user. `inputs` is
# captured from the flake rather than passed as specialArgs.
{ config, ... }:
let
  userModules = config.homeManager.user;
in
{
  nixos.home-manager-integration =
    { config, host, ... }:
    {
      home-manager = {
        useGlobalPkgs = true;
        useUserPackages = true;
        # Existing unmanaged files are preserved. A repeated collision aborts
        # rather than replacing an earlier backup.
        backupFileExtension = "before-home-manager-20261009";
        overwriteBackup = false;
        users.${host.primaryUser} = {
          imports = [ userModules ];
          home.username = host.primaryUser;
          home.homeDirectory = config.users.users.${host.primaryUser}.home;
        };
      };
    };
}
