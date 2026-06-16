# zenbuji（全部字）

Take Japanese text and get **furigana** (readings) plus **English and German**
translations — from the command line, a global **hotkey** on whatever text you
have selected, a **screen-region OCR** grab for text you *can't* select, the
GNOME **top-bar menu**, or the **Files context menu**. Built for immersive
Japanese learners who want a reading + meaning for *anything* on screen, fast.

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
| **Screen OCR** (`Super+Shift+J`) | Draw a box around *any* on-screen Japanese — UI text, a game, a video frame — and OCR reads it. For text you can't select. |
| **Top-bar menu** | Click the `振` icon, type or paste Japanese, get furigana + EN/DE inline, grab a screen region, and re-open any **recent** lookup. |
| **Files context menu** | Right-click a text file ▸ *Scripts ▸ zenbuji*, or (with `nautilus-python`) a direct context-menu entry. |
| **CLI** | `zenbuji <text>` / pipe stdin / `--selection` / `ocr`. |

All language processing lives in the `zenbuji` Python CLI; the extension and
Nautilus integration just call it and render the result.

## Requirements

- GNOME Shell 45–50 on **Wayland**
- `python3` with PyGObject and GTK 4 (standard on GNOME)
- `wl-clipboard` (`wl-paste`) for selection lookup
- ~1.7 GB disk for the offline translation backend (CPU-only PyTorch + models).
  Skip it with `--light` and use DeepL instead.
- Screen-region OCR uses [manga-ocr] (installed with the full backend) and the
  XDG desktop Screenshot portal — no extra tools needed on Wayland.

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
zenbuji ocr                       # capture a screen region and OCR it
zenbuji ocr screenshot.png        # OCR an existing image file
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

### Screen-region OCR

Lots of Japanese on screen isn't selectable — text baked into a UI, a game, a
video frame, an image. Press **`Super+Shift+J`** (or top-bar ▸ *Look up screen
region*), **draw a box** around the text, and zenbuji reads it with OCR, then
shows furigana + EN/DE in the usual popup. The recognized text sits in an
**editable field** — OCR isn't perfect, so fix a stray character and press Enter
to look it up again.

```sh
zenbuji ocr                  # capture a region interactively
zenbuji ocr image.png        # or OCR a file you already have
```

OCR is provided by [manga-ocr] (a Japanese-tuned model) and runs **fully
offline**. It needs the **full install** (not `--light`) and downloads a ~450MB
model on first use. Each lookup loads the model fresh, so the first result takes
a few seconds — the popup shows a spinner while it works. Region capture goes
through the desktop Screenshot portal (GNOME's own screenshot UI), so it works
on Wayland.

### Configuration

The easiest way is the **extension settings UI** (`gnome-extensions prefs
zenbuji@meeksi39`, or *Extensions ▸ zenbuji ▸ Settings*): set the **DeepL API
key**, pick the **backend** and **languages**, choose the **interface
language** (English or 日本語), **verify** the key (shows your remaining DeepL
quota), toggle/clear the recent-lookup **history**, flip the popup's
**close-on-focus-loss** behaviour, and **rebind the hotkeys** (click a shortcut
in *Shortcuts* and press the new combo). The UI reads and writes the same config
file the CLI uses, so every surface stays in sync.

From the command line:

```sh
zenbuji config                          # show current config
zenbuji config --backend argos          # offline (default)
zenbuji config --backend deepl --deepl-key <KEY>
zenbuji config --lang en,de             # which languages to show
zenbuji config --ui-language ja         # interface language (en or ja)
zenbuji config --popup-close-on-focus-loss off   # keep popup open until Escape
zenbuji config --history off            # stop recording recent lookups
zenbuji config --clear-history          # forget recorded lookups
zenbuji usage                           # check the DeepL key + remaining quota
```

Config lives in `~/.config/zenbuji/config.json`. The DeepL key can also come
from `$DEEPL_API_KEY`. `auto` (the default) uses DeepL when a key is set,
otherwise the offline backend. Recent lookups are stored in
`~/.local/share/zenbuji/history.json`.

The popup window has **copy buttons** next to the reading and each translation.

### Frosted-glass popup

The popup is a headerless, translucent floating card that follows your system
light/dark theme, can be **dragged** from any empty spot, and dismisses on
**Escape** — and, optionally, when it loses focus (toggle *Close when it loses
focus* in the settings). Its tint tracks the ~15px corner radius of GNOME's
[Blur My Shell] "Applications" component.

GNOME/Mutter has no way for an app to blur what's behind its own window, so the
real blur is supplied by Blur My Shell. `install.sh` adds `com.meeksi39.zenbuji`
to its **Applications ▸ whitelist** automatically (idempotent; removed on
uninstall). For the best effect, in Blur My Shell:

- **Applications blur**: enabled,
- **static blur**: off — blurs the live windows behind the popup, not the
  wallpaper,
- **hacks level**: 1 or higher — avoids a blur artifact when the popup is moved.

Without Blur My Shell the popup degrades gracefully to a clean translucent panel.

[Blur My Shell]: https://extensions.gnome.org/extension/3193/blur-my-shell/

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
[manga-ocr]: https://github.com/kha-white/manga-ocr
