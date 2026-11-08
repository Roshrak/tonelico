{ ... }:
{
  homeManager.browsers =
    { pkgs, ... }:
    let
      chromiumFlags = [
        "--password-store=basic"
        "--ozone-platform=wayland"
        "--enable-gpu-rasterization"
        "--enable-zero-copy"
        "--disable-breakpad"
        "--disable-crash-reporter"
        "--disable-domain-reliability"
        "--disable-pings"
        "--no-default-browser-check"
        "--no-first-run"
        "--enable-features=VaapiVideoDecoder,VaapiIgnoreDriverChecks,HighEfficiencyModeAvailable,CanvasOopRasterization"
        "--disable-features=OptimizationHints,OptimizationGuideModelDownloading,OptimizationTargetPrediction,OptimizationHintsFetching,MediaRouter,DialMediaRouteProvider,PrivacySandboxSettings4,AutofillServerCommunication,InterestFeedContentSuggestions"
      ];
    in
    {
      home.packages = with pkgs; [
        (chromium-latest.override { commandLineArgs = chromiumFlags; })
      ];
    }
  ;
}
