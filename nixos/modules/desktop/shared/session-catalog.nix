{ ... }:
{
  nixos.session-catalog =
    { config, lib, pkgs, ... }:

    let
      greeter = config.services.displayManager.noctalia-greeter;
      waylandNames = [
        "mango"
        "niri"
        "sway"
        "plasma"
        "hyprland"
      ];
      waylandPackages = lib.filter (
        package: lib.any (name: builtins.elem name waylandNames) (package.providedSessions or [ ])
      ) config.services.displayManager.sessionPackages;
      packagePaths = lib.concatStringsSep " " (map toString waylandPackages);

      dmSessionsShare =
        pkgs.runCommand "tonelico-curated-desktop-sessions"
          {
            meta.priority = 1;
          }
          ''
            mkdir -p "$out/share/wayland-sessions" "$out/share/xsessions"

            for name in mango niri sway plasma hyprland; do
              source=""
              for package in ${packagePaths}; do
                candidate="$package/share/wayland-sessions/$name.desktop"
                if [ -f "$candidate" ]; then
                  source="$candidate"
                  break
                fi
              done
              if [ -z "$source" ]; then
                echo "Required Wayland session $name.desktop was not provided by pinned nixpkgs/modules" >&2
                exit 1
              fi

              case "$name" in
                mango)
                  sed 's|^Exec=.*|Exec=/run/current-system/sw/bin/mango-session-guarded|' "$source" \
                    > "$out/share/wayland-sessions/$name.desktop"
                  ;;
                niri)
                  sed 's|^Exec=.*|Exec=/run/current-system/sw/bin/niri-session-guarded|' "$source" \
                    > "$out/share/wayland-sessions/$name.desktop"
                  ;;
                sway)
                  sed 's|^Exec=.*|Exec=/run/current-system/sw/bin/sway-session-guarded|' "$source" \
                    > "$out/share/wayland-sessions/$name.desktop"
                  ;;
                plasma)
                  sed 's|^Exec=.*|Exec=/run/current-system/sw/bin/plasma-session-guarded|' "$source" \
                    > "$out/share/wayland-sessions/$name.desktop"
                  ;;
                hyprland)
                  sed 's|^Exec=.*|Exec=/run/current-system/sw/bin/hyprland-session-guarded|' "$source" \
                    > "$out/share/wayland-sessions/$name.desktop"
                  ;;
              esac
            done

            hide_session() {
              kind="$1"
              name="$2"
              case "$kind" in
                wayland) directory="$out/share/wayland-sessions" ;;
                x11) directory="$out/share/xsessions" ;;
                *) exit 2 ;;
              esac
              cat > "$directory/$name.desktop" <<EOF
            [Desktop Entry]
            Type=Application
            Name=Hidden session ($name)
            Exec=false
            Hidden=true
            NoDisplay=true
            EOF
            }

            # Keep alternate sessions out of Noctalia Greeter even when their package
            # is linked into the system profile alongside the selected session.
            for name in hyprland-uwsm; do
              hide_session wayland "$name"
            done
          '';
    in
    {
      environment.systemPackages = [ dmSessionsShare ];

      # The upstream module exposes the entire NixOS session registry through
      # XDG_DATA_DIRS. Show the greeter only the curated entries exported by the
      # system profile.
      services.greetd.settings.default_session.command = lib.mkForce (
        "${pkgs.coreutils}/bin/env XDG_DATA_DIRS=/run/current-system/sw/share "
        + "${greeter.package}/bin/noctalia-greeter-session -- ${greeter.greeter-args}"
      );

      # No X11 desktop is installed; the Wayland sessions run X clients through
      # Xwayland and xwayland-satellite.
      services.xserver.enable = false;

      assertions = [
        {
          assertion = builtins.length waylandNames == 5;
          message = "The curated Noctalia Greeter Wayland session allowlist must contain exactly five sessions.";
        }
        {
          assertion =
            !config.services.displayManager.gdm.enable
            && !config.services.displayManager.sddm.enable
            && !config.services.xserver.displayManager.lightdm.enable;
          message = "greetd + Noctalia Greeter is the only permitted display-manager stack for this host.";
        }
        {
          assertion = !config.programs.hyprland.withUWSM;
          message = "Only the plain Hyprland session is permitted; UWSM must remain disabled.";
        }
      ];
    }
  ;
}
