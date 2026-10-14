{ pkgs, ... }:
{
  home.packages = with pkgs; [
    (chromium.override { commandLineArgs = [ "--password-store=basic" ]; })
  ];
}
