{ ... }:
{
  nixos.audio =
    { ... }:
    {
      # Audio.
      security.rtkit.enable = true;
      services.pipewire = {
        enable = true;
        alsa.enable = true;
        alsa.support32Bit = true;
        pulse.enable = true;
        wireplumber.enable = true;

        # High-resolution bit-perfect clock switching (44.1kHz - 96kHz),
        # low-latency 512 quantum (~10.6ms), and audiophile sinc resampler (quality 10).
        extraConfig.pipewire."92-high-quality" = {
          "context.properties" = {
            "default.clock.rate" = 48000;
            "default.clock.allowed-rates" = [ 44100 48000 88200 96000 ];
            "default.clock.quantum" = 512;
            "default.clock.min-quantum" = 64;
            "default.clock.max-quantum" = 2048;
          };
          "stream.properties" = {
            "resample.quality" = 10;
          };
        };
        extraConfig.pipewire-pulse."92-high-quality" = {
          "stream.properties" = {
            "resample.quality" = 10;
          };
        };
        extraConfig.client."92-high-quality" = {
          "stream.properties" = {
            "resample.quality" = 10;
          };
        };

        # Bluetooth HD codecs (LDAC HQ, aptX HD, AAC, SBC-XQ) & disable broken BLE MIDI spam.
        wireplumber.extraConfig."10-bluez-hd-audio" = {
          "monitor.bluez.properties" = {
            "bluez5.enable-sbc-xq" = true;
            "bluez5.enable-msbc" = true;
            "bluez5.enable-hw-volume" = true;
            "bluez5.enable-midi" = false;
            "bluez5.a2dp.ldac.quality" = "hq";
            "bluez5.codecs" = [ "ldac" "aptx_hd" "aptx" "aac" "sbc_xq" "sbc" ];
          };
        };
      };
    }
  ;
}
