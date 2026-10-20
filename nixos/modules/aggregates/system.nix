# NixOS features applied to every host, in the order they were imported before
# the dendritic migration. Order is kept so the built closure does not change.
{ config, ... }:
{
  nixos.system = {
    imports = map (name: config.nixos.${name}) [
      "base"
      "boot"
      "hardware"
      "networking"
      "audio"
      "services"
      "packages"
      "desktop"
      "gaming"
      "input-methods"
      "fonts"
      "docker"
      "access"
      "npu-compiler"
    ];
  };
}
