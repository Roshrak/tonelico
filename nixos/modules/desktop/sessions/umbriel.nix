{ inputs, ... }:
{
  nixos.umbriel =
    { pkgs, ... }:
    {
      imports = [ inputs.umbriel.nixosModules.default ];

      programs.umbriel = {
        enable = true;
        # Portal routing is centrally managed in modules/desktop/shared/portals.nix
        portalPackage = null;
      };

      environment.systemPackages = with pkgs; [
        wl-clipboard
        cliphist
        grim
        slurp
        swaybg
        brightnessctl
        pamixer
        playerctl
        networkmanagerapplet
        polkit_gnome
      ];
    };
}
