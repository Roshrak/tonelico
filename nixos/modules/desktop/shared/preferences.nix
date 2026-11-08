{ ... }:
{
  nixos.preferences =
    { ... }:
    {
      # Disable audible UI/error feedback for every desktop using the shared
      # GNOME settings schemas. Lock these keys so an application cannot silently
      # turn the empty-field/error bell back on.
      programs.dconf.profiles.user.databases = [
        {
          settings = {
            "org/gnome/desktop/sound" = {
              "event-sounds" = false;
              "input-feedback-sounds" = false;
            };
            "org/gnome/desktop/wm/preferences" = {
              "audible-bell" = false;
            };
          };
          locks = [
            "/org/gnome/desktop/sound/event-sounds"
            "/org/gnome/desktop/sound/input-feedback-sounds"
            "/org/gnome/desktop/wm/preferences/audible-bell"
          ];
        }
      ];

      # GTK's error bell is separate from its event-sound preferences. These
      # defaults cover GTK lock/password dialogs and file/application launchers.
      environment.etc."xdg/gtk-3.0/settings.ini".text = ''
        [Settings]
        gtk-error-bell=false
        gtk-enable-event-sounds=false
        gtk-enable-input-feedback-sounds=false
      '';
      environment.etc."xdg/gtk-4.0/settings.ini".text = ''
        [Settings]
        gtk-error-bell=false
        gtk-enable-event-sounds=false
        gtk-enable-input-feedback-sounds=false
      '';

      # KDE/Plasma has its own system-bell and accessibility-bell switches.
      environment.etc."xdg/kdeglobals".text = ''
        [General]
        UseSystemBell=false
      '';
      environment.etc."xdg/kaccessrc".text = ''
        [Bell]
        ArtsBell=false
        SystemBell=false
        VisibleBell=false
      '';

      # Chromium policy: clean privacy, zero AI/telemetry bloat, and Memory Saver without breaking sites.
      # Declarative (was a manual /etc/chromium/... copy) so reinstalls keep it.
      environment.etc."chromium/policies/managed/default-browser.json".text = ''
        {
          "DefaultBrowserSettingEnabled": false,
          "BackgroundModeEnabled": false,
          "HighEfficiencyModeEnabled": true,
          "HardwareAccelerationModeEnabled": true,
          "MetricsReportingEnabled": false,
          "UrlKeyedAnonymizedDataCollectionEnabled": false,
          "FeedbackSurveysEnabled": false,
          "ShoppingListEnabled": false,
          "PromotionsEnabled": false,
          "BuiltInAiAPIsEnabled": false,
          "GenAiDefaultSettings": 2,
          "HelpMeWriteSettings": 2,
          "TabCompareSettings": 2,
          "HistorySearchSettings": 2,
          "CreateThemesSettings": 2,
          "PrivacySandboxPromptEnabled": false,
          "PrivacySandboxAdMeasurementEnabled": false,
          "PrivacySandboxAdTopicsEnabled": false,
          "PrivacySandboxSiteEnabledAdsEnabled": false,
          "BlockThirdPartyCookies": true,
          "DnsOverHttpsMode": "automatic",
          "WebRtcIPHandling": "default_public_interface_only",
          "PaymentMethodQueryEnabled": false,
          "ExtensionSettings": {
            "ddkjiahejlhfcafbddmgiahcphecmpfh": {
              "installation_mode": "normal_installed",
              "update_url": "https://clients2.google.com/service/update2/crx",
              "toolbar_pin": "force_pinned"
            },
            "hdannnflhlmdablckfkjpleikpphncik": {
              "installation_mode": "normal_installed",
              "update_url": "https://clients2.google.com/service/update2/crx",
              "toolbar_pin": "force_pinned"
            }
          }
        }
      '';
    }
  ;
}
