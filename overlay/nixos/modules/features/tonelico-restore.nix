# Places the exported theme, wallpapers and desktop settings into the primary
# user's home on the first boot after install.sh staged them.
#
# Why a boot service and not Home Manager: Plasma and Noctalia rewrite their own
# settings files while a session is running, and Home Manager would turn them
# into read-only links. Copying plain files before the login screen starts
# means nothing is running that could overwrite them, and every setting stays
# editable afterwards.
{ ... }:
{
  nixos.tonelico-restore =
    { host, lib, pkgs, ... }:

    let
      user = host.primaryUser;
      home = "/home/${user}";
      stage = "/var/lib/tonelico/home";
      stateDir = "${home}/.local/state/tonelico";

      restore = pkgs.writeShellScript "tonelico-restore" ''
        set -euo pipefail
        export PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.findutils pkgs.gnugrep ]}

        version="$(cat ${stage}/.version 2>/dev/null || echo unknown)"
        if [ -f ${stateDir}/restored ] && [ "$(cat ${stateDir}/restored)" = "$version" ]; then
          echo "theme version $version is already in place"
          exit 0
        fi

        placed=0
        skipped=0
        while IFS= read -r -d "" src; do
          rel="''${src#${stage}/}"
          dest="${home}/$rel"
          dir="$(dirname "$dest")"

          # Never replace anything Home Manager (or another Nix profile) owns.
          resolved="$(realpath -m -- "$dir")/$(basename "$dest")"
          if { [ -L "$dest" ] && [ ! -L "$src" ]; } || [[ "$(realpath -m -- "$dest")" == /nix/store/* ]] || [[ "$resolved" == /nix/store/* ]]; then
            skipped=$((skipped + 1))
            continue
          fi

          mkdir -p -- "$dir"
          if [ -L "$src" ]; then
            # A link between the user's own files (for example the Noctalia profiles
            # that share ~/.local/state/noctalia). Never replace something that exists.
            if [ -e "$dest" ] || [ -L "$dest" ]; then skipped=$((skipped + 1)); continue; fi
            ln -s -- "$(readlink -- "$src")" "$dest"
          else
            cp -f --no-preserve=ownership -- "$src" "$dest"
          fi
          placed=$((placed + 1))
        done < <(find ${stage} \( -type f -o -type l \) -not -name .version -print0)

        mkdir -p -- ${stateDir}
        printf '%s\n' "$version" > ${stateDir}/restored
        echo "placed $placed files, left $skipped Home Manager links alone"
      '';
    in
    {
      # install.sh stages the files; without them this unit simply does not run.
      systemd.services.tonelico-restore = {
        description = "Place the Tonelico theme and wallpapers into ${home}";
        wantedBy = [ "multi-user.target" ];
        before = [ "display-manager.service" "greetd.service" ];
        after = [ "home-manager-${user}.service" "local-fs.target" ];
        unitConfig.ConditionPathExists = "${stage}/.version";
        serviceConfig = {
          Type = "oneshot";
          User = user;
          RemainAfterExit = true;
          ExecStart = restore;
        };
      };

      # install.sh --post uses this file to tell that the new system is running.
      environment.etc."tonelico-installed".text = "tonelico\n";
    }
  ;
}
