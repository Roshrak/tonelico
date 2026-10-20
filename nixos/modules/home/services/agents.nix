{ ... }:
{
  homeManager.agents =
    { config, lib, pkgs, ... }:
    let
      home = config.home.homeDirectory;
      bridgePython = pkgs.python3.withPackages (ps: [ ps.aiohttp ]);
      path = lib.makeBinPath [ pkgs.bashInteractive pkgs.coreutils pkgs.git pkgs.curl pkgs.python3 pkgs.nodejs ]
        + ":${home}/.local/bin:/etc/profiles/per-user/${config.home.username}/bin:${home}/.nix-profile/bin:/run/current-system/sw/bin";
    in
    {
      systemd.user.services.agy-bridge = {
        Unit = {
          Description = "Antigravity Pro Bridge - Persistent Google AI Pro OpenAI Adapter";
          After = [ "network-online.target" ];
          Wants = [ "network-online.target" ];
        };
        Service = {
          Type = "simple";
          ExecStart = "${bridgePython}/bin/python3 ${home}/.hermes/agy_bridge.py";
          WorkingDirectory = "${home}/.hermes";
          Environment = [ "PATH=${path}" "HOME=${home}" "AGY_BRIDGE_TIMEOUT_SECONDS=1800" "AGY_PRINT_TIMEOUT=30m" ];
          Restart = "always";
          RestartSec = 3;
        };
        Install.WantedBy = [ "default.target" ];
      };
      systemd.user.services.mc-chat-responder = {
        Unit = {
          Description = "Minecraft Auto Chat Responder for Roshrak (Morgan AI)";
          After = [ "network.target" "agy-bridge.service" ];
          Wants = [ "agy-bridge.service" ];
        };
        Service = {
          Type = "simple";
          ExecStart = "${pkgs.python3}/bin/python3 ${home}/.local/bin/mc_chat_responder.py";
          Restart = "on-failure";
          RestartSec = 3;
          Environment = [ "HOME=${home}" "PATH=${path}" "XDG_RUNTIME_DIR=%t" ];
        };
        Install.WantedBy = [ "default.target" ];
      };
      # The gateway's base unit belongs to the installed Hermes runtime. Preserve
      # it without restarting it; Home Manager owns the NixOS ExecReload adapter.
      xdg.configFile."systemd/user/hermes-gateway.service.d/10-home-manager.conf".text = ''
        [Service]
        ExecReload=
        ExecReload=${pkgs.util-linux}/bin/kill -USR1 $MAINPID
      '';
    }
  ;
}
