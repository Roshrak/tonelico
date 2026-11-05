{ ... }:
{
  nixos.portals =
    { lib, pkgs, ... }:

    {
      # Upstream session modules each add their own portal backend, so the same
      # packages were listed several times (gtk x4, wlr x2). D-Bus then reported
      # every duplicate service file on each boot. Each backend is listed once.
      xdg.portal.extraPortals = lib.mkForce [
        pkgs.xdg-desktop-portal-gtk
        pkgs.xdg-desktop-portal-wlr
        pkgs.xdg-desktop-portal-gnome
        pkgs.xdg-desktop-portal-hyprland
        pkgs.kdePackages.xdg-desktop-portal-kde
        pkgs.kdePackages.kwallet
        pkgs.gnome-keyring
      ];

      # Use the NixOS portal module's typed config so these files replace the
      # upstream per-DE defaults cleanly instead of concatenating duplicate
      # [preferred] sections into /etc.
      xdg.portal.config = {
        mango = {
          "org.freedesktop.impl.portal.FileChooser" = lib.mkForce "kde";
          default = [ "gtk" ];
          "org.freedesktop.impl.portal.ScreenCast" = "wlr";
          "org.freedesktop.impl.portal.Screenshot" = "wlr";
          "org.freedesktop.impl.portal.Secret" = "gnome-keyring";
        };

        niri = {
          # The pinned Niri module defaults to GNOME then GTK. Keep GTK as the
          # general UI backend and choose GNOME specifically for capture.
          default = lib.mkForce [ "gtk" ];
          "org.freedesktop.impl.portal.Access" = "gtk";
          "org.freedesktop.impl.portal.FileChooser" = lib.mkForce "kde";
          "org.freedesktop.impl.portal.Notification" = "gtk";
          "org.freedesktop.impl.portal.ScreenCast" = "gnome";
          "org.freedesktop.impl.portal.Screenshot" = "gnome";
          "org.freedesktop.impl.portal.Secret" = "gnome-keyring";
        };

        sway = {
          "org.freedesktop.impl.portal.FileChooser" = lib.mkForce "kde";
          # Keep the upstream Sway GTK + wlroots routing and add the shared
          # Secret Service portal explicitly.
          "org.freedesktop.impl.portal.Secret" = "gnome-keyring";
        };

        hyprland = {
          "org.freedesktop.impl.portal.FileChooser" = lib.mkForce "kde";
          default = [ "gtk" ];
          "org.freedesktop.impl.portal.GlobalShortcuts" = "hyprland";
          "org.freedesktop.impl.portal.ScreenCast" = "hyprland";
          "org.freedesktop.impl.portal.Screenshot" = "hyprland";
          "org.freedesktop.impl.portal.Secret" = "gnome-keyring";
        };

        kde = {
          default = [ "kde" ];
          "org.freedesktop.impl.portal.Secret" = "kwallet";
        };

      };

      # Chromium, Electron (Discord, ...) and Firefox only use the portal file picker when
      # GTK_USE_PORTAL is set; otherwise they open their own GTK dialog.
      environment.sessionVariables.GTK_USE_PORTAL = "1";
    }
  ;
}
