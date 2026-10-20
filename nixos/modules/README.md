# Module layout (dendritic)

Every `.nix` file under `modules/` is a flake-parts module, imported
automatically by `import-tree`. Files starting with `_` are ignored.

- `nixos.<feature>` and `homeManager.<feature>` hold lower-level modules.
  A file's path names its feature, and one file may define both classes.
- `aggregates/` groups features into sets: `nixos.system` (applied to every
  host), `nixos.desktop` (all sessions) and `homeManager.user` (the user's
  Home Manager config).
- `flake/` declares the option storage, systems and host discovery.
- `system/home-manager-integration.nix` connects Home Manager to the primary user.

Hosts live in `hosts/<name>/` (outside `modules/`). They select shared
features by name in `host.nix`: `features = [ "virtualization" ];`.

Add a feature: create a file, define `nixos.<name>` or `homeManager.<name>`,
and add `<name>` to the matching aggregate, or to a host's `features`.
Verify with the closure check (see `hosts/README.md`).
