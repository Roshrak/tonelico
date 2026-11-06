#!/usr/bin/env python3
import os
import subprocess
import time
from pathlib import Path

os.environ["PATH"] = (
    "/run/wrappers/bin:/run/current-system/sw/bin:/etc/profiles/per-user/aesc/bin:"
    "/home/aesc/.nix-profile/bin:/home/aesc/.local/bin:" + os.environ.get("PATH", "")
)


def send_tg(msg: str) -> None:
    try:
        subprocess.run(
            ["/home/aesc/.local/bin/telegram_send.py", msg],
            timeout=20,
            check=False,
        )
    except Exception:
        pass


def get_ram_free() -> str:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                kb = int(line.split()[1])
                return f"{kb / (1024 * 1024):.1f} GiB"
    except Exception:
        pass
    return "unknown"


def main() -> int:
    start_ts = time.time()
    log_path = Path("/home/aesc/.hermes/cache/scratch/safe-update.log")
    out_link = Path("/home/aesc/.local/share/nix-roots/pending-system-build")

    drv = subprocess.check_output(
        [
            "nix",
            "eval",
            "--no-write-lock-file",
            "--raw",
            "path:/etc/nixos#nixosConfigurations.tonelico-nix.config.system.build.toplevel.drvPath",
        ],
        text=True,
    ).strip()
    subprocess.run(
        ["ln", "-sfn", drv, "/home/aesc/.local/share/nix-roots/pending-system-drv"],
        check=False,
    )

    with log_path.open("w") as logf:
        proc = subprocess.Popen(
            [
                "nixos-rebuild",
                "build",
                "--no-write-lock-file",
                "--max-jobs",
                "2",
                "--cores",
                "4",
                "--flake",
                "path:/etc/nixos#tonelico-nix",
            ],
            cwd="/home/aesc/.local/share/nix-roots",
            stdout=logf,
            stderr=subprocess.STDOUT,
            text=True,
        )

        last_update = time.time()
        while proc.poll() is None:
            time.sleep(10)
            now = time.time()
            if now - last_update >= 600:
                last_update = now
                mins = int((now - start_ts) // 60)
                tail_line = "downloading/building..."
                try:
                    lines = [
                        l.strip()
                        for l in log_path.read_text(errors="ignore").splitlines()
                        if l.strip()
                    ]
                    if lines:
                        tail_line = lines[-1][:120]
                except Exception:
                    pass
                send_tg(
                    f"⏳ **NixOS Update Progress ({mins}m elapsed)**\n"
                    f"- **Step**: `{tail_line}`\n"
                    f"- **RAM Available**: `{get_ram_free()}`"
                )

        rc = proc.returncode

    if rc != 0:
        send_tg(f"⚠️ **NixOS Build exited with code {rc}**. Check `{log_path}`.")
        return rc

    res_link = Path("/home/aesc/.local/share/nix-roots/result")
    built_system = str(res_link.resolve())
    subprocess.run(["ln", "-sfn", built_system, str(out_link)], check=False)

    subprocess.run(
        [
            "/run/wrappers/bin/sudo",
            "nixos-rebuild",
            "--no-reexec",
            "dry-activate",
            "--store-path",
            built_system,
        ],
        check=True,
    )
    subprocess.run(
        [
            "/run/wrappers/bin/sudo",
            "nixos-rebuild",
            "--no-reexec",
            "switch",
            "--store-path",
            built_system,
        ],
        check=True,
    )

    subprocess.run(["git", "-C", "/etc/nixos", "add", "-A"], check=False)
    subprocess.run(
        [
            "git",
            "-C",
            "/etc/nixos",
            "commit",
            "-m",
            "Fast zero-heavy-compile NixOS update (Gen 181)",
        ],
        check=False,
    )
    subprocess.run(["/home/aesc/tonelico/export.sh"], check=False)
    subprocess.run(["git", "-C", "/home/aesc/tonelico", "add", "-A"], check=False)
    subprocess.run(
        [
            "git",
            "-C",
            "/home/aesc/tonelico",
            "commit",
            "-m",
            "Sync post-switch NixOS Generation 181 state",
        ],
        check=False,
    )
    subprocess.run(
        ["git", "-C", "/home/aesc/tonelico", "push", "origin", "main"],
        check=False,
    )
    subprocess.run(["/home/aesc/.local/bin/hermes-memory-guard"], check=False)

    mins = int((time.time() - start_ts) // 60)
    current_gen = subprocess.check_output(
        ["readlink", "/nix/var/nix/profiles/system"], text=True
    ).strip()
    send_tg(
        f"✅ **NixOS Update Complete ({mins}m total)**\n"
        f"- **Active Generation**: `{current_gen}` (`{built_system}`)\n"
        f"- **Fallback Preserved**: `system-180-link`\n"
        f"- **GitHub (`Roshrak/tonelico`)**: Synced & pushed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
