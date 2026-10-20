{ ... }:
{
  nixos.docker =
    { ... }:

    {
      virtualisation.docker.rootless = {
        enable = true;
        setSocketVariable = true;
      };

      users.users.aesc.autoSubUidGidRange = true;
    }
  ;
}
