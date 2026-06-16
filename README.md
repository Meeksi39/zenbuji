# zenbuji（全部字）

Take Japanese text and get **furigana** (readings) plus **English and German**
translations — from the command line, a global **hotkey** on whatever text you
have selected, the GNOME **top-bar menu**, or the **Files context menu**. Built
for immersive Japanese learners who want a reading + meaning for *anything* on
screen, fast.

```text
$ zenbuji 日本語を勉強しています
日本語を勉強しています
  にほんごをべんきょうしています
  日本語（にほんご） 勉強（べんきょう）

English: I am studying Japanese.
German: Ich lerne Japanisch.
```

<!-- Add a screenshot of the top-bar menu / popup to docs/ once the extension
     is loaded:  ![zenbuji](docs/menu.png) -->

- **Furigana** is generated **offline** with [fugashi] + [unidic-lite] (real
  word-level readings, not naïve kana mapping).
- **Translation** is **offline-first** via [Argos Translate]; an optional
  **DeepL** free-API backend is available when you set a key. Both **English and
  German** are shown.
- **Omni-available**: a GNOME global shortcut looks up the current selection in
  any app, a top-bar menu lets you type/paste text, and a Nautilus entry handles
  text files.

> Built for my own Bazzite (Fedora Silverblue) / GNOME Wayland system first.
> Free to use and adapt for your own setup — **just mention me** (Meeksi39).

## How it works

GNOME Wayland has no API for adding an item to *every* application's right-click
menu, so "omni-available" is delivered the way that actually works everywhere:

| Surface | What it does |
|---|---|
| **Global hotkey** (`Super+J`) | Reads the current PRIMARY selection (`wl-paste -p`) and shows a popup. Select text in any app, press the key. |
| **Top-bar menu** | Click the `振` icon, type or paste Japanese, get furigana + EN/DE inline. |
| **Files context menu** | Right-click a text file ▸ *Scripts ▸ zenbuji*, or (with `nautilus-python`) a direct context-menu entry. |
| **CLI** | `zenbuji <text>` / pipe stdin / `--selection`. |

All language processing lives in the `zenbuji` Python CLI; the extension and
Nautilus integration just call it and render the result.

## Requirements

- GNOME Shell 45–50 on **Wayland**
- `python3` with PyGObject and GTK 4 (standard on GNOME)
- `wl-clipboard` (`wl-paste`) for selection lookup
- ~1.7 GB disk for the offline translation backend (CPU-only PyTorch + models).
  Skip it with `--light` and use DeepL instead.

## Install

```sh
git clone git@github.com:Meeksi39/zenbuji.git ~/zenbuji
cd ~/zenbuji
./install.sh                 # CLI + extension + Nautilus + offline backend
./install.sh --models        # ...and download the offline models now
gnome-extensions enable zenbuji@meeksi39
```

On Bazzite/Silverblue the system Python is immutable, so dependencies install
into a venv at `~/.local/share/zenbuji/venv` — no `rpm-ostree` layering, no
reboot. On **Wayland you must log out and back in** for GNOME to load the
extension.

Lighter install (no offline backend, ~300 MB):

```sh
./install.sh --light
zenbuji config --backend deepl --deepl-key <YOUR_DEEPL_KEY>
```

Other modes:

```sh
./install.sh --uninstall     # remove CLI, extension, Nautilus entry (keeps config)
```

`install.sh` only touches: `~/.local/bin/{zenbuji,zb}`, the extension dir, the
Nautilus script, and the venv. Your config in `~/.config/zenbuji/` is never
deleted.

## Usage

### Command line

```sh
zenbuji 日本語を勉強しています   # furigana + EN + DE
zenbuji furigana 今日は良い天気    # readings only
zenbuji tr これは何ですか          # translation only
zenbuji --selection               # process the current text selection
echo "ありがとう" | zenbuji        # from stdin
zenbuji --json 速い               # machine-readable output
zenbuji popup 速い                # GTK popup window
```

`zb` is a short alias for `zenbuji`. Example output:

```
日本語を勉強しています
  にほんごをべんきょうしています
  日本語（にほんご） 勉強（べんきょう）

English: I am studying Japanese.
German: Ich lerne Japanisch.
```

### Hotkey

`install.sh` registers **`Super+J`** as a GNOME *custom keyboard shortcut* that
runs `zenbuji popup --selection`. It works immediately (no logout) and doesn't
depend on the extension being enabled. Re-bind it under **Settings ▸ Keyboard ▸
Custom Shortcuts**, or with gsettings:

```sh
P=org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/zenbuji/
gsettings set "$P" binding '<Super>F9'
```

### Configuration

```sh
zenbuji config                          # show current config
zenbuji config --backend argos          # offline (default)
zenbuji config --backend deepl --deepl-key <KEY>
zenbuji config --lang en,de             # which languages to show
```

Config lives in `~/.config/zenbuji/config.json`. The DeepL key can also come
from `$DEEPL_API_KEY`. `auto` (the default) uses DeepL when a key is set,
otherwise the offline backend.

### Offline models

```sh
zenbuji models --install   # download ja↔en, en↔de packages
zenbuji models --list      # show installed language packs
```

German is produced by pivoting through English (ja→en→de) when no direct model
exists — DeepL gives better German if you have a key.

## Motivation

I'm learning Japanese and wanted a reading + meaning for *anything* on screen
without breaking immersion — subtitles, a web page, a chat message — instead of
copying text into a separate dictionary app every time. zenbuji puts furigana
and an EN/DE gloss one keypress away, anywhere in the OS.

Built for my system first. If you want to adapt it for yours, go ahead — **just
mention me**.

## Development

The repo is the source of truth; `install.sh` symlinks the extension and points
the CLI launcher at `bin/zenbuji.py`, so edits take effect immediately (reload
GNOME Shell / log out on Wayland for extension changes). Watch extension logs:

```sh
journalctl -f -o cat /usr/bin/gnome-shell
```

[fugashi]: https://github.com/polm/fugashi
[unidic-lite]: https://github.com/polm/unidic-lite
[Argos Translate]: https://github.com/argosopentech/argos-translate
