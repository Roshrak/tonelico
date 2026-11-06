{ inputs, ... }:
{
  homeManager.scripts =
    { config, lib, pkgs, ... }:
    let
      home = config.home.homeDirectory;
      portable = path: lib.replaceStrings [ "/home/aesc" ] [ home ] (builtins.readFile path);
      chromium = pkgs.chromium-latest.override { commandLineArgs = [ "--password-store=basic" ]; };
      discord = pkgs.discord.override { commandLineArgs = "--ozone-platform=wayland"; };
      hermes = inputs.hermes-agent.packages.${pkgs.stdenv.hostPlatform.system}.messaging;
      chromiumLauncher = pkgs.writeShellScript "chromium-app" ''
        export WAYLAND_DISPLAY="''${WAYLAND_DISPLAY:-wayland-1}"
        export XDG_RUNTIME_DIR="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
        export GTK_USE_PORTAL=1
        exec ${chromium}/bin/chromium --ozone-platform=wayland --remote-debugging-port=9222 "$@"
      '';
      scripts = [
        "apply-theme-profile" "save-theme-profile" "sync-active-theme"
        "clean-stray-sessions" "hypr-active-window-screenshot"
        "hypr-noctalia-notification-owner" "hypr-session-ready"
        "mango-animation" "noctalia-greeter-sync-smart" "obs-fix-recording-paths"
        "mc_chat_responder.py" "mc_chat_responder_alt" "mc_responder_ctl"
      ];
    in
    {
      home.file = lib.listToAttrs (map (name: {
        name = ".local/bin/${name}";
        value = { text = portable (../../home/files/bin + "/${name}"); executable = true; force = true; };
      }) scripts) // {
        ".hermes/agy_bridge.py" = {
          text = portable ../../home/files/bin/agy_bridge.py;
          force = true;
        };
        ".local/bin/uinput_type" = {
          source = ../../home/files/bin/uinput_type;
          executable = true;
          force = true;
        };
        ".local/bin/chromium-app" = {
          source = chromiumLauncher;
          force = true;
        };
        ".local/bin/chromium" = {
          source = chromiumLauncher;
          force = true;
        };
        ".local/bin/obs-safe" = {
          executable = true;
          force = true;
          text = ''
            #!${pkgs.runtimeShell}
            set -euo pipefail
            "${home}/.local/bin/obs-fix-recording-paths"
            export QT_QPA_PLATFORM=wayland
            exec ${pkgs.obs-studio}/bin/obs "$@"
          '';
        };
        ".local/bin/Discord" = {
          executable = true;
          force = true;
          text = ''
            #!${pkgs.runtimeShell}
            export GTK_USE_PORTAL=1
            exec ${discord}/bin/Discord --ozone-platform=wayland "$@"
          '';
        };
        ".local/bin/hermes" = {
          executable = true;
          force = true;
          text = ''
            #!${pkgs.runtimeShell}
            exec ${hermes}/bin/hermes "$@"
          '';
        };
      };
    }
  ;
}
