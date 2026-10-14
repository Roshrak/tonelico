{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    # Shared desktop controls, screenshots, and X11 bridge for Wayland.
    xwayland-satellite
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
    # User applications are declared in home/packages/.
    bibata-cursors
    xdg-user-dirs
    lsp-plugins
    calf
    zam-plugins
    mda_lv2
    glib
  ];
}
