#!/usr/bin/env bash
# zenbuji installer.
#
#   ./install.sh            install CLI + GNOME extension + Nautilus script,
#                           create the venv and install offline backend
#   ./install.sh --light    skip the heavy offline backend (DeepL only)
#   ./install.sh --models   also download the offline translation models
#   ./install.sh --voicevox set up the local VOICEVOX neural TTS engine
#                           (natural Japanese voices; ~1.5GB podman image)
#   ./install.sh --uninstall remove everything except your config
#
# On Bazzite/Silverblue the system Python is immutable, so dependencies live in
# a venv at ~/.local/share/zenbuji/venv. Saved config in ~/.config/zenbuji is
# never touched.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/zenbuji/venv"
BIN_DIR="$HOME/.local/bin"
EXT_UUID="zenbuji@meeksi39"
EXT_SRC="$REPO_DIR/extension/$EXT_UUID"
EXT_DST="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"
NAUTILUS_SCRIPTS="$HOME/.local/share/nautilus/scripts"
NAUTILUS_EXT_DIR="$HOME/.local/share/nautilus-python/extensions"
# Firefox native-messaging host for the YouTube caption-capture extension. The
# manifest's allowed_extensions MUST equal the extension's gecko.id (set in
# firefox/zenbuji-capture/manifest.json) or Firefox refuses to launch the host.
NMH_ID="com.meeksi39.zenbuji_capture"
NMH_DIR="$HOME/.mozilla/native-messaging-hosts"
NMH_MANIFEST="$NMH_DIR/$NMH_ID.json"
NMH_WRAPPER="$BIN_DIR/zenbuji-native-host"
WEBEXT_ID="zenbuji-capture@meeksi39"
WEBEXT_SRC="$REPO_DIR/firefox/zenbuji-capture"
# Flatpak Firefox sandboxes its native-messaging host dir under ~/.var/app.
FF_FLATPAK_NMH="$HOME/.var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts"

LIGHT=0
WITH_MODELS=0
WITH_VOICEVOX=0
MODE=install

for arg in "$@"; do
    case "$arg" in
        --light) LIGHT=1 ;;
        --models) WITH_MODELS=1 ;;
        --voicevox) WITH_VOICEVOX=1 ;;
        --uninstall) MODE=uninstall ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

backup() {
    local target="$1"
    if [[ -e "$target" && ! -L "$target" ]]; then
        local bak="$target.bak.$(date +%s)"
        echo "  backing up existing $target -> $bak"
        mv "$target" "$bak"
    fi
}

link() {
    local src="$1" dst="$2"
    backup "$dst"
    rm -rf "$dst"
    ln -s "$src" "$dst"
    echo "  linked $dst"
}

if [[ "$MODE" == uninstall ]]; then
    echo "Uninstalling zenbuji…"
    rm -f "$BIN_DIR/zenbuji" "$BIN_DIR/zb"
    rm -rf "$EXT_DST"
    rm -f "$NAUTILUS_SCRIPTS/zenbuji (furigana + translation)"
    rm -f "$NAUTILUS_EXT_DIR/zenbuji-nautilus.py"
    rm -f "$NMH_WRAPPER" "$NMH_MANIFEST" \
          "$FF_FLATPAK_NMH/$NMH_ID.json" "$FF_FLATPAK_NMH/zenbuji-spawn.sh"
    rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/zenbuji-learn.desktop"
    # App icon + desktop entry.
    rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/com.meeksi39.zenbuji.desktop"
    rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps/com.meeksi39.zenbuji.png"
    command -v gtk-update-icon-cache >/dev/null \
        && gtk-update-icon-cache -qtf "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
    # Tear down the VOICEVOX engine service/unit if we set it up (keeps the
    # pulled image — `podman rmi voicevox/voicevox_engine` reclaims that space).
    VV_UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd/voicevox.container"
    if [[ -f "$VV_UNIT" ]]; then
        systemctl --user stop voicevox.service 2>/dev/null || true
        rm -f "$VV_UNIT"
        systemctl --user daemon-reload 2>/dev/null || true
        echo "Removed the VOICEVOX engine service (kept the podman image)."
    fi
    # Remove our custom keybindings from the list (leaves other customs intact).
    MK=org.gnome.settings-daemon.plugins.media-keys
    if command -v gsettings >/dev/null; then
        for slug in zenbuji zenbuji-ocr zenbuji-ocr-add zenbuji-add zenbuji-speak zenbuji-learn zenbuji-game; do
            KBPATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/$slug/"
            cur="$(gsettings get $MK custom-keybindings 2>/dev/null || echo "@as []")"
            if [[ "$cur" == *"$KBPATH"* ]]; then
                new="$(printf '%s' "$cur" | sed "s#, *'$KBPATH'##; s#'$KBPATH', *##; s#\['$KBPATH'\]#@as []#")"
                gsettings set $MK custom-keybindings "$new"
                echo "Removed the $slug custom keybinding."
            fi
        done
    fi
    # Remove our app-id from Blur My Shell's whitelist (leaves others intact).
    BMS_DIR="$HOME/.local/share/gnome-shell/extensions/blur-my-shell@aunetx"
    BMS_SCHEMA="org.gnome.shell.extensions.blur-my-shell.applications"
    if command -v gsettings >/dev/null && [[ -d "$BMS_DIR/schemas" ]]; then
        cur="$(GSETTINGS_SCHEMA_DIR="$BMS_DIR/schemas" gsettings get "$BMS_SCHEMA" whitelist 2>/dev/null || echo '@as []')"
        if [[ "$cur" == *"'com.meeksi39.zenbuji'"* ]]; then
            new="$(python3 - "$cur" <<'PY'
import sys, ast
s = sys.argv[1].strip()
s = s[4:].strip() if s.startswith("@as ") else s
lst = [x for x in (ast.literal_eval(s) if s else []) if x != "com.meeksi39.zenbuji"]
print(lst)
PY
)"
            GSETTINGS_SCHEMA_DIR="$BMS_DIR/schemas" gsettings set "$BMS_SCHEMA" whitelist "$new"
            echo "Removed com.meeksi39.zenbuji from the Blur My Shell whitelist."
        fi
    fi
    echo "Removed CLI, extension and Nautilus integration."
    echo "Kept: venv at $VENV (delete by hand to reclaim space),"
    echo "      config at ~/.config/zenbuji."
    echo "Disable the extension with: gnome-extensions disable $EXT_UUID"
    exit 0
fi

echo "Installing zenbuji from $REPO_DIR"

# --- venv + Python deps -------------------------------------------------- #
echo "Setting up venv at $VENV"
mkdir -p "$(dirname "$VENV")"
# --system-site-packages lets the venv use the system PyGObject/GTK (which can't
# be pip-installed on an immutable OS); our pip packages still take precedence.
[[ -d "$VENV" ]] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install -q --upgrade pip wheel
echo "  installing furigana deps (fugashi, unidic-lite, jaconv)…"
"$VENV/bin/pip" install -q fugashi unidic-lite jaconv

if [[ "$LIGHT" -eq 0 ]]; then
    echo "  installing offline translation backend (CPU torch — large)…"
    "$VENV/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
    "$VENV/bin/pip" install -q argostranslate
    echo "  installing OCR backend (manga-ocr — Japanese screen-region OCR)…"
    "$VENV/bin/pip" install -q manga-ocr
else
    echo "  --light: skipping offline backend (configure DeepL with: zenbuji config --deepl-key …)"
    echo "  --light: skipping OCR backend (screen-region OCR will be unavailable)"
fi

# --- CLI launchers ------------------------------------------------------- #
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/zenbuji" <<EOF
#!/usr/bin/env bash
# Generated by zenbuji install.sh — runs the CLI inside its venv.
exec "$VENV/bin/python" "$REPO_DIR/bin/zenbuji_main.py" "\$@"
EOF
chmod +x "$BIN_DIR/zenbuji"
ln -sf "$BIN_DIR/zenbuji" "$BIN_DIR/zb"
echo "  installed $BIN_DIR/zenbuji (+ zb alias)"

# --- Firefox native-messaging host (YouTube caption capture) ------------- #
# The Firefox extension (firefox/zenbuji-capture, loaded by hand — see its
# README) streams captions to `zenbuji native-host` over native messaging. We
# register the host here; the extension itself isn't installed into Firefox.
mkdir -p "$NMH_DIR"
cat > "$NMH_WRAPPER" <<EOF
#!/usr/bin/env bash
# Generated by zenbuji install.sh — Firefox native-messaging host entry point.
exec "$BIN_DIR/zenbuji" native-host "\$@"
EOF
chmod +x "$NMH_WRAPPER"
cat > "$NMH_MANIFEST" <<EOF
{
  "name": "$NMH_ID",
  "description": "zenbuji YouTube caption capture host",
  "path": "$NMH_WRAPPER",
  "type": "stdio",
  "allowed_extensions": ["$WEBEXT_ID"]
}
EOF
echo "  registered Firefox native-messaging host: $NMH_MANIFEST"
# Flatpak Firefox runs native-messaging hosts INSIDE its sandbox, where the host
# wrapper in ~/.local/bin isn't visible. So for Flatpak we install a stub in the
# sandbox-reachable manifest dir that breaks out to the host via flatpak-spawn,
# point the manifest at the stub's in-sandbox path (~/.mozilla maps to this dir
# inside the sandbox), and grant Firefox permission to spawn host processes.
if [[ -d "$HOME/.var/app/org.mozilla.firefox" ]]; then
    mkdir -p "$FF_FLATPAK_NMH"
    cat > "$FF_FLATPAK_NMH/zenbuji-spawn.sh" <<EOF
#!/bin/sh
# Runs inside the Firefox Flatpak sandbox; breaks out to the host to run the
# real native-messaging host (stdio, the native-messaging pipe, is forwarded).
exec flatpak-spawn --host "$NMH_WRAPPER" "\$@"
EOF
    chmod +x "$FF_FLATPAK_NMH/zenbuji-spawn.sh"
    cat > "$FF_FLATPAK_NMH/$NMH_ID.json" <<EOF
{
  "name": "$NMH_ID",
  "description": "zenbuji YouTube caption capture host",
  "path": "$HOME/.mozilla/native-messaging-hosts/zenbuji-spawn.sh",
  "type": "stdio",
  "allowed_extensions": ["$WEBEXT_ID"]
}
EOF
    if command -v flatpak >/dev/null; then
        flatpak override --user --talk-name=org.freedesktop.Flatpak org.mozilla.firefox 2>/dev/null \
            && echo "  registered the host for Flatpak Firefox + granted spawn permission" \
            || echo "  registered the host for Flatpak Firefox (could not set the flatpak override; run:
    flatpak override --user --talk-name=org.freedesktop.Flatpak org.mozilla.firefox)"
    else
        echo "  registered the host for Flatpak Firefox"
    fi
    echo "    (restart Firefox so the permission takes effect)"
fi
echo "  Firefox extension lives at $WEBEXT_SRC"
echo "    load it via about:debugging ▸ Load Temporary Add-on (see firefox/README.md)"

# --- App icon + desktop entry -------------------------------------------- #
# Every GTK window runs under the app-id com.meeksi39.zenbuji, so a desktop file
# of that name (matching StartupWMClass) lets GNOME show our icon for them in
# the dock / window list. The icon lives in the hicolor theme.
APP_ID="com.meeksi39.zenbuji"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$ICON_DIR" "$APPS_DIR"
cp "$REPO_DIR/icons/$APP_ID.png" "$ICON_DIR/$APP_ID.png"
cat > "$APPS_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=zenbuji
GenericName=Japanese reading helper
Comment=Furigana + EN/DE translation for Japanese, anywhere on screen
Exec=$BIN_DIR/zenbuji dict
Icon=$APP_ID
Terminal=false
Categories=Education;
Keywords=Japanese;furigana;kanji;translation;
StartupWMClass=$APP_ID
EOF
command -v gtk-update-icon-cache >/dev/null \
    && gtk-update-icon-cache -qtf "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null \
    && update-desktop-database "$APPS_DIR" 2>/dev/null || true
echo "  installed app icon + $APPS_DIR/$APP_ID.desktop"

# --- GNOME extension ----------------------------------------------------- #
mkdir -p "$(dirname "$EXT_DST")"
link "$EXT_SRC" "$EXT_DST"
if command -v glib-compile-schemas >/dev/null; then
    glib-compile-schemas "$EXT_SRC/schemas" >/dev/null
    echo "  compiled GSettings schema"
fi

# --- Nautilus integration ------------------------------------------------ #
mkdir -p "$NAUTILUS_SCRIPTS"
SCRIPT_DST="$NAUTILUS_SCRIPTS/zenbuji (furigana + translation)"
cp "$REPO_DIR/nautilus/zenbuji-script.sh" "$SCRIPT_DST"
chmod +x "$SCRIPT_DST"
echo "  installed Nautilus script: right-click ▸ Scripts ▸ zenbuji"

if "$VENV/bin/python" -c "import gi; gi.require_version('Nautilus','4.0')" 2>/dev/null \
   || python3 -c "import gi; gi.require_version('Nautilus','4.0')" 2>/dev/null; then
    mkdir -p "$NAUTILUS_EXT_DIR"
    ln -sf "$REPO_DIR/nautilus/zenbuji-nautilus.py" "$NAUTILUS_EXT_DIR/zenbuji-nautilus.py"
    echo "  installed Nautilus context-menu extension (restart Files to load)"
else
    echo "  (nautilus-python not found — skipping the context-menu extension;"
    echo "   the Scripts entry above works without it)"
fi

# --- Global hotkeys (GNOME custom keybindings) --------------------------- #
# Owned here rather than by the extension so they work immediately (no logout)
# and without the extension enabled.
MK=org.gnome.settings-daemon.plugins.media-keys

# Warn if <slug>'s key is also bound to another custom shortcut — a duplicate
# binding silently fires neither, and is the usual reason a "registered"
# shortcut does nothing. Only the media-keys custom list is scanned (where our
# own shortcuts live); clashes with built-in WM shortcuts are out of scope.
kb_warn_conflict() {
    local slug="$1" mine="$2" op ob oname
    [[ -z "$mine" || "$mine" == "''" || "$mine" == "@s ''" ]] && return
    while read -r op; do
        [[ -z "$op" || "$op" == *"/$slug/" ]] && continue
        ob="$(gsettings get "$MK.custom-keybinding:$op" binding 2>/dev/null)"
        if [[ "$ob" == "$mine" ]]; then
            oname="$(gsettings get "$MK.custom-keybinding:$op" name 2>/dev/null)"
            echo "  ! $mine also bound to $oname — one of them won't fire; rebind one"
        fi
    done < <(gsettings get $MK custom-keybindings 2>/dev/null \
        | grep -oE "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/[^/]+/")
}

# register_keybinding <slug> <name> <command> <default-binding> <human-desc>
# Idempotent and self-healing: re-adds the slug to the active list if missing
# and always rewrites name+command, so entries left blank/unlisted by an older
# install or a manual edit in GNOME Settings get repaired on reinstall. The
# binding is only set when none exists, preserving a key the user customised.
# Reports the *effective* binding (not the default) and warns on conflicts.
register_keybinding() {
    local slug="$1" name="$2" cmd="$3" binding="$4" desc="$5"
    local kbpath="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/$slug/"
    local cur ck existing eff
    cur="$(gsettings get $MK custom-keybindings 2>/dev/null || echo "@as []")"
    if [[ "$cur" != *"custom-keybindings/$slug/"* ]]; then
        if [[ "$cur" == "@as []" || "$cur" == "[]" ]]; then
            gsettings set $MK custom-keybindings "['$kbpath']"
        else
            gsettings set $MK custom-keybindings "${cur%]}, '$kbpath']"
        fi
    fi
    ck="$MK.custom-keybinding:$kbpath"
    gsettings set "$ck" name "$name"
    gsettings set "$ck" command "$cmd"
    # Don't clobber a binding the user may have customised.
    existing="$(gsettings get "$ck" binding 2>/dev/null || echo "''")"
    if [[ "$existing" == "''" || "$existing" == "@s ''" ]]; then
        gsettings set "$ck" binding "$binding"
    fi
    eff="$(gsettings get "$ck" binding 2>/dev/null)"
    echo "  bound ${eff//\'/} → $desc"
    kb_warn_conflict "$slug" "$eff"
}

if command -v gsettings >/dev/null; then
    register_keybinding zenbuji 'zenbuji: look up selection' \
        "$BIN_DIR/zenbuji popup --selection" '<Super>j' 'zenbuji popup --selection'
    register_keybinding zenbuji-ocr 'zenbuji: look up screen region (OCR)' \
        "$BIN_DIR/zenbuji popup --ocr" '<Super><Shift>j' 'zenbuji popup --ocr'
    register_keybinding zenbuji-ocr-add 'zenbuji: OCR a region into the dictionary (silent + speak)' \
        "$BIN_DIR/zenbuji add --ocr --speak" '<Super><Shift>k' 'zenbuji add --ocr --speak (silent, reads aloud)'
    register_keybinding zenbuji-add 'zenbuji: add selection to the dictionary (silent + speak)' \
        "$BIN_DIR/zenbuji add --selection --speak" '<Super>k' 'zenbuji add --selection --speak (silent, reads aloud)'
    register_keybinding zenbuji-speak 'zenbuji: read selection aloud' \
        "$BIN_DIR/zenbuji speak --selection" '<Super><Shift>s' 'zenbuji speak --selection'
    register_keybinding zenbuji-learn 'zenbuji: practice (SRS)' \
        "$BIN_DIR/zenbuji learn" '<Super><Shift>l' 'zenbuji learn'
    register_keybinding zenbuji-game 'zenbuji: game-helper overlay' \
        "$BIN_DIR/zenbuji game" '<Super><Shift>g' 'zenbuji game'
fi

# --- Blur My Shell integration (frosted-glass popup) --------------------- #
# The popup window is transparent; GNOME can't blur behind a client window on
# its own, so Blur My Shell's "Applications" component supplies the blur. Add
# our app-id to its whitelist (idempotent). Without it the popup is simply a
# clean translucent panel.
BMS_DIR="$HOME/.local/share/gnome-shell/extensions/blur-my-shell@aunetx"
BMS_APP_ID="com.meeksi39.zenbuji"
BMS_SCHEMA="org.gnome.shell.extensions.blur-my-shell.applications"
if command -v gsettings >/dev/null && [[ -d "$BMS_DIR/schemas" ]]; then
    cur="$(GSETTINGS_SCHEMA_DIR="$BMS_DIR/schemas" gsettings get "$BMS_SCHEMA" whitelist 2>/dev/null || echo '@as []')"
    if [[ "$cur" == *"'$BMS_APP_ID'"* ]]; then
        echo "  Blur My Shell already knows $BMS_APP_ID"
    else
        new="$(python3 - "$cur" "$BMS_APP_ID" <<'PY'
import sys, ast
s = sys.argv[1].strip()
s = s[4:].strip() if s.startswith("@as ") else s
lst = ast.literal_eval(s) if s else []
if sys.argv[2] not in lst:
    lst.append(sys.argv[2])
print(lst)
PY
)"
        if [[ -n "$new" ]]; then
            GSETTINGS_SCHEMA_DIR="$BMS_DIR/schemas" gsettings set "$BMS_SCHEMA" whitelist "$new"
            echo "  registered $BMS_APP_ID with Blur My Shell (frosted-glass popup)"
        fi
    fi
    if [[ "$(GSETTINGS_SCHEMA_DIR="$BMS_DIR/schemas" gsettings get "$BMS_SCHEMA" blur 2>/dev/null)" == "false" ]]; then
        echo "  note: turn on Blur My Shell ▸ Applications blur to see the glass effect"
    fi
    if [[ "$(GSETTINGS_SCHEMA_DIR="$BMS_DIR/schemas" gsettings get "$BMS_SCHEMA" static-blur 2>/dev/null)" == "true" ]]; then
        echo "  tip: Blur My Shell ▸ Applications ▸ 'static blur' is on — turn it off for"
        echo "       live blur of the windows behind the popup (vs. the wallpaper image)"
    fi
    if [[ "$(GSETTINGS_SCHEMA_DIR="$BMS_DIR/schemas" gsettings get org.gnome.shell.extensions.blur-my-shell hacks-level 2>/dev/null)" == "0" ]]; then
        echo "  tip: set Blur My Shell 'hacks level' to 1 or higher to avoid a blur"
        echo "       artifact when the popup window is dragged/moved"
    fi
else
    echo "  (Blur My Shell not found — the popup will be translucent without blur;"
    echo "   install blur-my-shell from extensions.gnome.org for frosted glass)"
fi

# --- Offline models ------------------------------------------------------ #
if [[ "$WITH_MODELS" -eq 1 && "$LIGHT" -eq 0 ]]; then
    echo "Downloading offline models (ja→en, en→de, …)…"
    "$VENV/bin/python" "$REPO_DIR/bin/zenbuji_main.py" models --install || true
    echo "Warming the OCR model (manga-ocr, ~450MB on first download)…"
    "$VENV/bin/python" -c "from manga_ocr import MangaOcr; MangaOcr()" || true
fi

# --- VOICEVOX neural TTS engine (opt-in: --voicevox) --------------------- #
# Runs the official VOICEVOX engine as a rootless podman container managed by a
# systemd --user Quadlet unit — no changes to the immutable base, no reboot.
# zenbuji then synthesizes against it over its local HTTP API (127.0.0.1:50021).
if [[ "$WITH_VOICEVOX" -eq 1 ]]; then
    echo "Setting up the VOICEVOX TTS engine…"
    if ! command -v podman >/dev/null; then
        echo "  ! podman not found — install it (or run VOICEVOX yourself), then" >&2
        echo "    re-run: ./install.sh --voicevox" >&2
    else
        VV_IMAGE="docker.io/voicevox/voicevox_engine:cpu-latest"
        VV_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd"
        echo "  pulling $VV_IMAGE (~1.5GB, first time only)…"
        podman pull "$VV_IMAGE" || echo "  ! pull failed; the service will retry on start" >&2
        mkdir -p "$VV_UNIT_DIR"
        cat > "$VV_UNIT_DIR/voicevox.container" <<UNIT
# Local VOICEVOX TTS engine for zenbuji (managed by systemd --user).
[Unit]
Description=VOICEVOX TTS engine (local HTTP, used by zenbuji)
After=network-online.target

[Container]
Image=$VV_IMAGE
PublishPort=127.0.0.1:50021:50021
AutoUpdate=registry

[Service]
Restart=always
TimeoutStartSec=300

[Install]
WantedBy=default.target
UNIT
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user start voicevox.service 2>/dev/null \
            && echo "  started voicevox.service (auto-starts on login)" \
            || echo "  ! could not start voicevox.service — check: systemctl --user status voicevox" >&2
        # Point zenbuji at the built-in VOICEVOX engine.
        "$BIN_DIR/zenbuji" config --tts-engine voicevox --tts on >/dev/null 2>&1 || true
        echo "  zenbuji TTS set to VOICEVOX (default voice: Zundamon)"
        echo "  tip: logged-out playback needs lingering — run: loginctl enable-linger \$USER"
    fi
fi

cat <<EOF

Done.

Next steps:
  • Enable the extension:  gnome-extensions enable $EXT_UUID
    (Wayland: log out and back in first so GNOME loads it.)
  • Offline models:        zenbuji models --install
  • Or use DeepL:          zenbuji config --backend deepl --deepl-key <KEY>
  • Try it:                zenbuji 日本語を勉強しています
  • Hotkey:                Super+J looks up the current selection
  • Screen OCR:            Super+Shift+J reads on-screen text (draw a box)
  • OCR → dictionary:      Super+Shift+K OCRs a region silently into the
                           dictionary and reads the word aloud (no popup)
  • Read aloud:            Super+Shift+S reads the current selection aloud
EOF

if [[ "$WITH_VOICEVOX" -eq 1 ]]; then
    cat <<EOF
  • Natural voice (TTS):   VOICEVOX is set up — pick a voice in Settings ▸ Speech
                           or test it with: zenbuji speak こんにちは
EOF
else
    cat <<EOF
  • Natural voice (TTS):   for natural Japanese instead of the robotic system
                           voice, set up VOICEVOX:  ./install.sh --voicevox
EOF
fi
