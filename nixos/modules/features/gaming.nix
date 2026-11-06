{ ... }:
{
  nixos.gaming =
    { pkgs, ... }:
    {
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
            end = "${pkgs.power-profiles-daemon}/bin/powerprofilesctl set balanced || true";
          };
        };
      };

      systemd.tmpfiles.rules = [
        "w /sys/class/drm/card1/gt_min_freq_mhz - - - - 800"
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
      };
    }
  ;
}
