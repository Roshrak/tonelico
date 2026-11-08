{ ... }:
{
  homeManager.browsers =
    { pkgs, ... }:
    let
      ublockOrigin = pkgs.fetchzip {
        url = "https://github.com/gorhill/uBlock/releases/download/1.75.4/uBlock0_1.75.4.chromium.zip";
        hash = "sha256-W1JDkCRE/D1N8VhmitNyP6I2JT2X/C9L0GLEn3HH+EE=";
      };
      chromiumFlags = [
        "--password-store=basic"
        "--ozone-platform=wayland"
        "--enable-gpu-rasterization"
        "--enable-zero-copy"
        "--process-per-site"
        "--renderer-process-limit=4"
        "--aggressive-cache-discard"
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
        "--reduced-referrer-granularity"
        "--disable-search-engine-collection"
        "--disable-beforeunload"
        "--enforce-webrtc-ip-permission-check"
        "--force-webrtc-ip-handling-policy=default_public_interface_only"
        "--fingerprinting-canvas-image-data-noise"
        "--fingerprinting-canvas-measuretext-noise"
        "--fingerprinting-client-rects-noise"
        "--extension-mime-request-handling=always-prompt-for-install"
        "--load-extension=${ublockOrigin}"
        "--enable-features=VaapiVideoDecoder,VaapiIgnoreDriverChecks,HighEfficiencyModeAvailable,DestroyProfileOnBrowserClose,UnretainedPageCache,ReducedSystemInfo,PartitionConnectionsByNetworkIsolationKey,SplitCacheByNetworkIsolationKey,EnableTabMuting"
        "--disable-features=OptimizationHints,OptimizationGuideModelDownloading,OptimizationTargetPrediction,OptimizationHintsFetching,MediaRouter,DialMediaRouteProvider,Translate,PrivacySandboxSettings4,AutofillServerCommunication,InterestFeedContentSuggestions,CertificateTransparencyComponentUpdater,BackForwardCache,Prerender2"
      ];
    in
    {
      home.packages = with pkgs; [
        (chromium-latest.override { commandLineArgs = chromiumFlags; })
      ];
    }
  ;
}
