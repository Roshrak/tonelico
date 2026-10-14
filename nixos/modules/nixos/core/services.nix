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
  services.accounts-daemon.enable = true;
  programs.dconf.enable = true;
  programs.gdk-pixbuf.modulePackages = [ pkgs.librsvg ];

  programs.nix-ld.enable = true;
  xdg.portal.enable = true;
  services.flatpak.enable = true;
}
