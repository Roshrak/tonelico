{
  description = "Acer laptop NixOS 26.05 with Mango and Noctalia v5";

  # Dendritic layout: every .nix file under modules/ is a flake-parts module
  # (auto-imported by import-tree). Hosts are discovered from hosts/<name>/.
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    import-tree.url = "github:vic/import-tree";
    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Keep the base system on the supported 26.05 channel while tracking the
    # newer Codex CLI independently. This avoids a broad system upgrade just
    # to receive Codex fixes.
    codex-nixpkgs.url = "github:NixOS/nixpkgs/master";
    # Chromium follows the current 26.05 branch on its own, so browser security
    # updates do not require moving the whole system to a newer nixpkgs.
    chromium-nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    mango.url = "github:mangowm/mango";
    noctalia.url = "github:noctalia-dev/noctalia/cachix";
    lotus.url = "github:LotusInputMethod/fcitx5-lotus";
    niri.url = "github:epireyn/niri-flake";
    noctalia-greeter = {
      url = "github:noctalia-dev/noctalia-greeter";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    claude-code-nix.url = "github:sadjow/claude-code-nix";
    # Match the newer AGY and OpenCode builds already installed in the user
    # profile while moving them into the NixOS system profile.
    llm-agents.url = "github:numtide/llm-agents.nix/e452052b9efb54fd59f8a06cbc09978fb542a3c2";
    # Hermes CLI and Telegram gateway, pinned to the current upstream release.
    hermes-agent.url = "tarball+https://codeload.github.com/NousResearch/hermes-agent/tar.gz/refs/tags/v2026.9.24";
  };

  outputs =
    inputs:
    inputs.flake-parts.lib.mkFlake { inherit inputs; } (inputs.import-tree ./modules);

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
