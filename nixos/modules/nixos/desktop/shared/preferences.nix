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

  # Chromium policy: never nag about being the default browser.
  # Declarative (was a manual /etc/chromium/... copy) so reinstalls keep it.
  environment.etc."chromium/policies/managed/default-browser.json".text = ''
    {
      "DefaultBrowserSettingEnabled": false
    }
  '';
}
