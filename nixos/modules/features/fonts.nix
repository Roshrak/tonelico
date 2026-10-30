{ ... }:
{
  nixos.fonts =
    { pkgs, lib, ... }:
    {
      imports = [ ../../comic-mono.nix ];

      fonts.packages =
        with pkgs;
        lib.mkBefore [
          nerd-fonts.jetbrains-mono
          nerd-fonts.space-mono
          noto-fonts
          noto-fonts-cjk-sans
          noto-fonts-color-emoji
        ];
    }
  ;
}
