{ inputs, ... }:
{
  nixos.gaming =
    { pkgs, ... }:
    let
      system = pkgs.stdenv.hostPlatform.system;
      wrapAAGL = pkgs.callPackage "${inputs.aagl}/pkgs/wrapAAGL" { };
      honkers-railway-launcher = pkgs.callPackage "${inputs.aagl}/pkgs/honkers-railway-launcher" {
        inherit wrapAAGL;
        unwrapped = inputs.aagl.packages.${system}.the-honkers-railway-launcher-unwrapped;
      };
    in
    {
      imports = [ "${inputs.aagl}/module/hosts.nix" ];

      environment.systemPackages = [ honkers-railway-launcher ];
      networking.mihoyo-telemetry.block = true;

      programs.steam.enable = true;
      programs.gamemode = {
        enable = true;
        enableRenice = true;
        settings = {
          general = {
            renice = 10;
            ioprio = 0;
            inhibit_screensaver = 1;
            defaultgov = "powersave";
            desiredgov = "performance";
            igpu_desiredgov = "performance";
            softrealtime = "auto";
          };
          custom = {
            start = "${pkgs.power-profiles-daemon}/bin/powerprofilesctl set performance || true";
            end = "${pkgs.power-profiles-daemon}/bin/powerprofilesctl set performance || true";
          };
        };
      };

      systemd.tmpfiles.rules = [
        "w /sys/class/drm/card1/gt_min_freq_mhz - - - - 800"
        "w /sys/module/snd_hda_intel/parameters/power_save - - - - 0"
        "w /sys/module/snd_hda_intel/parameters/power_save_controller - - - - N"
        "w /sys/kernel/mm/transparent_hugepage/shmem_enabled - - - - advise"
        "w /sys/kernel/mm/transparent_hugepage/enabled - - - - madvise"
      ];

      boot.kernel.sysctl = {
        "vm.page-cluster" = 0;
        "vm.swappiness" = 15;
        "vm.vfs_cache_pressure" = 50;
        "vm.dirty_background_ratio" = 5;
        "vm.dirty_ratio" = 10;
        "vm.compaction_proactiveness" = 0;
        "vm.watermark_boost_factor" = 0;
        "vm.watermark_scale_factor" = 125;
        "dev.i915.perf_stream_paranoid" = 0;
        "kernel.sched_autogroup_enabled" = 1;
        "kernel.split_lock_mitigate" = 0;
        "net.core.default_qdisc" = "fq";
        "net.ipv4.tcp_congestion_control" = "bbr";
        "net.ipv4.tcp_fastopen" = 3;
        "net.core.rmem_max" = 16777216;
        "net.core.wmem_max" = 16777216;
        "net.core.rmem_default" = 1048576;
        "net.core.wmem_default" = 1048576;
        "net.ipv4.tcp_rmem" = "4096 1048576 16777216";
        "net.ipv4.tcp_wmem" = "4096 1048576 16777216";
        "net.ipv4.udp_rmem_min" = 16384;
        "net.ipv4.udp_wmem_min" = 16384;
        "net.core.netdev_max_backlog" = 16384;
        "net.core.somaxconn" = 8192;
        "net.ipv4.tcp_mtu_probing" = 1;
        "net.ipv4.tcp_slow_start_after_idle" = 0;
        "net.ipv4.tcp_notsent_lowat" = 131072;
        "net.ipv4.tcp_ecn" = 2;
      };
    }
  ;
}
