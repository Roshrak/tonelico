{ ... }:
{
  nixos.packages =
    { pkgs, ... }:
    {
      environment.systemPackages = with pkgs; [
        # Shared desktop controls, screenshots, and X11 bridge for Wayland.
        xwayland-satellite
        # Pinned during the GNOME/XFCE/X11 removal: still used by the Sunshine app
        # setup (xrandr --output HDMI-1 ...) and by shared thumbnail, icon and
        # GTK theme consumers in the remaining sessions.
        xrandr
        gst-thumbnailers
        glycin-thumbnailer
        desktop-file-utils
        tango-icon-theme
        gnome-themes-extra
        xdg-user-dirs-gtk
        pavucontrol
        playerctl
        brightnessctl
        wl-clipboard
        grim
        slurp
        wlr-randr
        wayland-utils
        libnotify

        # Driver verification
        mesa-demos
        vulkan-tools
        libva-utils

        # Everyday CLI tools
        git
        curl
        wget
        unzip
        zip
        python3
        nodejs
        jq
        pciutils
        usbutils
        smartmontools
        nvme-cli
        xdg-utils
        bubblewrap

        # Icons
        adwaita-icon-theme
        papirus-icon-theme

        # Shared greeter assets and the system LV2 plugin path stay system-owned.
        # User applications are declared in modules/home/packages/.
        bibata-cursors
        xdg-user-dirs
        lsp-plugins
        calf
        zam-plugins
        mda_lv2
        glib
      ];
    }
  ;
}
