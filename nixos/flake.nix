{
  description = "Acer laptop NixOS 26.05 with Mango and Noctalia v5";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Keep the base system on the supported 26.05 channel while tracking the
    # newer Codex CLI independently. This avoids a broad system upgrade just
    # to receive Codex fixes.
    codex-nixpkgs.url = "github:NixOS/nixpkgs/master";
    mango.url = "github:mangowm/mango";
    noctalia.url = "github:noctalia-dev/noctalia/cachix";
    lotus.url = "github:LotusInputMethod/fcitx5-lotus";
    niri.url = "github:epireyn/niri-flake"; # NEW - Phase 5
    noctalia-greeter = {
      url = "github:noctalia-dev/noctalia-greeter";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    claude-code-nix.url = "github:sadjow/claude-code-nix";
    # Match the newer AGY and OpenCode builds already installed in the user
    # profile while moving them into the NixOS system profile.
    llm-agents.url = "github:numtide/llm-agents.nix/a621acfa43a25731694a8ef64fcbd5a00241e085";
    # Hermes CLI and Telegram gateway, pinned to the current upstream release.
    hermes-agent.url = "tarball+https://codeload.github.com/NousResearch/hermes-agent/tar.gz/refs/tags/v2026.9.24";
  };

  outputs =
    inputs@{ nixpkgs, ... }:
    let
      lib = nixpkgs.lib;
      hostRoot = ./hosts;
      hostEntries = builtins.readDir hostRoot;

      # A host becomes a flake configuration when its directory contains both
      # host.nix (small metadata) and hardware-configuration.nix (generated on
      # that physical machine). Templates and documentation are ignored.
      hostKeys = builtins.attrNames (
        lib.filterAttrs (
          name: type:
          type == "directory"
          && builtins.pathExists (hostRoot + "/${name}/host.nix")
          && builtins.pathExists (hostRoot + "/${name}/hardware-configuration.nix")
        ) hostEntries
      );

      mkHost =
        hostKey:
        let
          hostPath = hostRoot + "/${hostKey}";
          host = import (hostPath + "/host.nix");
          codexPackage = inputs.codex-nixpkgs.legacyPackages.${host.system}.codex;
          hostModule = hostPath + "/default.nix";
          extraModules = host.extraModules or [ ];
        in
        lib.nameValuePair hostKey (
          lib.nixosSystem {
            system = host.system;
            specialArgs = { inherit inputs host; };
            modules = [
              (hostPath + "/hardware-configuration.nix")
              hostModule
              inputs.home-manager.nixosModules.home-manager
              ./home-manager.nix
              ({ ... }: {
                # Codex is intentionally sourced from the dedicated pinned
                # input above instead of upgrading all NixOS packages.
                nixpkgs.overlays = [
                  (_final: _prev: { codex = codexPackage; })
                ];
              })
              ./configuration.nix
              ({ ... }: {
                networking.hostName = host.hostName;
              })
            ]
            ++ extraModules;
          }
        );
    in
    {
      # Keep the directory-based target for installation/backup tooling and
      # expose hostname aliases for native nixos-rebuild without --flake.
      nixosConfigurations =
        let
          configurations = builtins.listToAttrs (map mkHost hostKeys);
          hostnameAliases = builtins.listToAttrs (
            map (
              key: lib.nameValuePair (import (hostRoot + "/${key}/host.nix")).hostName configurations.${key}
            ) hostKeys
          );
        in
        configurations // hostnameAliases;
    };

  nixConfig = {
    extra-substituters = [
      "https://noctalia.cachix.org"
      "https://cache.numtide.com"
    ];
    extra-trusted-public-keys = [
      "noctalia.cachix.org-1:pCOR47nnMEo5thcxNDtzWpOxNFQsBRglJzxWPp3dkU4="
      "niks3.numtide.com-1:DTx8wZduET09hRmMtKdQDxNNthLQETkc/yaX7M4qK0g="
    ];
  };
}
