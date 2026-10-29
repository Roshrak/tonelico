# Sway Wayland compositor + Noctalia v5 shell as an independent session.
# Strictly additive: preserves the existing Mango, Niri, Plasma and Hyprland sessions.
{ ... }:
{
  nixos.sway =
    { pkgs, ... }:

    {
      # ---- Sway Compositor -----------------------------------------------------
      programs.sway = {
        enable = true;
        wrapperFeatures.gtk = true;
        extraPackages = with pkgs; [
          xwayland-satellite
        ];
      };

    }
  ;
}
