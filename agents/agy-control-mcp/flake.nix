{
  description = "NixOS development environment for AGY Control MCP";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in {
      devShells = forAllSystems (system:
        let pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.mkShell {
            packages = [
              pkgs.nodejs_22
              pkgs.git
              pkgs.gcc
              pkgs.gnumake
              pkgs.pkg-config
              pkgs.python3
              pkgs.shellcheck
              pkgs.bubblewrap
            ];
            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc pkgs.zlib pkgs.openssl ];
          };
        });
    };
}
