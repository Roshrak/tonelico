# Minecraft & Integrated GPU Performance Tuning on NixOS (Acer Swift SFG16-72)

## 1. Host CPU, iGPU & Kernel Tuning (`/etc/nixos/modules/features/gaming.nix`)
1. **Intel Meteor Lake iGPU Shared Memory**:
   - Linux (`i915`/`xe` + Mesa Iris/ANV) dynamically allocates up to 50% of system LPDDR5X RAM (~7.6 GiB) to the integrated GPU regardless of the InsydeH2O BIOS UMA setting; BIOS NVRAM edits are unnecessary for VRAM capacity.
2. **Power Profile & iGPU Minimum Clock**:
   - Keep `powerprofilesctl set performance` active at all times (`energy_performance_preference = performance`; never switch to `power-saver`, even when clearing RAM/processes for idle cooling, because the laptop stays on charger full-time).
   - Keep the Intel iGPU minimum floor at hardware RPn/RP1 (`800 MHz` on Meteor Lake-P `8086:7d45`, `/sys/class/drm/card1/gt_min_freq_mhz`) to prevent frame-time micro-stutters.
   - To launch `Fabulously Optimized` on CFUK with a specific PrismLauncher account profile (`Roshrak` or `Miracle_Involker`) from a background daemon, export the active Niri session environment and pass `--profile`:
     ```bash
     export XDG_RUNTIME_DIR=/run/user/1000
     export WAYLAND_DISPLAY=wayland-1
     export NIRI_SOCKET=$(ls -t /run/user/1000/niri.*.sock | head -n1)
     export XDG_CURRENT_DESKTOP=niri
     export XDG_SESSION_ID=$(loginctl list-sessions --no-legend | awk '$3=="aesc" && $4=="seat0" {print $1; exit}')
     python3 /home/aesc/vivian/launch_mc_and_spawn.py \
       --instance "Fabulously Optimized" \
       --profile "Miracle_Involker" \
       --server "alt.crazy-fools.co.uk:25565" \
       --no-spawn
     ```
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
2. **OpenJDK 25 Generational ZGC + Compact Object Headers Flags**:
   - Note: `-XX:+ZGenerational` was removed in JDK 24/25 because Generational ZGC is now the default ZGC mode. Enable JEP 519 (`-XX:+UseCompactObjectHeaders`) and ensure `/sys/kernel/mm/transparent_hugepage/shmem_enabled` is set to `advise`.
   - Set `JvmArgs` to:
     ```text
     -XX:+UnlockExperimentalVMOptions -XX:+UseZGC -XX:+UseCompactObjectHeaders -XX:+AlwaysPreTouch -XX:+DisableExplicitGC -XX:+ParallelRefProcEnabled -XX:+PerfDisableSharedMem -XX:+UseTransparentHugePages -Dfml.ignorePatchDiscrepancies=true -Dfml.ignoreInvalidMinecraftCertificates=true
     ```
3. **Wayland & Mesa Threaded OpenGL Environment (Qt INI Comma Pitfall)**:
   - Close PrismLauncher before editing `prismlauncher.cfg` or `instance.cfg` so its in-memory `QSettings` state does not overwrite disk edits on launch or exit.
   - Never put unquoted comma-separated JSON inside `Env={...}` in `instance.cfg` — Qt's `QSettings::IniFormat` parser splits unquoted strings containing `,` into a `QStringList`, fails `QJsonDocument::fromJson`, and resets `Env={}` (causing SDL3 to fall back to XWayland and fail OpenGL context creation).
   - Instead, keep `Env={\"SDL_VIDEO_DRIVER\":\"wayland\"}` as a single comma-free key and pass all driver environment variables via `WrapperCommand` (including `MESA_NO_ERROR=1` to bypass GL error checking in `iris_dri.so` since Sodium disables `GL_KHR_no_error` on Linux via `[NO_ERROR_CONTEXT_UNSUPPORTED]`):
     ```ini
     Env={\"SDL_VIDEO_DRIVER\":\"wayland\"}
     OverrideCommands=true
     WrapperCommand="/run/current-system/sw/bin/env SDL_VIDEO_DRIVER=wayland mesa_glthread=true MESA_NO_ERROR=1 MESA_SHADER_CACHE_MAX_SIZE=4G vblank_mode=0 ANV_GPL=true MESA_VK_WSI_PRESENT_MODE=immediate"
     ```
4. **Why Minecraft 26.3's Built-in Vulkan (`RenderPearl`) Backend Runs Worse Than OpenGL on Intel Meteor Lake-P (`8086:7d45`)**:
   - **Keep `preferredGraphicsBackend:"opengl"` in `options.txt`**. Decompilation of `minecraft-26.3-client.jar` (`com.mojang.renderpearl`) and `sodium-fabric-0.9.2+mc26.3.jar` reveals 5 architectural bottlenecks in 26.3's Vulkan path on Linux Intel ANV:
     1. **Sodium `DrawBackend.chooseBackend` selects CPU-bound `VK_EXT_multi_draw` (`VK_MULTIDRAW`) over `VK_INDIRECT`**: Because Mesa ANV exposes `VK_EXT_multi_draw`, Sodium checks `multiDrawDirectInterleaved()` before `multiDrawIndirect()` and uses `nvkCmdDrawMultiIndexedEXT` (a CPU-side command-buffer loop on the Render Thread) instead of indirect GPU draws (`vkCmdDrawIndexedIndirect`), whereas OpenGL offloads draws asynchronously via `mesa_glthread=true`.
     2. **Per-draw `vkCreateBufferView` + `vkDestroyBufferView` in `VulkanRenderPass.pushDescriptors()`**: Every dirty texel-buffer descriptor in a draw call synchronously creates a new `VkBufferView` and queues its destruction at frame end; OpenGL binds persistent texture objects with zero per-draw allocation.
     3. **Broken Unified Memory (UMA) check in `VulkanDevice.<init>` (`isIntegratedIntelMoltenVK`)**: Mojang checks `deviceType == INTEGRATED_GPU && vendorID == 0x8086 && driverID == 14 (VK_DRIVER_ID_MOLTENVK)` and misses Linux Mesa ANV (`driverID == 3`). As a result, `isIntegratedIntelMoltenVK` is `false` on Linux, forcing every buffer upload on the unified LPDDR5X bus through a staging buffer (`VulkanTransientMemory.uploadStaging`), a `vkCmdCopyBuffer`, and a global `vkCmdPipelineBarrier2KHR` (`VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT`).
     4. **No persistent `VkPipelineCache` & 2-frame hard stall**: `VulkanRenderPipeline.compile()` passes `pipelineCache = 0L` (`VK_NULL_HANDLE`) and `VulkanCommandEncoder.submit()` stalls at `MAX_SUBMITS_IN_FLIGHT = 2`.
     5. **Iris Shaders & ImmediatelyFast incompatibility**: `iris-fabric-1.11.7+mc26.3` (`ShaderPackScreenPlaceholder`) explicitly disables shader packs when Vulkan is active.
5. **Keep `JavaPath` Synced Across NixOS Rebuilds**:
   - After a `nixos-rebuild switch` that updates OpenJDK, inspect `strings $(which prismlauncher) | grep openjdk-25` and update `JavaPath=` in `prismlauncher.cfg` and every `instances/*/instance.cfg` so subsequent Nix garbage collection does not invalidate a stale `/nix/store/...-openjdk-25.../bin/java` path.

## 3. Fabric Mods & In-Game Settings (`options.txt` & `config/*`)
1. **Core Performance Mods (Fabric 26.3)**:
   - Alongside Fabulously Optimized (`sodium`, `lithium`, `ferritecore`, `immediatelyfast`, `entityculling`, `modernfix`, `moreculling`), ensure these Modrinth performance mods and their required libraries are present in `minecraft/mods/` across **all** PrismLauncher instances:
     - `c2me-fabric` (multithreaded chunk I/O and generation with `AVX2VNNI` native acceleration)
     - `ScalableLux` (parallelized Starlight lighting engine)
     - `BadOptimizations` (sky/lightmap/renderer caching)
     - `vmp-fabric` (entity tracking optimization)
     - `particle_core` + **`fzzy_config`** (`>= 0.7.6`; `particle_core` refuses to boot without `fzzy_config`)
   - **Do NOT install `krypton` alongside `e4mc` (`Fabulously Optimized`)**: `e4mc` and `krypton` both redirect `ServerLoginPacketListenerImpl.getCipher` at priority `1000`, causing a fatal Mixin `InjectionError` on game initialization.
   - **Audit `fabric.mod.json` dependencies after manual `.jar` installs**: Parse `fabric.mod.json` (and nested `META-INF/jars/*.jar`) across `minecraft/mods/*.jar` to verify every key in `"depends"` is satisfied before launching.
2. **In-Game `options.txt` & Mod Configs**:
   - In `options.txt`, set `preferredGraphicsBackend:"opengl"`, `enableVsync:false`, `maxFps:260`, `glDebugVerbosity:0` (disables `GL_KHR_debug` callback overhead), `maxAnisotropyBit:0` (saves 4x texture fetch bandwidth on shared LPDDR5X), `chunkSectionFadeInTime:0.0` (removes translucent chunk fade-in shader pass), `menuBackgroundBlurriness:0` (removes fullscreen Gaussian blur in menus/chat), `renderDistance:12`, `simulationDistance:8`, `mipmapLevels:1`, `renderClouds:"false"`, `entityShadows:false`, and `weatherRadius:5`.
   - In `config/sodium-options.json`, set `"chunk_build_defer_mode": "ALWAYS"` under `"performance"`, `"cpu_render_ahead_limit": 3` under `"advanced"`, and `"terrain_sorting_enabled": false` under `"debug"`.
   - In `config/dynamic_fps.json`, set `"frame_rate_target": -1` and `"run_garbage_collector": false` for `hovered`, `unfocused`, and `unplugged` so switching windows or running on battery never throttles FPS or triggers `System.gc()` pauses.
   - In `config/immediatelyfast.json`, set `"experimental_sign_text_buffering": true`; in `config/moreculling.toml`, set `signTextCulling = true` and `entityModelCulling = true`; in `config/ixeris.toml`, set `aggressiveCaching = true`.
   - In `config/lambdynlights.toml`, set `mode = "off"` and `self = false` so holding light sources does not trigger per-step chunk lightmap rebuilds.
