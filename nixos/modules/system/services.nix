{ ... }:
{
  nixos.services =
    { pkgs, ... }:
    {
      # File manager integration, removable drives, and encrypted Secret Service.
      services.gvfs.enable = true;
      # GVFS spawns wsdd by name; give this package the missing discovery helper.
      # Keep the full GNOME integration and existing wrapper arguments.
      services.gvfs.package = (pkgs.gvfs.override { gnomeSupport = true; }).overrideAttrs (old: {
        preFixup = (old.preFixup or "") + ''
          gappsWrapperArgs+=(--prefix PATH : "${pkgs.wsdd}/bin")
        '';
      });
      services.udisks2.enable = true;
      services.gnome.gnome-keyring.enable = true;
      # Pinned during the GNOME/XFCE/X11 removal (was implied by the GNOME module):
      # colord is used by Plasma/KWin color management, and glib-networking provides
      # TLS to GTK/GIO applications in the remaining sessions.
      services.colord.enable = true;
      services.gnome.glib-networking.enable = true;
      # Nautilus (installed) uses the localsearch indexer and the tinysparql store for
      # search and recent files. Both were implied by the GNOME module before its removal.
      services.gnome.localsearch.enable = true;
      services.gnome.tinysparql.enable = true;
      # NixOS lists every D-Bus package twice (its own dbus-1 dir and system-path).
      # dbus-broker logs "Ignoring duplicate name" for each one on every boot and
      # reload; the classic dbus-daemon resolves the same names without warnings.
      services.dbus.implementation = "dbus";
      services.accounts-daemon.enable = true;
      programs.dconf.enable = true;
      programs.gdk-pixbuf.modulePackages = [ pkgs.librsvg ];

      programs.nix-ld.enable = true;
      xdg.portal.enable = true;
      services.flatpak.enable = true;
    }
  ;
}
