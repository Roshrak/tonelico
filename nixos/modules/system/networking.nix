{ ... }:
{
  nixos.networking =
    { ... }:
    {
      networking.networkmanager.enable = true;
      # Resolve .local names through Avahi (avahi warned "No NSS support for mDNS").
      services.avahi.nssmdns4 = true;
      networking.firewall.enable = true;

      services.cloudflare-warp.enable = true;
    }
  ;
}
