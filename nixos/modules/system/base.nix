{ inputs, ... }:
{
  nixos.base =
    { lib, ... }:
    {
      nix.settings = {
        max-jobs = 2;
        cores = 4;
        experimental-features = [
          "nix-command"
          "flakes"
        ];
        trusted-users = [
          "root"
          "@wheel"
        ];
        extra-substituters = [
          "https://noctalia.cachix.org"
          "https://umbriel.cachix.org"
          "https://cache.numtide.com"
          "https://niri-epireyn.cachix.org"
          "https://nix-community.cachix.org"
        ];
        extra-trusted-public-keys = [
          "noctalia.cachix.org-1:pCOR47nnMEo5thcxNDtzWpOxNFQsBRglJzxWPp3dkU4="
          "umbriel.cachix.org-1:JfNq/2yg2S6D6z4Z2dVSZrZlDPQTKtexB6GAVLD98nw="
          "niks3.numtide.com-1:DTx8wZduET09hRmMtKdQDxNNthLQETkc/yaX7M4qK0g="
          "niri-epireyn.cachix.org-1:tlVyFN7CtsDT+ZcLPS+ekFWeT1X6X4OqvWqbBMyIzFA="
          "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="
        ];
      };
      nix.registry.nixpkgs.flake = inputs.nixpkgs;
      nix.optimise.automatic = true;
      nix.gc = {
        automatic = true;
        dates = "weekly";
        options = "--delete-older-than 14d";
      };
      services.journald.extraConfig = ''
        SystemMaxUse=200M
        RuntimeMaxUse=64M
      '';
      nixpkgs.config.allowUnfree = true;
      # ~/.local/bin (slogout and the other personal commands) on PATH in every session,
      # including sessions whose terminals do not source Home Manager's session variables.
      environment.localBinInPath = true;

      time.timeZone = "Asia/Ho_Chi_Minh";
      i18n.defaultLocale = "en_US.UTF-8";
      console.keyMap = "us";

      users.users.aesc = {
        isNormalUser = true;
        uid = 1000;
        description = "Aesc";
        extraGroups = lib.mkBefore [
          "wheel"
          "networkmanager"
          "video"
          "render"
          "audio"
          "input"
        ];
      };
      security.sudo.wheelNeedsPassword = false;

      system.stateVersion = "26.05";
    }
  ;
}
