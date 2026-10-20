{ ... }:
{
  homeManager.home-base =
    { config, ... }:
    {
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
    };
}
