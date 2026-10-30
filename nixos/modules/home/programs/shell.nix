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

      programs.starship = {
        enable = true;
        enableBashIntegration = true;
        # Minimal two-line prompt modelled on Starship's "Pure" preset.
        settings = {
          add_newline = true;
          command_timeout = 1000;
          format = lib.concatStrings [
            "$username"
            "$hostname"
            "$directory"
            "$git_branch"
            "$git_state"
            "$git_status"
            "$nix_shell"
            "$cmd_duration"
            "$line_break"
            "$character"
          ];
          directory = {
            style = "blue";
            truncation_length = 3;
          };
          character = {
            success_symbol = "[❯](purple)";
            error_symbol = "[❯](red)";
            vimcmd_symbol = "[❮](green)";
          };
          git_branch = {
            format = "[$branch]($style)";
            style = "bright-black";
          };
          # Zero-width values make any change show as a single "*".
          git_status = {
            format = "[[(*$conflicted$untracked$modified$staged$renamed$deleted)](218) ($ahead_behind$stashed)]($style)";
            style = "cyan";
            conflicted = "​";
            untracked = "​";
            modified = "​";
            staged = "​";
            renamed = "​";
            deleted = "​";
            stashed = "≡";
          };
          git_state = {
            format = "\\([$state( $progress_current/$progress_total)]($style)\\) ";
            style = "bright-black";
          };
          nix_shell = {
            format = "[$symbol]($style) ";
            symbol = "❄";
            style = "bright-black";
          };
          cmd_duration = {
            format = "[$duration]($style) ";
            style = "yellow";
          };
        };
      };
    }
  ;
}
