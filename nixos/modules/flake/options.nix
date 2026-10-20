# Storage for lower-level modules. Every feature file defines
# nixos.<feature> or homeManager.<feature>; aggregates and hosts select them.
# Definitions with the same name merge, because deferredModule merges.
{ lib, ... }:
let
  moduleSet = lib.types.lazyAttrsOf lib.types.deferredModule;
in
{
  options = {
    nixos = lib.mkOption {
      type = moduleSet;
      default = { };
      description = "Named NixOS modules, one per feature.";
    };
    homeManager = lib.mkOption {
      type = moduleSet;
      default = { };
      description = "Named Home Manager modules, one per feature.";
    };
  };
}
