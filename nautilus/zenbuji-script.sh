#!/usr/bin/env bash
# zenbuji — Nautilus (Files) script.
#
# Installed to ~/.local/share/nautilus/scripts/ by install.sh, this appears in
# the Files right-click menu under  Scripts ▸ zenbuji (furigana + translation).
# It reads the selected text file (or the clipboard if none is selected) and
# shows the zenbuji popup. Works out of the box — no nautilus-python needed.

set -euo pipefail

ZENBUJI="${ZENBUJI_CMD:-zenbuji}"

text=""
# NAUTILUS_SCRIPT_SELECTED_FILE_PATHS is newline-separated.
if [[ -n "${NAUTILUS_SCRIPT_SELECTED_FILE_PATHS:-}" ]]; then
    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        if [[ -f "$f" ]]; then
            text="$(head -c 4000 "$f")"
            break
        fi
    done <<< "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"
fi

if [[ -n "$text" ]]; then
    "$ZENBUJI" popup "$text"
else
    # Fall back to the current selection / clipboard.
    "$ZENBUJI" popup --selection
fi
