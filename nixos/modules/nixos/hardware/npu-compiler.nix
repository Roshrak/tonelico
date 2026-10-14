{ pkgs, ... }:
let
  # Intel NPU compiler from the same release as intel-npu-driver (1.28.0).
  # nixpkgs does not package it, and the driver loads it at model compile time.
  npuCompiler = pkgs.stdenv.mkDerivation {
    pname = "intel-npu-driver-compiler";
    version = "1.28.0";
    src = pkgs.fetchurl {
      url = "https://github.com/intel/linux-npu-driver/releases/download/v1.28.0/linux-npu-driver-v1.28.0.20251218-20347000698-ubuntu2404.tar.gz";
      sha256 = "1hh3ip03fqkjpqgn6gck0sigwf66yqikkml56w59r1ziswks5k09";
    };
    nativeBuildInputs = [ pkgs.binutils pkgs.autoPatchelfHook ];
    buildInputs = [ pkgs.onetbb pkgs.zlib pkgs.zstd pkgs.stdenv.cc.cc.lib ];
    unpackPhase = ''
      tar -xzf "$src"
      ar x intel-driver-compiler-npu_*_amd64.deb
      tar -xf data.tar.*
    '';
    installPhase = ''
      mkdir -p "$out/lib"
      cp usr/lib/x86_64-linux-gnu/libnpu_driver_compiler.so "$out/lib/"
    '';
  };
in
{
  # Merged into the graphics driver directory the system loads from.
  hardware.graphics.extraPackages = [ npuCompiler ];
}
