{ ... }:
{
  homeManager.development =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        codex
        gh
        gcc
        tree-sitter
        lazygit
      ];
    }
  ;
}
