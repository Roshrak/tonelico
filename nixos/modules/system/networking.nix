{ ... }:
{
  nixos.networking =
    { ... }:
    {
      networking.networkmanager = {
        enable = true;
        # Disable Wi-Fi DTIM power-save to eliminate 15-60ms ping spikes & jitter.
        wifi.powersave = false;
      };
      # Resolve .local names through Avahi (avahi warned "No NSS support for mDNS").
      services.avahi.nssmdns4 = true;
      networking.firewall.enable = true;

      services.cloudflare-warp.enable = true;
    }
  ;
}
