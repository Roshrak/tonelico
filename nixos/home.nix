{ config, ... }:
{
  imports = [
    ./home/programs/shell.nix
    ./home/programs/git.nix
    ./home/programs/kitty.nix
    ./home/programs/neovim.nix
    ./home/programs/fastfetch.nix
    ./home/packages/communication.nix
    ./home/packages/browsers.nix
    ./home/packages/productivity.nix
    ./home/packages/media.nix
    ./home/packages/gaming.nix
    ./home/packages/development.nix
    ./home/packages/utilities.nix
    ./home/packages/ai.nix
    ./home/desktop/configuration.nix
    ./home/desktop/gnome.nix
    ./home/services/agents.nix
    ./home/files/scripts.nix
  ];

  # First Home Manager activation. This is a compatibility version, not a
  # release selector; preserve it when updating Home Manager later.
  home.stateVersion = "26.05";
  xdg.enable = true;
  home.sessionPath = [ "${config.home.homeDirectory}/.local/bin" ];
  home.sessionVariables = {
    BROWSER = "chromium";
    TERMINAL = "kitty";
    XCURSOR_THEME = "Bibata-Modern-Ice";
    XCURSOR_SIZE = "24";
  };

  # Activation must not restart the current desktop or working agents.
  # Existing enablement links are preserved; new logins use these definitions.
  systemd.user.startServices = false;
}
