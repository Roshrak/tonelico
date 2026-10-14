{ config, lib, pkgs, inputs, ... }:
let
  home = config.home.homeDirectory;
  portable = path: lib.replaceStrings [ "/home/aesc" ] [ home ] (builtins.readFile path);
  chromium = pkgs.chromium.override { commandLineArgs = [ "--password-store=basic" ]; };
  discord = pkgs.discord.override { commandLineArgs = "--ozone-platform=x11"; };
  hermes = inputs.hermes-agent.packages.${pkgs.stdenv.hostPlatform.system}.messaging;
  chromiumLauncher = pkgs.writeShellScript "chromium-app" ''
    export WAYLAND_DISPLAY="''${WAYLAND_DISPLAY:-wayland-1}"
    export DISPLAY="''${DISPLAY:-:0}"
    export XDG_RUNTIME_DIR="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    exec ${chromium}/bin/chromium --ozone-platform=x11 --remote-debugging-port=9222 "$@"
  '';
  scripts = [
    "apply-theme-profile" "save-theme-profile" "sync-active-theme"
    "clean-stray-sessions" "hypr-active-window-screenshot"
    "hypr-noctalia-notification-owner" "hypr-session-ready"
    "mango-animation" "noctalia-greeter-sync-smart" "obs-fix-recording-paths"
    "mc_chat_responder.py"
  ];
in
{
  home.file = lib.listToAttrs (map (name: {
    name = ".local/bin/${name}";
    value = { text = portable (./bin + "/${name}"); executable = true; };
  }) scripts) // {
    ".hermes/agy_bridge.py".text = portable ./bin/agy_bridge.py;
    ".local/bin/chromium-app".source = chromiumLauncher;
    ".local/bin/chromium".source = chromiumLauncher;
    ".local/bin/obs-safe" = {
      executable = true;
      text = ''
        #!${pkgs.runtimeShell}
        set -euo pipefail
        "${home}/.local/bin/obs-fix-recording-paths"
        exec ${pkgs.obs-studio}/bin/obs "$@"
      '';
    };
    ".local/bin/Discord" = {
      executable = true;
      text = ''
        #!${pkgs.runtimeShell}
        exec ${discord}/bin/Discord --ozone-platform=x11 "$@"
      '';
    };
    ".local/bin/hermes" = {
      executable = true;
      text = ''
        #!${pkgs.runtimeShell}
        exec ${hermes}/bin/hermes "$@"
      '';
    };
  };
}
