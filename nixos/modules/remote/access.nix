{ ... }:
{
  nixos.access =
    { pkgs, ... }:
    {
      # RustDesk background service: accepts incoming connections (the GUI alone cannot).
      systemd.services.rustdesk = {
        description = "RustDesk remote desktop service";
        wantedBy = [ "multi-user.target" ];
        after = [ "network-online.target" ];
        wants = [ "network-online.target" ];
        # RustDesk starts the user session server with sudo; NixOS keeps sudo in the setuid wrappers.
        path = [
          "/run/wrappers"
          "/run/current-system/sw"
        ];
        # Capture uses X11 through xwayland-satellite on DISPLAY :0; the Wayland
        # portal path fails on niri (PipeWire "no more input formats").
        environment = {
          DISPLAY = ":0";
          XDG_RUNTIME_DIR = "/run/user/1000";
          XDG_SESSION_TYPE = "wayland";
        };
        serviceConfig = {
          ExecStart = "${pkgs.rustdesk-flutter}/bin/rustdesk --service";
          Restart = "on-failure";
        };
      };

      # Private remote access: reachable only over the Tailscale network.
      # Nothing is opened on the router or on the public interfaces.
      services.tailscale = {
        enable = true;
        # Trust only the tailnet interface for inbound connections.
        useRoutingFeatures = "none";
      };

      # Sunshine streams the desktop to Moonlight. Its ports are opened
      # on tailscale0 only, never on the public interfaces.
      services.sunshine = {
        enable = true;
        autoStart = false; # started on demand by remote mode, not at boot
        openFirewall = false;
        # KMS capture needs this capability; without it Wayland capture fails on Intel.
        capSysAdmin = true;
      };

      networking.firewall.interfaces.tailscale0.allowedTCPPorts = [ 47984 47989 47990 48010 ];
      networking.firewall.interfaces.tailscale0.allowedUDPPorts = [ 47998 47999 48000 48002 48010 ];
    }
  ;
}
