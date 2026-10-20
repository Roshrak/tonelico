{ ... }:
{
  homeManager.neovim =
    { ... }:
    {
      programs.neovim = {
        enable = true;
        initLua = builtins.readFile ../../../home/files/config/nvim/init.lua;
      };
      xdg.configFile."nvim/lua" = {
        source = ../../../home/files/config/nvim/lua;
        recursive = true;
      };
      xdg.configFile."nvim/stylua.toml".source = ../../../home/files/config/nvim/stylua.toml;
      # LazyVim lock/session/cache files remain writable and application-owned.
    }
  ;
}
