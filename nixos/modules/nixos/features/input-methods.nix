{
  pkgs,
  inputs,
  lib,
  ...
}:
{
  imports = [ inputs.lotus.nixosModules.fcitx5-lotus ];

  # Vietnamese input with Fcitx5 + Unikey. XDG autostart above starts it in Mango.
  i18n.inputMethod = {
    enable = true;
    type = "fcitx5";
    fcitx5 = {
      waylandFrontend = true;
      addons =
        with pkgs;
        lib.mkBefore [
          qt6Packages.fcitx5-unikey
          fcitx5-gtk
        ];
    };
  };
  services.fcitx5-lotus = {
    enable = true;
    users = [ "aesc" ];
    package = inputs.lotus.packages.${pkgs.stdenv.hostPlatform.system}.fcitx5-lotus;
  };
}
