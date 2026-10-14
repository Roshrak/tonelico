{ lib, config, ... }:
{
  programs.bash = {
    enable = true;
    package = null; # NixOS supplies the account's shell.
    shellAliases = {
      agy = "agy --dangerously-skip-permissions";
      opencode = "opencode --auto";
    };
    initExtra = ''
      export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
      export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
      export BUN_OPTIONS="--use-system-ca"

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
}
