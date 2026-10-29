{ config, pkgs, ... }:

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

  # Restore this Acer's firmware-backed 80% cap on every boot. These controls
  # belong to this laptop, not the shared modules for other hardware.
  boot.extraModulePackages = [ acerWmiBattery ];
  boot.extraModprobeConfig = ''
    options acer-wmi-battery enable_health_mode=1
  '';
  systemd.services.acer-wmi-battery = {
    description = "Enable and verify Acer 80% battery charge limit";
    wantedBy = [ "multi-user.target" ];
    after = [ "systemd-modules-load.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      # Extra modules live outside kmod's default /lib/modules on NixOS.
      ExecStart = "${pkgs.kmod}/bin/modprobe --dirname /run/current-system/kernel-modules acer_wmi_battery enable_health_mode=1";
      # Also reapply when the module is already loaded. Verify the driver's
      # firmware readback; loading a module alone does not establish success.
      ExecStartPost = pkgs.writeShellScript "verify-acer-battery-limit" ''
        set -eu
        control=/sys/bus/wmi/drivers/acer-wmi-battery/health_mode
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

  # Acer Swift SFG16-72 / Intel Core Ultra 5 125U-specific tuning.
  # Keep vendor-specific settings here instead of in shared modules/system.
  hardware.cpu.intel.updateMicrocode = true;
  hardware.graphics.extraPackages = with pkgs; [
    intel-media-driver
    vpl-gpu-rt
    intel-compute-runtime
  ];
  services.thermald.enable = true;

  environment.sessionVariables.LIBVA_DRIVER_NAME = "iHD";

  # Fix for PixArt PIXA3848 I2C Touchpad boot race condition.
  # On cold boot, the touchpad power/controller takes a moment to stabilize,
  # causing the initial i2c_hid_acpi descriptor probe to fail with error -22
  # ("unexpected long global item"). Reloading i2c_hid_acpi if missing fixes it.
  systemd.services.pixart-touchpad-fix = {
    description = "Fix PixArt PIXA3848 I2C Touchpad Initialization";
    wantedBy = [ "multi-user.target" ];
    after = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = false;
      ExecStart = pkgs.writeShellScript "pixart-touchpad-fix" ''
        if ! grep -q "PIXA3848.*Touchpad" /proc/bus/input/devices; then
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

  # Ensure the touchpad is re-checked upon resuming from sleep/suspend
  powerManagement.resumeCommands = ''
    if ! grep -q "PIXA3848.*Touchpad" /proc/bus/input/devices; then
      ${pkgs.kmod}/bin/modprobe -r i2c_hid_acpi || true
      sleep 0.5
      ${pkgs.kmod}/bin/modprobe i2c_hid_acpi
    fi
  '';
}
