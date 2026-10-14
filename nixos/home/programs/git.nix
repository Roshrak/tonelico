{ pkgs, ... }:
{
  programs.git = {
    enable = true;
    package = null; # Retain Git in NixOS for root and recovery operations.
    settings = {
      user = { name = "Roshrak"; email = "Roshrak@users.noreply.github.com"; };
      init.defaultBranch = "main";
      safe.directory = "/etc/nixos";
      credential."https://github.com".helper = "!${pkgs.gh}/bin/gh auth git-credential";
      credential."https://gist.github.com".helper = "!${pkgs.gh}/bin/gh auth git-credential";
    };
  };
}
