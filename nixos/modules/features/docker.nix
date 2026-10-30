{ ... }:
{
  nixos.docker =
    { lib, pkgs, ... }:

    {
      virtualisation.docker.rootless = {
        enable = true;
        setSocketVariable = true;
      };
      # Docker's rootless daemon manages its firewall rules with nft; the unit's
      # PATH does not include it unless it is added here.
      systemd.user.services.docker.path = [ pkgs.nftables ];
      # The rootless daemon belongs to the primary user only. Without this, the
      # greeter's user manager also starts it at boot, fails, and hits the start limit.
      systemd.user.services.docker.unitConfig.ConditionUser = lib.mkForce "aesc";
      # At boot the daemon starts before Tailscale DNS answers, and its embedded resolver
      # logs a burst of "failed to query external DNS server". Wait for the host resolver
      # (at most 30 s); always exit 0 so Docker never fails to start because of this.
      systemd.user.services.docker.serviceConfig.ExecStartPre = [
        (pkgs.writeShellScript "docker-wait-for-dns" ''
          host="''${1:-github.com}"; limit="''${2:-30}"
          for _ in $(${pkgs.coreutils}/bin/seq 1 "$limit"); do
            ${pkgs.getent}/bin/getent hosts "$host" >/dev/null 2>&1 && exit 0
            ${pkgs.coreutils}/bin/sleep 1
          done
          exit 0
        '')
      ];
      # The rootless socket is owned by the user; there is no "docker" group. Inside the
      # rootless namespace gid 0 maps to the user's own primary group (users, 100), so
      # "root" gives the socket the right group outside. ("users" maps to a subgid.)
      virtualisation.docker.rootless.daemon.settings.group = "root";

      users.users.aesc.autoSubUidGidRange = true;
    }
  ;
}
