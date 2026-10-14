{ config, host, inputs, ... }:
{
  home-manager = {
    useGlobalPkgs = true;
    useUserPackages = true;
    extraSpecialArgs = { inherit inputs host; };
    # Existing unmanaged files are preserved. A repeated collision aborts
    # rather than replacing an earlier backup.
    backupFileExtension = "before-home-manager-20261009";
    overwriteBackup = false;
    users.${host.primaryUser} = {
      imports = [ ./home.nix ];
      home.username = host.primaryUser;
      home.homeDirectory = config.users.users.${host.primaryUser}.home;
    };
  };
}
