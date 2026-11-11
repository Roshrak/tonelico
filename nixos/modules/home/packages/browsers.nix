{ ... }:
{
  homeManager.browsers =
    { ... }:
    {
      programs.librewolf = {
        enable = true;
        policies = {
          DisableTelemetry = true;
          DisableFirefoxStudies = true;
          DisablePocket = true;
          DisableFirefoxAccounts = false;
          DisableFeedbackCommands = true;
          DisableFormHistory = true;
          DontCheckDefaultBrowser = true;
          HardwareAcceleration = true;
          HttpsOnlyMode = "force_enabled";
          PostQuantumKeyAgreementEnabled = true;

          DNSOverHTTPS = {
            Enabled = true;
            ProviderURL = "https://security.cloudflare-dns.com/dns-query";
            Locked = true;
            Fallback = true;
            ExcludedDomains = [
              "localhost"
              "local"
              "lan"
            ];
          };

          EnableTrackingProtection = {
            Value = true;
            Locked = true;
            Cryptomining = true;
            Fingerprinting = true;
            EmailTracking = true;
            Category = "strict";
          };

          PopupBlocking = {
            Default = true;
            Locked = true;
          };

          Permissions = {
            Location = {
              BlockNewRequests = true;
              Locked = false;
            };
            Notifications = {
              BlockNewRequests = true;
              Locked = false;
            };
            VirtualReality = {
              BlockNewRequests = true;
              Locked = true;
            };
          };

          FirefoxHome = {
            Search = true;
            TopSites = false;
            SponsoredTopSites = false;
            Highlights = false;
            Pocket = false;
            SponsoredPocket = false;
            Snippets = false;
            Locked = true;
          };

          FirefoxSuggest = {
            WebSuggestions = false;
            SponsoredSuggestions = false;
            ImproveSuggest = false;
            Locked = true;
          };

          UserMessaging = {
            ExtensionRecommendations = false;
            FeatureRecommendations = false;
            UrlbarInterventions = false;
            SkipOnboarding = true;
            MoreFromMozilla = false;
            FirefoxLabs = false;
            Locked = true;
          };

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
            # Persistent logins & cookies across restarts while closing tabs on exit
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
            "browser.startup.page" = { Value = 1; Status = "locked"; };
            "browser.sessionstore.resume_from_crash" = { Value = false; Status = "locked"; };
            "browser.sessionstore.max_resumed_crashes" = { Value = 0; Status = "locked"; };
            "browser.toolbars.bookmarks.visibility" = { Value = "always"; Status = "default"; };

            # Strict content blocking, Total Cookie Protection (dFPI), & bounce tracking protection
            "browser.contentblocking.category" = { Value = "strict"; Status = "locked"; };
            "network.cookie.cookieBehavior" = { Value = 5; Status = "locked"; };
            "privacy.trackingprotection.enabled" = { Value = true; Status = "locked"; };
            "privacy.trackingprotection.pbmode.enabled" = { Value = true; Status = "locked"; };
            "privacy.trackingprotection.socialtracking.enabled" = { Value = true; Status = "locked"; };
            "privacy.trackingprotection.emailtracking.enabled" = { Value = true; Status = "locked"; };
            "privacy.trackingprotection.emailtracking.pbmode.enabled" = { Value = true; Status = "locked"; };
            "privacy.trackingprotection.cryptomining.enabled" = { Value = true; Status = "locked"; };
            "privacy.trackingprotection.fingerprinting.enabled" = { Value = true; Status = "locked"; };
            "privacy.bounceTrackingProtection.mode" = { Value = 1; Status = "locked"; };
            "privacy.query_stripping.enabled" = { Value = true; Status = "locked"; };
            "privacy.query_stripping.enabled.pbmode" = { Value = true; Status = "locked"; };
            "privacy.globalprivacycontrol.enabled" = { Value = true; Status = "locked"; };

            # Fingerprinting protection without breaking dark mode, local +07:00 timezone, or high refresh rate
            "privacy.resistFingerprinting" = { Value = false; Status = "locked"; };
            "privacy.fingerprintingProtection" = { Value = true; Status = "locked"; };
            "privacy.fingerprintingProtection.overrides" = { Value = "+AllTargets,-CSSPrefersColorScheme,-JSDateTimeUTC,-FrameRate"; Status = "locked"; };
            "webgl.disabled" = { Value = false; Status = "locked"; };

            # Process sandboxing, Fission site isolation, & HTTPS-Only hardening
            "fission.autostart" = { Value = true; Status = "locked"; };
            "security.sandbox.content.level" = { Value = 4; Status = "locked"; };
            "dom.security.https_only_mode" = { Value = true; Status = "locked"; };
            "dom.security.https_only_mode_ever_enabled" = { Value = true; Status = "locked"; };
            "dom.security.https_only_mode_pbm" = { Value = true; Status = "locked"; };
            "dom.security.https_only_mode_send_http_background_request" = { Value = false; Status = "locked"; };

            # TLS, post-quantum cryptography, CRLite revocation, & anti-spoofing
            "security.tls.version.min" = { Value = 3; Status = "locked"; };
            "security.tls.version.enable-deprecated" = { Value = false; Status = "locked"; };
            "security.tls.enable_0rtt_data" = { Value = false; Status = "locked"; };
            "network.http.http3.enable_0rtt" = { Value = false; Status = "locked"; };
            "security.tls.enable_kyber" = { Value = true; Status = "locked"; };
            "security.tls.enable_mlkem1024" = { Value = true; Status = "locked"; };
            "security.tls.enable_mldsa" = { Value = true; Status = "locked"; };
            "security.ssl.require_safe_negotiation" = { Value = true; Status = "locked"; };
            "security.ssl.treat_unsafe_negotiation_as_broken" = { Value = true; Status = "locked"; };
            "security.cert_pinning.enforcement_level" = { Value = 2; Status = "locked"; };
            "security.pki.crlite_mode" = { Value = 2; Status = "locked"; };
            "security.remote_settings.crlite_filters.enabled" = { Value = true; Status = "locked"; };
            "network.IDN_show_punycode" = { Value = true; Status = "locked"; };

            # Encrypted DNS (DoH with system fallback), WebRTC IP leak protection, & zero speculative connections
            "network.trr.mode" = { Value = 2; Status = "locked"; };
            "network.trr.uri" = { Value = "https://security.cloudflare-dns.com/dns-query"; Status = "locked"; };
            "network.trr.custom_uri" = { Value = "https://security.cloudflare-dns.com/dns-query"; Status = "locked"; };
            "media.peerconnection.ice.default_address_only" = { Value = true; Status = "locked"; };
            "media.peerconnection.ice.no_host" = { Value = true; Status = "locked"; };
            "media.peerconnection.ice.proxy_only_if_behind_proxy" = { Value = true; Status = "locked"; };
            "network.http.referer.XOriginTrimmingPolicy" = { Value = 2; Status = "locked"; };
            "network.http.referer.disallowCrossSiteRelaxingDefault.top_navigation" = { Value = true; Status = "locked"; };
            "network.prefetch-next" = { Value = false; Status = "locked"; };
            "network.dns.disablePrefetch" = { Value = true; Status = "locked"; };
            "network.dns.disablePrefetchFromHTTPS" = { Value = true; Status = "locked"; };
            "network.predictor.enabled" = { Value = false; Status = "locked"; };
            "network.predictor.enable-prefetch" = { Value = false; Status = "locked"; };
            "network.http.speculative-parallel-limit" = { Value = 0; Status = "locked"; };
            "browser.places.speculativeConnect.enabled" = { Value = false; Status = "locked"; };
            "browser.urlbar.speculativeConnect.enabled" = { Value = false; Status = "locked"; };
            "beacon.enabled" = { Value = false; Status = "locked"; };
            "browser.send_pings" = { Value = false; Status = "locked"; };
            "security.csp.reporting.enabled" = { Value = false; Status = "locked"; };

            # Attack surface reduction & AI/ML bloat removal
            "pdfjs.enableScripting" = { Value = false; Status = "locked"; };
            "dom.webserial.enabled" = { Value = false; Status = "locked"; };
            "dom.disable_window_move_resize" = { Value = true; Status = "locked"; };
            "dom.popup_allowed_events" = { Value = "click dblclick mousedown pointerdown"; Status = "locked"; };
            "browser.ml.enable" = { Value = false; Status = "locked"; };
            "browser.ml.chat.enabled" = { Value = false; Status = "locked"; };
            "browser.ml.chat.menu" = { Value = false; Status = "locked"; };
            "browser.tabs.groups.smart.enabled" = { Value = false; Status = "locked"; };
            "browser.preferences.aiControls" = { Value = false; Status = "locked"; };
            "browser.ai.control.default" = { Value = "blocked"; Status = "locked"; };

            # Wayland hardware acceleration, Multi-Account Containers, dark theme, & memory cache
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
            "general.smoothScroll" = { Value = true; Status = "default"; };
            "browser.tabs.unloadOnLowMemory" = { Value = true; Status = "default"; };
            "browser.cache.disk.enable" = { Value = false; Status = "default"; };
            "browser.cache.memory.enable" = { Value = true; Status = "default"; };
            "browser.cache.memory.capacity" = { Value = 131072; Status = "default"; };
            "browser.shell.checkDefaultBrowser" = { Value = false; Status = "locked"; };
            "widget.use-xdg-desktop-portal.mime-handler" = { Value = 0; Status = "default"; };
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
              private_browsing = true;
              default_area = "navbar";
            };
            "{7be2ba16-0f1e-4d93-9ebc-5164397477a9}" = {
              installation_mode = "blocked";
            };
            "@testpilot-containers" = {
              install_url = "https://addons.mozilla.org/firefox/downloads/latest/multi-account-containers/latest.xpi";
              installation_mode = "force_installed";
              private_browsing = true;
              default_area = "navbar";
            };
          };

          "3rdparty" = {
            Extensions = {
              "uBlock0@raymondhill.net" = {
                adminSettings = {
                  userSettings = {
                    autoUpdate = true;
                    cnameUncloakEnabled = true;
                    contextMenuEnabled = true;
                    hyperlinkAuditingDisabled = true;
                    ignoreGenericCosmeticFilters = false;
                    parseAllABPHideFilters = true;
                    prefetchingDisabled = true;
                    webrtcIPAddressHidden = true;
                  };
                };
                toOverwrite = {
                  filterLists = [
                    "user-filters"
                    "ublock-filters"
                    "ublock-badware"
                    "ublock-privacy"
                    "ublock-quick-fixes"
                    "ublock-unbreak"
                    "easylist"
                    "adguard-generic"
                    "adguard-mobile"
                    "easyprivacy"
                    "adguard-spyware-url"
                    "block-lan"
                    "urlhaus-1"
                    "curben-phishing"
                    "plowe-0"
                    "dpollock-0"
                    "adguard-cookies"
                    "ublock-cookies-adguard"
                    "fanboy-cookiemonster"
                    "ublock-cookies-easylist"
                    "adguard-popup-overlays"
                    "adguard-mobile-app-banners"
                    "adguard-other-annoyances"
                    "adguard-widgets"
                    "easylist-annoyances"
                    "easylist-chat"
                    "fanboy-ai-suggestions"
                    "easylist-newsletters"
                    "easylist-notifications"
                    "ublock-annoyances"
                    "VIE-1"
                  ];
                };
              };
            };
          };
        };
      };
    }
  ;
}
