{ ... }:
{
  nixos.session-lifecycle =
    { config, lib, pkgs, ... }:

    let
      themeSessionLease = pkgs.writeShellScriptBin "theme-session-lease" ''
        set -euo pipefail
        COREUTILS=${pkgs.coreutils}/bin
        FLOCK=${pkgs.util-linux}/bin/flock
        STAT=${pkgs.coreutils}/bin/stat
        runtime_dir="''${XDG_RUNTIME_DIR:-}"
        [ -n "$runtime_dir" ] || {
          echo "theme-session-lease: XDG_RUNTIME_DIR is missing" >&2
          exit 1
        }
        [ -d "$runtime_dir" ] && [ ! -L "$runtime_dir" ] || {
          echo "theme-session-lease: runtime directory is not a real directory" >&2
          exit 1
        }
        uid="$("$COREUTILS/id" -u)"
        runtime_owner="$("$STAT" -c '%u:%a' -- "$runtime_dir")"
        [ "$runtime_owner" = "$uid:700" ] || {
          echo "theme-session-lease: runtime directory owner/mode is unsafe" >&2
          exit 1
        }
        lock_path="$runtime_dir/tonelico-graphical-session.lock"
        [ ! -L "$lock_path" ] || {
          echo "theme-session-lease: lock path is a symlink" >&2
          exit 1
        }
        [ "$#" -gt 0 ] || {
          echo "usage: theme-session-lease command [arguments...]" >&2
          exit 2
        }
        umask 077
        if "$FLOCK" --nonblock --conflict-exit-code 75 --close "$lock_path" "$@"; then
          rc=0
        else
          rc=$?
        fi
        if [ "$rc" -eq 75 ]; then
          echo "theme-session-lease: another graphical session owns the shared user-session lease" >&2
        fi
        exit "$rc"
      '';
      sessionLeaseGuard = ''
        if [ "''${THEME_SESSION_LEASE_HELD:-0}" != 1 ]; then
          [ -n "''${XDG_RUNTIME_DIR:-}" ] || {
            echo "graphical session has no XDG_RUNTIME_DIR; refusing shared session changes" >&2
            exit 1
          }
          exec ${pkgs.coreutils}/bin/env THEME_SESSION_LEASE_HELD=1 \
            /run/current-system/sw/bin/theme-session-lease "$0" "$@"
        fi
        unset THEME_SESSION_LEASE_HELD
      '';

      # Place the startup pointer on the laptop panel where compositor IPC allows
      # a safe one-shot warp. Niri centers the cursor on its focus-at-startup
      # output natively, and its Kanshi hook repeats that on hotplug. All four
      # Wayland compositors use their compositor IPC rather than input injection.
      desktopMainPointer = pkgs.writeShellScriptBin "desktop-main-pointer" ''
        set -u
        JQ=${pkgs.jq}/bin/jq
        SLEEP=${pkgs.coreutils}/bin/sleep
        mode="''${1:-}"

        case "$mode" in
          sway|hyprland)
            attempt=0
            while [ "$attempt" -lt 20 ]; do
              if [ "$mode" = sway ]; then
                json="$(/run/current-system/sw/bin/swaymsg -t get_outputs 2>/dev/null || true)"
                coords="$(printf '%s' "$json" | "$JQ" -r '
                  .[] | select(.name == "eDP-1" and .active) |
                  [.rect.x, .rect.y, .rect.width, .rect.height] | @tsv' 2>/dev/null || true)"
              else
                json="$(/run/current-system/sw/bin/hyprctl -j monitors 2>/dev/null || true)"
                coords="$(printf '%s' "$json" | "$JQ" -r '
                  .[] | select(.name == "eDP-1" and ((.disabled // false) == false)) |
                  [(.x + (.width / (.scale // 1)) / 2 | floor),
                   (.y + (.height / (.scale // 1)) / 2 | floor)] | @tsv' 2>/dev/null || true)"
              fi
              if [ -n "$coords" ]; then
                if [ "$mode" = sway ]; then
                  read -r x y width height <<< "$coords"
                  /run/current-system/sw/bin/swaymsg \
                    "seat seat0 cursor set $((x + width / 2)) $((y + height / 2))" \
                    >/dev/null 2>&1 || true
                else
                  read -r x y <<< "$coords"
                  /run/current-system/sw/bin/hyprctl dispatch movecursor "$x" "$y" \
                    >/dev/null 2>&1 || true
                fi
                exit 0
              fi
              attempt=$((attempt + 1))
              "$SLEEP" 0.15
            done
            ;;
          niri)
            # Niri's focus-monitor IPC moves the cursor onto the chosen output.
            # Retry briefly because Kanshi may invoke us while the compositor is
            # still initializing after login or a hotplug event.
            attempt=0
            while [ "$attempt" -lt 20 ]; do
              if /run/current-system/sw/bin/niri msg action focus-monitor eDP-1 >/dev/null 2>&1; then
                exit 0
              fi
              attempt=$((attempt + 1))
              "$SLEEP" 0.15
            done
            ;;
          mango)
            MMSG=/run/current-system/sw/bin/mmsg
            attempt=0
            while [ "$attempt" -lt 20 ]; do
              if "$MMSG" get monitor eDP-1 >/dev/null 2>&1; then
                # Moving to the external output and back forces Mango's native
                # warpcursor policy to center the pointer on eDP-1. If HDMI is not
                # connected the first dispatch is a harmless no-op.
                "$MMSG" dispatch focusmon,HDMI-A-1 >/dev/null 2>&1 || true
                "$MMSG" dispatch focusmon,eDP-1 >/dev/null 2>&1 || true
                exit 0
              fi
              attempt=$((attempt + 1))
              "$SLEEP" 0.15
            done
            ;;
          *)
            echo "usage: desktop-main-pointer <sway|hyprland|niri|mango>" >&2
            exit 2
            ;;
        esac
      '';

      hyprlandSessionGuarded = pkgs.writeShellScriptBin "hyprland-session-guarded" ''
        set -u
        ${sessionLeaseGuard}
        for arg in "$@"; do
          case "$arg" in
            -c|--config|--config=*|--config-file|--config-file=*|-c?*)
              echo "hyprland-session-guarded uses the declarative config; rejected: $arg" >&2
              exit 2
              ;;
          esac
        done
        /run/current-system/sw/bin/theme-session-admit || exit $?
        unset WAYLAND_DISPLAY DISPLAY XAUTHORITY NIRI_SOCKET SWAYSOCK \
          MANGO_INSTANCE_SIGNATURE HYPRLAND_INSTANCE_SIGNATURE \
          KDE_FULL_SESSION KDE_SESSION_VERSION KDE_SESSION_UID KDE_SESSION_VT \
          GNOME_DESKTOP_SESSION_ID GNOME_SETUP_DISPLAY MATE_DESKTOP_SESSION_ID \
          CINNAMON_VERSION LXQT_SESSION_CONFIG LXQT_SESSION_ID AWESOME_CONF \
          NIX_GSETTINGS_OVERRIDES_DIR
        /run/current-system/sw/bin/theme-session-cleanup >/dev/null 2>&1 || true
        export XDG_CURRENT_DESKTOP=Hyprland
        export XDG_SESSION_DESKTOP=Hyprland
        export XDG_SESSION_TYPE=wayland
        export DESKTOP_SESSION=hyprland
        export THEME_PROFILE=hyprland
        export NOCTALIA_CONFIG_HOME="$HOME/.config/theme-profiles/hyprland/config-home"
        export NOCTALIA_STATE_HOME="$HOME/.local/state/theme-profiles/hyprland"
        export KITTY_CONFIG_DIRECTORY="$HOME/.config/kitty/profiles/hyprland"
        export QT_QPA_PLATFORMTHEME=qt6ct

        on_exit() {
          /run/current-system/sw/bin/theme-session-cleanup >/dev/null 2>&1 || true
        }
        trap on_exit EXIT TERM INT HUP

        vars=(XDG_CURRENT_DESKTOP XDG_SESSION_DESKTOP XDG_SESSION_TYPE XDG_SESSION_ID DESKTOP_SESSION
          THEME_PROFILE NOCTALIA_CONFIG_HOME NOCTALIA_STATE_HOME
          KITTY_CONFIG_DIRECTORY QT_QPA_PLATFORMTHEME)
        /run/current-system/sw/bin/systemctl --user import-environment "''${vars[@]}" 2>/dev/null || true
        /run/current-system/sw/bin/dbus-update-activation-environment --systemd "''${vars[@]}" 2>/dev/null || true

        /run/current-system/sw/bin/theme-profile-activate hyprland >/dev/null 2>&1 || true
        /run/current-system/sw/bin/systemctl --user start geoclue-agent.service 2>/dev/null || true
        /run/current-system/sw/bin/desktop-main-pointer hyprland >/dev/null 2>&1 &
        pointer_pid=$!
        # Home Manager owns the primary user's Lua settings. Other accounts keep
        # the system fallback, so login integration does not depend on HM.
        hypr_config="$HOME/.config/hypr/hyprland.lua"
        [ -f "$hypr_config" ] || hypr_config=/etc/xdg/hypr/hyprland.lua
        /run/current-system/sw/bin/start-hyprland -- --config "$hypr_config" "$@"
        rc=$?
        kill -TERM "$pointer_pid" 2>/dev/null || true
        wait "$pointer_pid" 2>/dev/null || true
        trap - EXIT
        on_exit
        exit "$rc"
      '';
    in
    {
      # Keep NixOS's geoclue demo agent for the five sessions. It is started per
      # session, never at login.
      services.geoclue2.enableDemoAgent = lib.mkForce true;
      systemd.user.services.geoclue-agent.wantedBy = lib.mkForce [ ];

      # Never export the GNOME settings override directory, to any session.
      environment.sessionVariables.NIX_GSETTINGS_OVERRIDES_DIR = lib.mkForce null;

      # Cloudflare WARP ships this tray helper as a default.target user service.
      # During an X11-to-Wayland handoff it may exit with the old DISPLAY before
      # the new compositor imports its display values; immediate retries exhaust
      # systemd's start limit before the new session is ready.
      systemd.user.services.warp-taskbar = {
        overrideStrategy = "asDropin";
        unitConfig = {
          StartLimitIntervalSec = "30s";
          StartLimitBurst = 4;
        };
        serviceConfig = {
          Restart = lib.mkForce "on-failure";
          RestartSec = "5s";
        };
      };

      environment.systemPackages = [
        themeSessionLease
        desktopMainPointer
        hyprlandSessionGuarded
      ];
    }
  ;
}
