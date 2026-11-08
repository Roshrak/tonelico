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
        "--process-per-site"
        "--renderer-process-limit=6"
        "--disk-cache-size=104857600"
        "--media-cache-size=52428800"
        "--disable-background-networking"
        "--disable-breakpad"
        "--disable-crash-reporter"
        "--disable-component-update"
        "--disable-domain-reliability"
        "--disable-sync"
        "--disable-pings"
        "--no-default-browser-check"
        "--no-first-run"
        "--no-service-autorun"
        "--disable-speech-api"
        "--fingerprinting-canvas-image-data-noise"
        "--fingerprinting-canvas-measuretext-noise"
        "--fingerprinting-client-rects-noise"
        "--extension-mime-request-handling=always-prompt-for-install"
        "--enable-features=VaapiVideoDecoder,VaapiIgnoreDriverChecks,HighEfficiencyModeAvailable,DestroyProfileOnBrowserClose,UnretainedPageCache"
        "--disable-features=OptimizationHints,OptimizationGuideModelDownloading,OptimizationTargetPrediction,OptimizationHintsFetching,MediaRouter,DialMediaRouteProvider,Translate,PrivacySandboxSettings4,AutofillServerCommunication,InterestFeedContentSuggestions,CertificateTransparencyComponentUpdater"
      ];
    in
    {
      home.packages = with pkgs; [
        (chromium-latest.override { commandLineArgs = chromiumFlags; })
      ];
    }
  ;
}
