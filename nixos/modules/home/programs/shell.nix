{ ... }:
{
  homeManager.shell =
    { lib, config, ... }:
    {
      programs.bash = {
        enable = true;
        package = null; # NixOS supplies the account's shell.
        shellAliases = {
          agy = "agy --dangerously-skip-permissions";
          opencode = "opencode --auto";
          # Claude Code never saves folder trust for $HOME; start it in ~/vivian instead.
          cv = "cd ~/vivian && claude";
        };
        initExtra = ''
          export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
          export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
          export BUN_OPTIONS="--use-system-ca"

          # Window title: running command name while busy, "Morgan" at the prompt.
          __morgan_idle() { printf '\033]0;Morgan\007'; }
          __morgan_preexec() {
            [ -n "''${COMP_LINE:-}" ] && return
            case "$BASH_COMMAND" in
              __morgan_*|starship_*|PROMPT_COMMAND*) return ;;
            esac
            printf '\033]0;%s\007' "''${BASH_COMMAND%% *}"
          }
          trap '__morgan_preexec' DEBUG
          PROMPT_COMMAND="''${PROMPT_COMMAND:+$PROMPT_COMMAND; }__morgan_idle"

          if [ -z "''${KITTY_CONFIG_DIRECTORY:-}" ]; then
            case "''${XDG_CURRENT_DESKTOP:-}" in
              *sway*|*Sway*) export KITTY_CONFIG_DIRECTORY="$HOME/.config/kitty/profiles/sway" ;;
              *niri*|*Niri*) export KITTY_CONFIG_DIRECTORY="$HOME/.config/kitty/profiles/niri" ;;
              *mango*|*Mango*) export KITTY_CONFIG_DIRECTORY="$HOME/.config/kitty/profiles/mango" ;;
              *KDE*|*kde*|*Plasma*|*plasma*) export KITTY_CONFIG_DIRECTORY="$HOME/.config/kitty/profiles/kde" ;;
            esac
          fi
        '';
      };

      programs.starship = {
        enable = true;
        enableBashIntegration = true;
      };
      xdg.configFile."starship.toml".source = ../../../home/files/config/starship/starship.toml;
    }
  ;
}
