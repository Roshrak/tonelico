# Exact overview chord, handled without patching KWin C++ source so all KDE
# packages hit cache.nixos.org binary substitutes.
{ ... }:
{
  nixos.overview =
    { pkgs, ... }:
    let
      plasmaOverviewChord = pkgs.writeScriptBin "tonelico-plasma-overview-chord" ''
        #!${pkgs.python3}/bin/python3
        import glob, os, select, struct, subprocess

        EV_KEY = 0x01
        KEY_LEFTMETA = 125
        KEY_RIGHTMETA = 126
        KEY_LEFTSHIFT = 42
        KEY_RIGHTSHIFT = 54
        BTN_MIDDLE = 0x112
        EVENT_FMT = "llHHi"
        EVENT_SIZE = struct.calcsize(EVENT_FMT)

        fds = {}
        for path in glob.glob("/dev/input/event*"):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                fds[fd] = path
            except OSError:
                pass

        pressed = set()
        while fds:
            r, _, _ = select.select(list(fds.keys()), [], [], 5.0)
            for fd in r:
                try:
                    data = os.read(fd, EVENT_SIZE * 16)
                except OSError:
                    os.close(fd)
                    fds.pop(fd, None)
                    continue
                for offset in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                    _, _, ev_type, code, value = struct.unpack_from(EVENT_FMT, data, offset)
                    if ev_type != EV_KEY:
                        continue
                    if value == 1:
                        pressed.add(code)
                        if code == BTN_MIDDLE and (
                            (KEY_LEFTMETA in pressed or KEY_RIGHTMETA in pressed)
                            and (KEY_LEFTSHIFT in pressed or KEY_RIGHTSHIFT in pressed)
                        ):
                            subprocess.Popen([
                                "${pkgs.dbus}/bin/dbus-send",
                                "--session",
                                "--type=method_call",
                                "--dest=org.kde.kglobalaccel",
                                "/component/kwin",
                                "org.kde.kglobalaccel.Component.invokeShortcut",
                                "string:Overview",
                            ])
                    elif value == 0:
                        pressed.discard(code)
      '';
    in
    {
      systemd.user.services.tonelico-plasma-overview-chord = {
        description = "Trigger Plasma KWin Overview on Super+Shift+MiddleClick without recompiling KWin";
        wantedBy = [ "graphical-session.target" ];
        partOf = [ "graphical-session.target" ];
        unitConfig.ConditionEnvironment = "THEME_PROFILE=kde";
        serviceConfig = {
          ExecStart = "${plasmaOverviewChord}/bin/tonelico-plasma-overview-chord";
          Restart = "on-failure";
          RestartSec = 2;
        };
      };
    };
}
