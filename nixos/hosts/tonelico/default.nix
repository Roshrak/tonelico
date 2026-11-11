{ config, lib, pkgs, ... }:

let
  # Build against this host's selected kernel, keeping the previously verified
  # upstream revision rather than changing package inputs during restoration.
  acerWmiBattery = config.boot.kernelPackages.callPackage (
    { lib, stdenv, fetchFromGitHub, kernel }:
    stdenv.mkDerivation {
      pname = "acer-wmi-battery";
      version = "0.2.0";

      src = fetchFromGitHub {
        owner = "frederik-h";
        repo = "acer-wmi-battery";
        rev = "9f90d75cc9237aeed7964622d10dbdf4d2c7b518";
        hash = "sha256-CyKRpE3cnhEIFHc4Hal2PQUW7cd5k8+55S4QdSqGvNI=";
      };

      nativeBuildInputs = kernel.moduleBuildDependencies;
      hardeningDisable = [ "pic" ];

      buildPhase = ''
        runHook preBuild
        make -C ${kernel.dev}/lib/modules/${kernel.modDirVersion}/build M=$PWD modules
        runHook postBuild
      '';

      installPhase = ''
        runHook preInstall
        install -Dm644 acer-wmi-battery.ko \
          -t "$out/lib/modules/${kernel.modDirVersion}/extra"
        runHook postInstall
      '';

      meta = {
        description = "Acer WMI battery health control kernel module";
        homepage = "https://github.com/frederik-h/acer-wmi-battery";
        license = lib.licenses.gpl2Only;
        platforms = lib.platforms.linux;
      };
    }
  ) { };
in

{
  imports = [ ./input-devices.nix ];

  # Hardware-adaptive kernel modules and low-latency driver options.
  # Device-specific units below check sysfs/DMI/CPU vendor before running, so
  # this host profile works on any future laptop or desktop without manual edits.
  boot.extraModulePackages = [ acerWmiBattery ];
  boot.extraModprobeConfig = ''
    options acer-wmi-battery enable_health_mode=1
    options snd_hda_intel power_save=0 power_save_controller=N
    options iwlwifi power_save=0
    options iwlmvm power_scheme=1
  '';
  systemd.services.acer-wmi-battery = {
    description = "Enable and verify Acer 80% battery charge limit";
    wantedBy = [ "multi-user.target" ];
    after = [ "systemd-modules-load.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      # Only Acer laptops with a battery have this firmware interface. Any other
      # machine skips the unit cleanly (exit 1 in ExecCondition is a skip).
      ExecCondition = pkgs.writeShellScript "acer-wmi-battery-only-on-acer" ''
        grep -qx 'Acer' /sys/class/dmi/id/sys_vendor && compgen -G '/sys/class/power_supply/BAT*' >/dev/null
      '';
      # Extra modules live outside kmod's default /lib/modules on NixOS.
      ExecStart = pkgs.writeShellScript "load-acer-wmi-battery" ''
        if [ -d "/run/current-system/kernel-modules/lib/modules/$(uname -r)" ]; then
          exec ${pkgs.kmod}/bin/modprobe --dirname /run/current-system/kernel-modules acer_wmi_battery enable_health_mode=1
        else
          exec ${pkgs.kmod}/bin/modprobe --dirname /run/booted-system/kernel-modules acer_wmi_battery enable_health_mode=1
        fi
      '';
      # Also reapply when the module is already loaded. Verify the driver's
      # firmware readback when present; skip gracefully on Acer models without it.
      ExecStartPost = pkgs.writeShellScript "verify-acer-battery-limit" ''
        set -eu
        control=/sys/bus/wmi/drivers/acer-wmi-battery/health_mode
        if [ ! -e "$control" ]; then
          printf 'Acer WMI battery health_mode interface not present on this model; skipping.\n'
          exit 0
        fi
        printf '1\n' > "$control"
        read -r enabled < "$control"
        if [ "$enabled" != 1 ]; then
          printf 'Acer 80%% charge limit was not accepted (health_mode=%s)\n' "$enabled" >&2
          exit 1
        fi
        printf 'Acer 80%% battery charge limit verified: health_mode=1\n'
      '';
    };
  };

  # CPU microcode updates and GPU/media runtimes.
  # Mesa + libva auto-select the active GPU driver (iHD on Intel, radeonsi on AMD, etc.).
  hardware.cpu.intel.updateMicrocode = lib.mkDefault config.hardware.enableRedistributableFirmware;
  hardware.cpu.amd.updateMicrocode = lib.mkDefault config.hardware.enableRedistributableFirmware;
  hardware.graphics.extraPackages = with pkgs; [
    intel-media-driver
    vpl-gpu-rt
    intel-compute-runtime
  ];
  services.thermald.enable = true;
  systemd.services.thermald.unitConfig.ConditionCPUVendor = "GenuineIntel";

  # Fix for PixArt PIXA3848 I2C Touchpad boot race condition (only runs on machines
  # that physically expose the PIXA3848 ACPI device).
  systemd.services.pixart-touchpad-fix = {
    description = "Fix PixArt PIXA3848 I2C Touchpad Initialization";
    wantedBy = [ "multi-user.target" ];
    after = [ "multi-user.target" ];
    unitConfig.ConditionPathExists = "/sys/bus/acpi/devices/PIXA3848:00";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = false;
      ExecStart = pkgs.writeShellScript "pixart-touchpad-fix" ''
        if [ -e /sys/bus/acpi/devices/PIXA3848:00 ] && ! grep -q "PIXA3848.*Touchpad" /proc/bus/input/devices; then
          echo "PIXA3848 touchpad not detected in input devices. Reloading i2c_hid_acpi..."
          ${pkgs.kmod}/bin/modprobe -r i2c_hid_acpi || true
          sleep 0.5
          ${pkgs.kmod}/bin/modprobe i2c_hid_acpi
        else
          echo "PIXA3848 touchpad is already initialized."
        fi
      '';
    };
  };

  # Ensure the touchpad is re-checked upon resuming from sleep/suspend on hardware with PIXA3848
  powerManagement.resumeCommands = ''
    if [ -e /sys/bus/acpi/devices/PIXA3848:00 ] && ! grep -q "PIXA3848.*Touchpad" /proc/bus/input/devices; then
      ${pkgs.kmod}/bin/modprobe -r i2c_hid_acpi || true
      sleep 0.5
      ${pkgs.kmod}/bin/modprobe i2c_hid_acpi
    fi
  '';
}
