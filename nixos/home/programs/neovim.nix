{ ... }:
{
  programs.neovim = {
    enable = true;
    initLua = builtins.readFile ../files/config/nvim/init.lua;
  };
  xdg.configFile."nvim/lua" = {
    source = ../files/config/nvim/lua;
    recursive = true;
  };
  xdg.configFile."nvim/stylua.toml".source = ../files/config/nvim/stylua.toml;
  # LazyVim lock/session/cache files remain writable and application-owned.
}
