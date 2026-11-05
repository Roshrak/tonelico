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
        "dev.i915.perf_stream_paranoid" = 0;
        "kernel.sched_autogroup_enabled" = 1;
      };
    }
  ;
}
