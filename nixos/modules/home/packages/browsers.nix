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

      programs.librewolf = {
        enable = true;
        policies = {
          DisableTelemetry = true;
          DisableFirefoxStudies = true;
          DisablePocket = true;
          DisableFirefoxAccounts = false;
          DontCheckDefaultBrowser = true;
          HardwareAcceleration = true;
          SanitizeOnShutdown = {
            Cache = false;
            Cookies = false;
            Downloads = false;
            FormData = false;
            History = false;
            OfflineApps = false;
            Sessions = false;
            SiteSettings = false;
            Locked = true;
          };
          Preferences = {
            "privacy.sanitize.sanitizeOnShutdown" = { Value = false; Status = "locked"; };
            "privacy.clearOnShutdown.cookies" = { Value = false; Status = "locked"; };
            "privacy.clearOnShutdown.offlineApps" = { Value = false; Status = "locked"; };
            "privacy.clearOnShutdown.sessions" = { Value = false; Status = "locked"; };
            "privacy.clearOnShutdown.history" = { Value = false; Status = "locked"; };
            "privacy.clearOnShutdown.cache" = { Value = false; Status = "locked"; };
            "privacy.clearOnShutdown_v2.cookiesAndStorage" = { Value = false; Status = "locked"; };
            "privacy.clearOnShutdown_v2.historyFormDataAndDownloads" = { Value = false; Status = "locked"; };
            "privacy.clearOnShutdown_v2.cache" = { Value = false; Status = "locked"; };
            "network.cookie.lifetimePolicy" = { Value = 0; Status = "locked"; };
            "browser.startup.page" = { Value = 3; Status = "default"; };
            "browser.toolbars.bookmarks.visibility" = { Value = "always"; Status = "default"; };
            "privacy.resistFingerprinting" = { Value = false; Status = "locked"; };
            "privacy.fingerprintingProtection" = { Value = true; Status = "locked"; };
            "privacy.fingerprintingProtection.overrides" = { Value = "+AllTargets,-CSSPrefersColorScheme,-JSDateTimeUTC,-FrameRate"; Status = "locked"; };
            "webgl.disabled" = { Value = false; Status = "locked"; };
            "gfx.webrender.all" = { Value = true; Status = "locked"; };
            "media.ffmpeg.vaapi.enabled" = { Value = true; Status = "locked"; };
            "media.hardware-video-decoding.force-enabled" = { Value = true; Status = "locked"; };
            "widget.dmabuf.force-enabled" = { Value = true; Status = "locked"; };
            "privacy.userContext.enabled" = { Value = true; Status = "locked"; };
            "privacy.userContext.ui.enabled" = { Value = true; Status = "locked"; };
            "ui.systemUsesDarkTheme" = { Value = 1; Status = "default"; };
            "layout.css.prefers-color-scheme.content-override" = { Value = 0; Status = "default"; };
            "browser.search.suggest.enabled" = { Value = true; Status = "default"; };
            "browser.urlbar.suggest.searches" = { Value = true; Status = "default"; };
          };
          SearchEngines = {
            Default = "Google";
            PreventInstalls = false;
            Add = [
              {
                Name = "Google";
                URLTemplate = "https://www.google.com/search?q={searchTerms}";
                Method = "GET";
                IconURL = "https://www.google.com/favicon.ico";
                Alias = "@g";
                Description = "Google Search";
                SuggestURLTemplate = "https://www.google.com/complete/search?client=firefox&q={searchTerms}";
              }
            ];
          };
          ManagedBookmarks = [
            { toplevel_name = "Gmail Accounts"; }
            { name = "0: trong2004.com"; url = "https://mail.google.com/mail/u/0/#inbox"; }
            { name = "1: eduardosachafolletto"; url = "https://mail.google.com/mail/u/1/#inbox"; }
            { name = "2: tronghoang060204"; url = "https://mail.google.com/mail/u/2/#inbox"; }
            { name = "3: roshrak0602"; url = "https://mail.google.com/mail/u/3/#inbox"; }
            { name = "4: trong123.com.com"; url = "https://mail.google.com/mail/u/4/#inbox"; }
            { name = "5: trong20041.com"; url = "https://mail.google.com/mail/u/5/#inbox"; }
            { name = "6: iamroshrak"; url = "https://mail.google.com/mail/u/6/#inbox"; }
            { name = "7: hnguyenle388"; url = "https://mail.google.com/mail/u/7/#inbox"; }
            { name = "8: welt4nderson"; url = "https://mail.google.com/mail/u/8/#inbox"; }
            { name = "9: leoanhoanh77"; url = "https://mail.google.com/mail/u/9/#inbox"; }
          ];
          ExtensionSettings = {
            "uBlock0@raymondhill.net" = {
              install_url = "https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi";
              installation_mode = "force_installed";
              default_area = "navbar";
            };
            "{7be2ba16-0f1e-4d93-9ebc-5164397477a9}" = {
              installation_mode = "blocked";
            };
            "@testpilot-containers" = {
              install_url = "https://addons.mozilla.org/firefox/downloads/latest/multi-account-containers/latest.xpi";
              installation_mode = "force_installed";
              default_area = "navbar";
            };
          };
        };
        settings = {
          # Keep Gmail / Google sessions & cookies persistent across browser restarts.
          "privacy.sanitize.sanitizeOnShutdown" = false;
          "privacy.clearOnShutdown.cookies" = false;
          "privacy.clearOnShutdown.offlineApps" = false;
          "privacy.clearOnShutdown.sessions" = false;
          "privacy.clearOnShutdown.history" = false;
          "privacy.clearOnShutdown.Cache" = false;
          "privacy.clearOnShutdown_v2.cookiesAndStorage" = false;
          "privacy.clearOnShutdown_v2.historyFormDataAndDownloads" = false;
          "privacy.clearOnShutdown_v2.cache" = false;
          "network.cookie.lifetimePolicy" = 0;
          "browser.startup.page" = 3;

          # Use modern Fingerprinting Protection (FPP) instead of legacy RFP so dark mode,
          # local +07:00 timezone, high-refresh-rate Wayland, and Google/Gmail work seamlessly.
          "privacy.resistFingerprinting" = false;
          "privacy.fingerprintingProtection" = true;
          "privacy.fingerprintingProtection.overrides" = "+AllTargets,-CSSPrefersColorScheme,-JSDateTimeUTC,-FrameRate";
          "webgl.disabled" = false;

          # Wayland hardware acceleration, VA-API video decoding & smooth performance.
          "gfx.webrender.all" = true;
          "media.ffmpeg.vaapi.enabled" = true;
          "media.hardware-video-decoding.force-enabled" = true;
          "widget.dmabuf.force-enabled" = true;
          "general.smoothScroll" = true;

          # Low-RAM tuning & fast memory cache.
          "browser.tabs.unloadOnLowMemory" = true;
          "browser.cache.disk.enable" = false;
          "browser.cache.memory.enable" = true;
          "browser.cache.memory.capacity" = 131072;

          # Enable Multi-Account Containers for extra Gmail accounts.
          "privacy.userContext.enabled" = true;
          "privacy.userContext.ui.enabled" = true;

          # Dark theme preference.
          "ui.systemUsesDarkTheme" = 1;
          "layout.css.prefers-color-scheme.content-override" = 0;
        };
      };
    }
  ;
}
