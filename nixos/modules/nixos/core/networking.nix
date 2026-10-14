{ ... }:
{
  networking.networkmanager.enable = true;
  networking.firewall.enable = true;

  services.cloudflare-warp.enable = true;
}
