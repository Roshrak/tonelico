# Host discovery. Each directory under hosts/ that holds host.nix and
# hardware-configuration.nix becomes nixosConfigurations.<directory>.
# Host metadata reaches NixOS modules as the `host` argument.
{ config, inputs, lib, ... }:
let
  hostRoot = ../../hosts;

  hostKeys = builtins.attrNames (
    lib.filterAttrs (
      name: type:
      type == "directory"
      && builtins.pathExists (hostRoot + "/${name}/host.nix")
      && builtins.pathExists (hostRoot + "/${name}/hardware-configuration.nix")
    ) (builtins.readDir hostRoot)
  );

  readHost = key: import (hostRoot + "/${key}/host.nix");

  mkHost =
    hostKey:
    let
      hostPath = hostRoot + "/${hostKey}";
      host = readHost hostKey;
      codexPackage = inputs.codex-nixpkgs.legacyPackages.${host.system}.codex;
      # Only the browser uses this; replacing pkgs.chromium would also rebuild Electron.
      chromiumPackage = inputs.chromium-nixpkgs.legacyPackages.${host.system}.chromium;
    in
    lib.nameValuePair hostKey (
      inputs.nixpkgs.lib.nixosSystem {
        system = host.system;
        modules = [
          (hostPath + "/hardware-configuration.nix")
          (hostPath + "/default.nix")
          inputs.home-manager.nixosModules.home-manager
          config.nixos.home-manager-integration
          {
            _module.args.host = host;
            # Codex is intentionally sourced from the dedicated pinned input
            # instead of upgrading all NixOS packages.
            nixpkgs.overlays = [ (_final: _prev: { codex = codexPackage; chromium-latest = chromiumPackage; }) ];
          }
          config.nixos.system
          { networking.hostName = host.hostName; }
        ]
        ++ (host.extraModules or [ ])
        ++ map (name: config.nixos.${name}) (host.features or [ ]);
      }
    );

  configurations = builtins.listToAttrs (map mkHost hostKeys);

  hostnameAliases = builtins.listToAttrs (
    map (key: lib.nameValuePair (readHost key).hostName configurations.${key}) hostKeys
  );
in
{
  # Directory-based names serve installation and backup tooling; hostname
  # aliases serve native nixos-rebuild without --flake.
  flake.nixosConfigurations = configurations // hostnameAliases;
}
