{ ... }:
{
  homeManager.browsers =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        (chromium-latest.override { commandLineArgs = [ "--password-store=basic" ]; })
      ];
    }
  ;
}
