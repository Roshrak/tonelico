{
  # The directory name is the flake attribute: /etc/nixos#tonelico.
  # The operating-system hostname is intentionally different.
  hostName = "tonelico-nix";
  system = "x86_64-linux";

  # The current desktop configuration contains intentional /home/aesc paths.
  primaryUser = "aesc";
  retainLocalRecovery = false; # Preserve this laptop's verified fallbacks.
  userUid = 1000;
  userGid = 100;

  # Host-local modules are paths. Shared features are named modules from
  # modules/. Neither is forced onto every future host.
  extraModules = [ ./keyboard.nix ];
  features = [ "virtualization" "tonelico-restore" ];
}
