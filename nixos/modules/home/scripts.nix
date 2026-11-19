{ inputs, ... }:
{
  homeManager.scripts =
    { config, lib, pkgs, ... }:
    let
      home = config.home.homeDirectory;
      portable = path: lib.replaceStrings [ "/home/aesc" ] [ home ] (builtins.readFile path);
      discord = pkgs.discord.override { commandLineArgs = "--ozone-platform=wayland"; };
      hermes = inputs.hermes-agent.packages.${pkgs.stdenv.hostPlatform.system}.messaging;
      scripts = [
        "apply-theme-profile" "save-theme-profile" "sync-active-theme"
        "clean-stray-sessions" "hypr-active-window-screenshot"
        "hypr-noctalia-notification-owner" "hypr-session-ready"
        "mango-animation" "noctalia-greeter-sync-smart" "obs-fix-recording-paths"
        "mc_chat_responder.py" "cfuk_hermes_brain.py" "mc_chat_responder_alt" "mc_responder_ctl"
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
        ".local/bin/zalo" = {
          executable = true;
          force = true;
          text = ''
            #!${pkgs.runtimeShell}
            set -euo pipefail
            uid="$(id -u)"
            runtime_dir="''${XDG_RUNTIME_DIR:-/run/user/$uid}"
            export XDG_RUNTIME_DIR="$runtime_dir"
            if [ -z "''${WAYLAND_DISPLAY:-}" ]; then
              for sock in wayland-1 wayland-0; do
                if [ -S "$runtime_dir/$sock" ]; then
                  export WAYLAND_DISPLAY="$sock"
                  break
                fi
              done
            fi
            export DISPLAY="''${DISPLAY:-:0}"
            display_num="''${DISPLAY#:}"
            display_num="''${display_num%%.*}"
            if [ -n "''${WAYLAND_DISPLAY:-}" ] && [ ! -S "/tmp/.X11-unix/X''${display_num}" ]; then
              xws_bin="$(command -v xwayland-satellite || true)"
              if [ -z "$xws_bin" ] && [ -x "${home}/.local/bin/xwayland-satellite" ]; then
                xws_bin="${home}/.local/bin/xwayland-satellite"
              fi
              if [ -n "$xws_bin" ]; then
                systemd-run --user --unit="xwayland-satellite-''${display_num}" --setenv="WAYLAND_DISPLAY=$WAYLAND_DISPLAY" "$xws_bin" ":''${display_num}" >/dev/null 2>&1 || true
                for _ in 1 2 3 4 5 6 7 8 9 10; do
                  [ -S "/tmp/.X11-unix/X''${display_num}" ] && break
                  sleep 0.1
                done
              fi
            fi
            if [ -x "${home}/.local/share/nix-roots/zalo/bin/zalo" ]; then
              exec "${home}/.local/share/nix-roots/zalo/bin/zalo" "$@"
            fi
            exec ${pkgs.zalo}/bin/zalo "$@"
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
