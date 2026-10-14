{ ... }:
{
  environment.sessionVariables = {
    NIXOS_OZONE_WL = "1";
    MOZ_ENABLE_WAYLAND = "1";
    TERMINAL = "kitty";
    BROWSER = "chromium";
    XCURSOR_THEME = "Bibata-Modern-Ice";
    XCURSOR_SIZE = "24";
    LV2_PATH = "/run/current-system/sw/lib/lv2";
  };
}
