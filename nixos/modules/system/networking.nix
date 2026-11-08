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
      # Local caching stub resolver (0.1ms cached DNS lookups + Tailscale split-DNS integration).
      services.resolved = {
        enable = true;
        settings.Resolve = {
          DNSSEC = "allow-downgrade";
          FallbackDNS = [ "8.8.8.8" "1.1.1.1" "8.8.4.4" "1.0.0.1" ];
        };
      };
      # Resolve .local names through Avahi (avahi warned "No NSS support for mDNS").
      services.avahi.nssmdns4 = true;
      networking.firewall.enable = true;

      services.cloudflare-warp.enable = true;
    }
  ;
}
