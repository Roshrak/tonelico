# Minecraft & Integrated GPU Performance Tuning on NixOS (Acer Swift SFG16-72)

## 1. Host CPU, iGPU & Kernel Tuning (`/etc/nixos/modules/features/gaming.nix`)
1. **Intel Meteor Lake iGPU Shared Memory**:
   - Linux (`i915`/`xe` + Mesa Iris/ANV) dynamically allocates up to 50% of system LPDDR5X RAM (~7.6 GiB) to the integrated GPU regardless of the InsydeH2O BIOS UMA setting; BIOS NVRAM edits are unnecessary for VRAM capacity.
2. **Power Profile & iGPU Minimum Clock**:
   - Ensure `powerprofilesctl set performance` is active when gaming (`energy_performance_preference = performance` rather than `power`).
   - Raise the Intel iGPU minimum floor to RP1 (`echo 800 | sudo tee /sys/class/drm/card1/gt_min_freq_mhz`) to prevent 100 MHz downclock micro-stutters between frames.
3. **Declarative GameMode & VM/ZRAM Sysctls**:
   - Keep `programs.gamemode` and kernel sysctls configured in `/etc/nixos/modules/features/gaming.nix`:
     ```nix
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
     boot.kernel.sysctl = {
       "vm.page-cluster" = 0; # 1-page reads for RAM-backed ZRAM
       "vm.swappiness" = 15;
       "dev.i915.perf_stream_paranoid" = 0;
       "kernel.sched_autogroup_enabled" = 1;
     };
     ```

## 2. PrismLauncher JVM, Heap & Driver Environment (`prismlauncher.cfg` & `instance.cfg`)
1. **Enable GameMode & Pre-Touched 4 GiB Heap**:
   - Set `EnableFeralGamemode=true`, `MinMemAlloc=4096`, and `MaxMemAlloc=4096` (both globally and in per-instance `instance.cfg`).
   - Avoid allocating >4 GiB heap on a 15 GiB shared-VRAM laptop — oversized heaps starve the Intel iGPU and Mesa shader cache of LPDDR5X RAM.
2. **OpenJDK 25 Generational ZGC Flags**:
   - Set `JvmArgs` to:
     ```text
     -XX:+UnlockExperimentalVMOptions -XX:+UseZGC -XX:+ZGenerational -XX:+AlwaysPreTouch -XX:+DisableExplicitGC -XX:+ParallelRefProcEnabled -XX:+PerfDisableSharedMem -XX:+UseTransparentHugePages -Dfml.ignorePatchDiscrepancies=true -Dfml.ignoreInvalidMinecraftCertificates=true
     ```
3. **Wayland & Mesa Threaded OpenGL Environment**:
   - Set `Env` in `instance.cfg` to:
     ```ini
     Env={\"MESA_SHADER_CACHE_MAX_SIZE\":\"4G\",\"SDL_VIDEO_DRIVER\":\"wayland\",\"__GL_THREADED_OPTIMIZATIONS\":\"1\",\"mesa_glthread\":\"true\",\"vblank_mode\":\"0\"}
     ```
4. **Keep `JavaPath` Synced Across NixOS Rebuilds**:
   - After a `nixos-rebuild switch` that updates OpenJDK, inspect `strings $(which prismlauncher) | grep openjdk-25` and update `JavaPath=` in `prismlauncher.cfg` and every `instances/*/instance.cfg` so subsequent Nix garbage collection does not invalidate a stale `/nix/store/...-openjdk-25.../bin/java` path.

## 3. Fabric Mods & In-Game Settings (`options.txt` & `sodium-options.json`)
1. **Core Performance Mods (Fabric 26.3)**:
   - Alongside Fabulously Optimized (`sodium`, `lithium`, `ferritecore`, `immediatelyfast`, `entityculling`, `modernfix`, `moreculling`), ensure these Modrinth performance mods and their required libraries are present in `minecraft/mods/` across **all** PrismLauncher instances:
     - `c2me-fabric` (multithreaded chunk I/O and generation with `AVX2VNNI` native acceleration)
     - `ScalableLux` (parallelized Starlight lighting engine)
     - `BadOptimizations` (sky/lightmap/renderer caching)
     - `vmp-fabric` (entity tracking optimization)
     - `particle_core` + **`fzzy_config`** (`>= 0.7.6`; `particle_core` refuses to boot without `fzzy_config`)
   - **Do NOT install `krypton` alongside `e4mc` (`Fabulously Optimized`)**: `e4mc` and `krypton` both redirect `ServerLoginPacketListenerImpl.getCipher` at priority `1000`, causing a fatal Mixin `InjectionError` on game initialization.
   - **Audit `fabric.mod.json` dependencies after manual `.jar` installs**: Parse `fabric.mod.json` (and nested `META-INF/jars/*.jar`) across `minecraft/mods/*.jar` to verify every key in `"depends"` is satisfied before launching.
2. **In-Game `options.txt` & `sodium-options.json`**:
   - Keep `renderDistance:12` (or `<=16`) and `simulationDistance:8`, `mipmapLevels:1`, `clouds:"false"`, `entityShadows:false`, `enableVsync:false`.
   - Set `"terrain_sorting_enabled": false` and `"chunk_build_defer_mode": "ALWAYS"` in `config/sodium-options.json`.
   - Set `mode = "off"` in `config/lambdynamiclights.toml` so holding light sources does not trigger per-frame chunk lightmap rebuilds.
