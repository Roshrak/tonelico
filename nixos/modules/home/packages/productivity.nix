{ ... }:
{
  homeManager.productivity =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        pdfarranger
        obsidian
        libreoffice
      ];
    }
  ;
}
