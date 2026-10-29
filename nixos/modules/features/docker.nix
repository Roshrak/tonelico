{ ... }:
{
  nixos.docker =
    { pkgs, ... }:

    {
      virtualisation.docker.rootless = {
        enable = true;
        setSocketVariable = true;
      };
      # Docker's rootless daemon manages its firewall rules with nft; the unit's
      # PATH does not include it unless it is added here.
      systemd.user.services.docker.path = [ pkgs.nftables ];

      users.users.aesc.autoSubUidGidRange = true;
    }
  ;
}
