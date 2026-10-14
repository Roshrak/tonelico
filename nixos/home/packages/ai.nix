{ pkgs, inputs, ... }:
{
  home.packages = with pkgs; [
    inputs.claude-code-nix.packages.${pkgs.stdenv.hostPlatform.system}.default
    inputs.llm-agents.packages.${pkgs.stdenv.hostPlatform.system}.antigravity-cli
    inputs.llm-agents.packages.${pkgs.stdenv.hostPlatform.system}.opencode
    inputs.hermes-agent.packages.${pkgs.stdenv.hostPlatform.system}.messaging
  ];
}
