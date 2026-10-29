# The user's Home Manager configuration: every home feature, then the shared
# base settings last, matching the import order used before the migration.
{ config, ... }:
{
  homeManager.user = {
    imports = map (name: config.homeManager.${name}) [
      "shell"
      "git"
      "kitty"
      "neovim"
      "fastfetch"
      "communication"
      "browsers"
      "productivity"
      "media"
      "gaming"
      "development"
      "utilities"
      "ai"
      "desktop-configuration"
      "agents"
      "scripts"
      "home-base"
    ];
  };
}
