{ ... }:
{
  nixos.fast-reboot =
    { lib, ... }:
    {
      # Stop jobs: nothing on this laptop needs the stock 90s grace period.
      systemd.settings.Manager.DefaultTimeoutStopSec = "5s";
      systemd.user.extraConfig = ''
        DefaultTimeoutStopSec=2s
      '';
      # Rootless dockerd stops its containers (stop_grace_period 2s) before exiting.
      systemd.user.services.docker.serviceConfig.TimeoutStopSec = lib.mkForce "4s";
      # tailscaled spends ~2.5s on log upload retries at shutdown; NetworkManager
      # and the firewall wait for it.
      systemd.services.tailscaled.serviceConfig.TimeoutStopSec = "1500ms";
      systemd.services.thermald.serviceConfig.TimeoutStopSec = "1s";

      # Start jobs: Home Manager activation (~1.1s) no longer holds back the
      # greeter. Links from the previous activation are already in $HOME, and the
      # activation finishes well before a password can be typed.
      systemd.services.home-manager-aesc.before = lib.mkForce [ "multi-user.target" ];

      # No kexec reboot: tried on 2026-10-20. Without the firmware reset, iwlwifi
      # failed to probe (-110) and i915 declared the GPU wedged.
    }
  ;
}
