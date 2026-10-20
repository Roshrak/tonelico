# The file picker every app gets when it asks to attach, open or save a file
# (Discord, browsers, Telegram, anything that uses the desktop portal).
#
# It is Yazi inside a Kitty window, served through xdg-desktop-portal-termfilechooser,
# so it is the same picker in every session. It replaces the GTK picker.
#
#   - It starts in the folder you picked from last time.
#   - Space selects, and the selection survives moving to other folders, so one
#     Enter returns files from several places at once.
#   - f / F find a folder / a file anywhere under your home by typing part of its name.
#   - r / R jump to a recently used folder / re-select recently used files.
{ ... }:
{
  nixos.file-picker =
    { config, lib, pkgs, host, ... }:

    let
      runtimeTools = with pkgs; [
        coreutils
        bash
        gnugrep
        gawk
        findutils
        file
        fd
        fzf
        ripgrep
        jq
        ffmpegthumbnailer
        poppler-utils
        imagemagick
        resvg
        yazi
      ];

      # What the find/recent lists show on the right for the highlighted entry.
      preview = pkgs.writeShellApplication {
        name = "tonelico-picker-preview";
        runtimeInputs = runtimeTools;
        # `ls` is wanted here: sorted by time with colours, which `find` cannot do.
        excludeShellChecks = [ "SC2012" ];
        text = ''
          path="$1"
          if [ -d "$path" ]; then
            ls -1AFt --color=always --group-directories-first -- "$path" | head -n 80
          elif [ -f "$path" ]; then
            printf '%s\n%s\n\n' "$(file --brief -- "$path" | cut -c1-120)" "$(ls -lh -- "$path" | awk '{print $5 "  " $6 " " $7 " " $8}')"
            case "$(file --brief --mime-type -- "$path")" in
              text/*|application/json) head -n 60 -- "$path" ;;
            esac
          else
            echo "(gone)"
          fi
        '';
      };

      # fzf front end for the picker. Runs inside Yazi (`shell --block`), so it owns
      # the terminal until it exits, then tells Yazi where to go or what to select.
      jump = pkgs.writeShellApplication {
        name = "tonelico-picker-jump";
        runtimeInputs = runtimeTools;
        text = ''
          mode="''${1:-}"
          state="''${XDG_STATE_HOME:-$HOME/.local/state}/tonelico/file-picker"
          mkdir -p "$state"
          touch "$state/recent-dirs" "$state/recent-files"

          # Colours are the terminal's own ANSI ones (0-15), so this follows the Kitty theme.
          fzf_args=(
            --height=100% --layout=reverse --border=rounded "--padding=0,1"
            --scheme=path "--tiebreak=length,end"
            --delimiter=$'\t' --with-nth=1 --ansi
            --gutter=' ' --pointer='▎' --marker='✓' --prompt='❯ ' --info=inline-right
            "--color=bg+:0,fg+:-1:bold,hl:6,hl+:6:bold,pointer:6,marker:2,prompt:6,info:8,border:8,header:8,gutter:-1,label:6:bold"
            --preview="${preview}/bin/tonelico-picker-preview {2}"
            "--preview-window=right,50%,border-left"
          )

          # Folders and files we never want to wade through.
          skip=(--exclude .git --exclude node_modules --exclude __pycache__ --exclude .cache --exclude .npm --exclude .cargo)

          # "~/short/path<TAB>/full/path": search and show the short one, act on the full one.
          pretty() {
            awk -v h="$HOME" '{ d = $0; if (index(d, h) == 1) d = "~" substr(d, length(h) + 1); print d "\t" $0 }'
          }

          go_to() {
            [ -n "$1" ] || exit 0
            ya emit cd "$1"
          }

          select_files() {
            local path
            while IFS= read -r path; do
              [ -e "$path" ] || continue
              ya emit reveal "$path"
              ya emit toggle --state=on
            done
          }

          case "$mode" in
            dirs-recent)
              sel="$(tac "$state/recent-dirs" | awk '!seen[$0]++' | while IFS= read -r d; do [ -d "$d" ] && printf '%s\n' "$d"; done \
                | pretty | fzf "''${fzf_args[@]}" --border-label=' recent folders ' \
                  --header='Enter go there   Esc back' | cut -f2 || true)"
              go_to "$sel"
              ;;
            dirs-find)
              sel="$(fd --hidden --type d "''${skip[@]}" . "$HOME" 2>/dev/null \
                | pretty | fzf "''${fzf_args[@]}" --border-label=' find a folder ' \
                  --header='type to filter   Enter go there   Esc back' | cut -f2 || true)"
              go_to "$sel"
              ;;
            files-recent)
              tac "$state/recent-files" | awk '!seen[$0]++' | while IFS= read -r f; do [ -e "$f" ] && printf '%s\n' "$f"; done \
                | pretty | fzf "''${fzf_args[@]}" --no-sort --multi --border-label=' recent files ' \
                  --header='Tab mark   Enter select   Esc back' | cut -f2 \
                | select_files || true
              ;;
            files-find)
              # Newest first, and kept in that order while you type: what you send is usually recent.
              fd --hidden --type f "''${skip[@]}" . "$HOME" -X stat -c '%Y %n' 2>/dev/null | sort -rn | cut -d' ' -f2- \
                | pretty | fzf "''${fzf_args[@]}" --no-sort --multi --border-label=' find files, newest first ' \
                  --header='type to filter   Tab mark   Enter select   Esc back' | cut -f2 \
                | select_files || true
              ;;
            *)
              echo "usage: tonelico-picker-jump dirs-recent|dirs-find|files-recent|files-find" >&2
              exit 2
              ;;
          esac
        '';
      };

      yaziConfig = pkgs.runCommand "tonelico-picker-yazi-config" { } ''
        mkdir -p $out
        cat > $out/yazi.toml <<'TOML'
        [mgr]
        ratio = [2, 6, 5]
        # Newest first: what you want to send is nearly always what you just made.
        sort_by = "mtime"
        sort_reverse = true
        sort_dir_first = true
        show_hidden = true
        linemode = "tonelico"
        scrolloff = 6

        [preview]
        max_width = 1200
        max_height = 1200
        TOML
        # Look: the Nord flavor for Yazi (github stepbrobd/nord.yazi, packaged in nixpkgs).
        # Chosen because it is an established, well-contrasted palette, and it stays the
        # same whatever Kitty theme the session uses.
        cat > $out/theme.toml <<'TOML'
        [flavor]
        use = "nord"
        TOML
        mkdir -p $out/flavors
        cp -r ${pkgs.yaziPlugins.nord} $out/flavors/nord.yazi
        chmod -R u+w $out/flavors/nord.yazi
        cat > $out/init.lua <<'LUA'
        -- Size and age beside every name, so you can tell the file you want from its lookalikes.
        function Linemode:tonelico()
          local size = self._file:size()
          local mtime = (self._file.cha.mtime or 0) // 1
          local when = mtime > 0 and os.date("%b %d  %H:%M", mtime) or ""
          return ui.Line {
            ui.Span(size and ya.readable_size(size) or "—"):fg("gray"),
            ui.Span("   " .. when):fg("darkgray"),
          }
        end

        -- Mouse: a left click on a file marks it for sending (click again to unmark).
        -- Marks stay when you move to other folders, like the keyboard Space key.
        -- Right click and the wheel keep Yazi's own behaviour.
        local picker_mode = os.getenv("TONELICO_PICKER_MODE") or "multiple"
        local click_default = Entity.click
        function Entity:click(event, up)
          if up or event.is_middle or event.is_right or picker_mode ~= "multiple" then
            return click_default(self, event, up)
          end
          local mark = not self._file:is_selected()
          ya.emit("reveal", { self._file.url })
          ya.emit("toggle", { state = mark and "on" or "off" })
        end

        -- Drag: press on a file, hold, and drag over the others. Every file from where you
        -- pressed to where the pointer is gets marked. Yazi calls Current:drag while the
        -- button is held, after Current:click on the press.
        local current_click = Current.click
        function Current:click(event, up)
          if not up and picker_mode == "multiple" and event.is_left then
            self._drag_from = event.y - self._area.y + 1
          end
          return current_click(self, event, up)
        end
        function Current:drag(event)
          if picker_mode ~= "multiple" or not self._drag_from then
            return
          end
          local to = event.y - self._area.y + 1
          local from = self._drag_from
          local lo, hi = math.min(from, to), math.max(from, to)
          for row = lo, hi do
            local file = self._folder.window[row]
            if file then
              ya.emit("reveal", { file.url })
              ya.emit("toggle", { state = "on" })
            end
          end
        end

        -- A solid badge at the start of every selected row.
        Entity:children_add(function(self)
          if self._file:is_selected() then
            return ui.Span(" ✓ "):fg("black"):bg("green"):bold()
          end
          return ui.Span("   ")
        end, 50, Entity.LEFT)

        -- Bottom bar: how many are selected, and the keys that matter for this kind of
        -- request. The wrapper says which kind it is.
        local hints = {
          multiple = { "Space", "select", "Enter", "confirm", "f", "folder", "F", "file", "r", "recent", ".", "dot-files", "Esc", "cancel" },
          single = { "Enter", "choose", "f", "folder", "F", "file", "r", "recent", ".", "dot-files", "Esc", "cancel" },
          folder = { "Enter", "open", "q", "pick this folder", "f", "find", "r", "recent", ".", "dot-files", "Esc", "cancel" },
          save = { "Enter", "open", "q", "save here", "f", "find", ".", "dot-files", "Esc", "cancel" },
        }
        local items = hints[os.getenv("TONELICO_PICKER_MODE") or "multiple"] or hints.multiple

        Status:children_remove(1, Status.LEFT)
        Status:children_remove(2, Status.LEFT)
        Status:children_remove(4, Status.RIGHT)
        Status:children_remove(5, Status.RIGHT)
        Status:children_remove(6, Status.RIGHT)

        Status:children_add(function()
          local n = #cx.active.selected
          if n == 0 then
            return ui.Line { ui.Span("  nothing selected "):fg("gray"):bg("black") }
          end
          return ui.Line { ui.Span("  ✓ " .. n .. " selected "):fg("black"):bg("green"):bold() }
        end, 100, Status.LEFT)

        Status:children_add(function()
          local spans = {}
          for i = 1, #items, 2 do
            spans[#spans + 1] = ui.Span(" " .. items[i] .. " "):fg("black"):bg("cyan"):bold()
            spans[#spans + 1] = ui.Span(" " .. items[i + 1] .. "  "):fg("gray")
          end
          return ui.Line(spans)
        end, 100, Status.RIGHT)
        LUA
        cat > $out/keymap.toml <<'TOML'
        [mgr]
        prepend_keymap = [
          { on = "<Esc>", run = "quit", desc = "Cancel (keeps the folder you were in)" },
          { on = "<C-a>", run = "toggle_all --state=on", desc = "Select everything in this folder" },
          { on = "<C-d>", run = "toggle_all --state=off", desc = "Clear the selection" },

          { on = "f", run = 'shell "tonelico-picker-jump dirs-find" --block', desc = "Find a folder by name" },
          { on = "F", run = 'shell "tonelico-picker-jump files-find" --block', desc = "Find files by name and select them" },
          { on = "r", run = 'shell "tonelico-picker-jump dirs-recent" --block', desc = "Recent folders" },
          { on = "R", run = 'shell "tonelico-picker-jump files-recent" --block', desc = "Recent files, select again" },

          { on = ["g", "d"], run = "cd ~/Downloads", desc = "Downloads" },
          { on = ["g", "p"], run = "cd ~/Pictures", desc = "Pictures" },
          { on = ["g", "s"], run = "cd ~/Pictures/Screenshots", desc = "Screenshots" },
          { on = ["g", "v"], run = "cd ~/Videos", desc = "Videos" },
          { on = ["g", "m"], run = "cd ~/Music", desc = "Music" },
          { on = ["g", "o"], run = "cd ~/Documents", desc = "Documents" },
          { on = ["g", "h"], run = "cd ~", desc = "Home" },
          { on = ["g", "t"], run = "cd /tmp", desc = "/tmp" },
        ]
        TOML
      '';

      # Save dialogs: pick the folder in Yazi, then type the file name.
      saver = pkgs.writeTextFile {
        name = "tonelico-picker-save";
        executable = true;
        destination = "/bin/tonelico-picker-save";
        # Needs readline for the pre-filled name, which the plain `bash` package lacks.
        text = ''
          #!${pkgs.bashInteractive}/bin/bash
          set -eu
          export PATH=${lib.makeBinPath runtimeTools}:$PATH

          start="$1"
          name="$2"
          out="$3"
          cwd_file="$4"
          pick="$out.pick"

          export YAZI_CONFIG_HOME=${yaziConfig}
          ${pkgs.yazi}/bin/yazi --chooser-file="$pick" --cwd-file="$cwd_file" "$start" || true

          if [ -s "$pick" ]; then
            # Enter on an existing file means "save over this one".
            target="$(head -n 1 "$pick")"
          elif [ -s "$cwd_file" ]; then
            dir="$(cat "$cwd_file")"
            printf 'Saving in %s\n' "$dir"
            read -r -e -i "$name" -p "File name (Enter saves, Ctrl-C cancels): " newname || exit 0
            [ -n "$newname" ] || exit 0
            target="$dir/$newname"
          else
            exit 0
          fi

          if [ -e "$target" ]; then
            read -r -p "$target exists. Replace it? [y/N] " answer || exit 0
            [ "$answer" = y ] || exit 0
          fi
          printf '%s' "$target" > "$out"
          rm -f "$pick"
        '';
      };

      # What termfilechooser runs. Arguments: multiple directory save path out [loglevel]
      picker = pkgs.writeShellApplication {
        name = "tonelico-file-picker";
        runtimeInputs = runtimeTools ++ [ jump saver pkgs.kitty ];
        text = ''
          multiple="''${1:-0}"
          directory="''${2:-0}"
          save="''${3:-0}"
          suggested="''${4:-}"
          out="''${5:?missing output file}"

          state="''${XDG_STATE_HOME:-$HOME/.local/state}/tonelico/file-picker"
          mkdir -p "$state"
          cwd_file="$out.cwd"

          # Where to open. Saving starts at the app's suggestion; opening starts
          # where the last pick happened, then the app's suggestion, then home.
          start="$HOME"
          last=""
          [ -r "$state/last-dir" ] && last="$(cat "$state/last-dir")"
          if [ "$save" = 1 ] && [ -n "$suggested" ]; then
            start="$suggested"
          elif [ -n "$last" ] && [ -d "$last" ]; then
            start="$last"
          elif [ -n "$suggested" ] && [ -e "$suggested" ]; then
            start="$suggested"
          fi

          if [ "$save" = 1 ]; then
            title="Save as  |  pick the folder, press q, then type the name"
          elif [ "$directory" = 1 ]; then
            title="Choose a folder  (go into it and press q, or Enter on it)"
          elif [ "$multiple" = 1 ]; then
            title="Choose files  |  Space select, Enter confirm, f/F find, r/R recent, F1 help"
          else
            title="Choose a file  |  Enter confirm, f/F find, r/R recent, F1 help"
          fi

          export YAZI_CONFIG_HOME=${yaziConfig}
          if [ "$save" = 1 ]; then
            export TONELICO_PICKER_MODE=save
            if [ -n "$suggested" ]; then name="$(basename -- "$suggested")"; else name=""; fi
            [ -d "$start" ] || start="$(dirname -- "$start")"
            [ -d "$start" ] || start="$HOME"
            run=(${saver}/bin/tonelico-picker-save "$start" "$name" "$out" "$cwd_file")
          else
            if [ "$directory" = 1 ]; then
              export TONELICO_PICKER_MODE=folder
            elif [ "$multiple" = 1 ]; then
              export TONELICO_PICKER_MODE=multiple
            else
              export TONELICO_PICKER_MODE=single
            fi
            run=(${pkgs.yazi}/bin/yazi --chooser-file="$out" --cwd-file="$cwd_file" "$start")
          fi
          ${pkgs.kitty}/bin/kitty --class tonelico-file-picker --title "$title" \
            -o initial_window_width=150c -o initial_window_height=40c \
            -o remember_window_size=no -o confirm_os_window_close=0 \
            -o window_padding_width=10 -o background_opacity=0.95 -o font_size=13 \
            "''${run[@]}" || true

          # A folder pick with nothing selected means "the folder I ended up in".
          if [ "$directory" = 1 ] && [ ! -s "$out" ] && [ -s "$cwd_file" ]; then
            cp "$cwd_file" "$out"
          fi

          # Single-file requests take exactly one answer.
          if [ "$multiple" != 1 ] && [ -s "$out" ]; then
            head -n 1 "$out" > "$out.one"
            mv "$out.one" "$out"
          fi

          # Remember where this went, so next time starts there.
          if [ -s "$out" ]; then
            # Yazi leaves out the final newline, hence the `|| [ -n ... ]`.
            while IFS= read -r picked || [ -n "$picked" ]; do
              [ -n "$picked" ] || continue
              if [ -d "$picked" ]; then dir="$picked"; else dir="$(dirname "$picked")"; fi
              printf '%s\n' "$dir" >> "$state/recent-dirs"
              [ -d "$picked" ] || printf '%s\n' "$picked" >> "$state/recent-files"
            done < "$out"
            # Next time starts where you ended up browsing, else beside the first pick.
            first="$(head -n 1 "$out")"
            if [ -s "$cwd_file" ]; then
              cat "$cwd_file" > "$state/last-dir"
            elif [ -d "$first" ]; then
              printf '%s\n' "$first" > "$state/last-dir"
            else
              dirname "$first" > "$state/last-dir"
            fi
            for list in recent-dirs recent-files; do
              tail -n 400 "$state/$list" | tac | awk '!seen[$0]++' | head -n 200 | tac > "$state/$list.new"
              mv "$state/$list.new" "$state/$list"
            done
          elif [ -s "$cwd_file" ]; then
            cat "$cwd_file" > "$state/last-dir"
          fi
          rm -f "$cwd_file"
        '';
      };
    in
    {
      xdg.portal.extraPortals = [ pkgs.xdg-desktop-portal-termfilechooser ];

      # termfilechooser 1.4 reads its config only from $XDG_CONFIG_HOME (the user's
      # ~/.config), not from /etc/xdg, so the picker has to be set there. Without it the
      # backend falls back to a bare `yazi`, which the portal's environment cannot find.
      home-manager.users.${host.primaryUser}.xdg.configFile."xdg-desktop-portal-termfilechooser/config".text = ''
        [filechooser]
        cmd=${picker}/bin/tonelico-file-picker
        default_dir=$HOME
        create_help_file=0
        open_mode=suggested
        save_mode=suggested
      '';

      # Chromium, Electron (Discord, ...) and Firefox only use the portal picker when
      # GTK_USE_PORTAL is set; otherwise they open their own GTK dialog.
      environment.sessionVariables.GTK_USE_PORTAL = "1";

      environment.systemPackages = [ picker jump ];
    }
  ;
}
