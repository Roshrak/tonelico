{ inputs, ... }:
{
  nixos.mango =
    { ... }:
    {
      imports = [ inputs.mango.nixosModules.mango ];
      programs.mango.enable = true;
    }
  ;
}
