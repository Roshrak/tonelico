{ ... }:
{
  services.udev.extraRules = ''
    # RDMCTMZT 36b0:3002 — prevent fake gamepad detection.
    SUBSYSTEM=="input", KERNEL=="event*", ATTRS{idVendor}=="36b0", ATTRS{idProduct}=="3002", ENV{ID_INPUT_JOYSTICK}=="1", ENV{ID_INPUT_JOYSTICK}=""
    # RDMCTMZT WAVE 75 36b0:3009 — its System Control endpoint is a
    # keyboard control interface, but input_id incorrectly tags it as a gamepad.
    SUBSYSTEM=="input", KERNEL=="event*", ATTRS{idVendor}=="36b0", ATTRS{idProduct}=="3009", ENV{ID_INPUT_JOYSTICK}=="1", ENV{ID_INPUT_JOYSTICK}=""
    # ATK X1 SE 373b:1107 — expose the pointer only. Its composite USB
    # receiver also advertises keyboard/consumer-control event nodes; when the
    # unstable receiver reconnects, those nodes can corrupt keyboard state.
    SUBSYSTEM=="input", KERNEL=="event*", ATTRS{idVendor}=="373b", ATTRS{idProduct}=="1107", ENV{ID_INPUT_MOUSE}!="1", ENV{LIBINPUT_IGNORE_DEVICE}="1"
    KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="36b0", ATTRS{idProduct}=="3009", MODE="0660", GROUP="users", TAG+="uaccess"
  '';
}
