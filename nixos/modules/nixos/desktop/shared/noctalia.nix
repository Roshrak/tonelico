{ pkgs, inputs, ... }:
{
  imports = [
    inputs.noctalia.nixosModules.default
    inputs.noctalia-greeter.nixosModules.default
  ];

  # Mango compositor and a graphical login screen.
  services.displayManager.sddm.enable = false;

  services.displayManager.noctalia-greeter = {
    enable = true;

    settings = {
      appearance.hide_logo = true;
      cursor = {
        theme = "Bibata-Modern-Ice";
        size = 24;
        path = "${pkgs.bibata-cursors}/share/icons";
      };

      output = {
        # Keep the login UI on the laptop panel. Noctalia disables other KMS
        # connectors only for the greeter and restores them for the user session.
        name = "eDP-1";
        layout = "HDMI-A-1:0,60; eDP-1:1920,0";
      };

      keyboard.layout = "us";
      idle.timeout = 300;
    };
  };
  services.xserver.desktopManager.runXdgAutostartIfNone = true;

  # Noctalia supplies the bar, launcher, notifications, control center,
  # wallpaper, lock screen, OSD, tray, and clipboard history.
  programs.noctalia = {
    enable = true;
    recommendedServices.enable = true;
    systemd.enable = false; # Started once by Mango instead.
  };
}
