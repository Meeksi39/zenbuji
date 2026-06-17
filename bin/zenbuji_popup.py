#!/usr/bin/env python3
"""GTK4 popup window for zenbuji results.

Shows the original text (editable, so OCR/selection mistakes can be fixed and
re-looked-up), a full hiragana reading, a per-word breakdown, and the configured
translations. Closes on Escape, so it behaves like a quick lookup overlay
triggered from a hotkey.

Lookups (and OCR) run in a background thread with a spinner, so the window stays
responsive and appears immediately even while the OCR model loads.
"""

from __future__ import annotations

import html
import os
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

try:
    from zenbuji_glass import accent_hex, make_glass_window
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zenbuji_glass import accent_hex, make_glass_window

# Target-language section labels, shown in the interface language.
LANG_NAMES_BY_UI = {
    "en": {"en": "English", "de": "Deutsch", "ja": "日本語"},
    "ja": {"en": "英語", "de": "ドイツ語", "ja": "日本語"},
}

# UI chrome strings, by interface language. Target-language section labels
# (LANG_NAMES) are intentionally left in their own language.
UI_STRINGS = {
    "placeholder":   {"en": "Japanese text…",        "ja": "日本語のテキスト…"},
    "look_up":       {"en": "Look up",               "ja": "調べる"},
    "copy":          {"en": "Copy",                  "ja": "コピー"},
    "read_aloud":    {"en": "Read aloud",            "ja": "読み上げる"},
    "looking_up":    {"en": "Looking up…",           "ja": "検索中…"},
    "recognising":   {"en": "Recognising…",          "ja": "認識中…"},
    "lookup_failed": {"en": "Lookup failed.",        "ja": "検索に失敗しました。"},
    "no_text":       {"en": "No text recognised.",   "ja": "テキストを認識できませんでした。"},
    "dictionary":    {"en": "Dictionary",            "ja": "辞書"},
}


def _make_tr(ui_language):
    """Return a translator t(key) for the given interface language."""
    def t(key):
        entry = UI_STRINGS.get(key, {})
        return entry.get(ui_language) or entry.get("en") or key
    return t


def _spawn_dictionary():
    """Open the dictionary window in a separate process (self-reinvocation)."""
    cli = str(Path(__file__).resolve().parent / "zenbuji.py")
    try:
        subprocess.Popen([sys.executable, cli, "dict"],
                         start_new_session=True)
    except OSError:
        pass


def _ruby_markup(tokens, accent=None) -> str:
    """Build Pango markup approximating furigana: reading shown small in-line,
    in the system accent color when available."""
    fg = f" foreground='{accent}'" if accent else ""
    parts = []
    for t in tokens:
        surf = html.escape(t.surface)
        if t.has_kanji and t.reading and t.reading != t.surface:
            rd = html.escape(t.reading)
            parts.append(f"{surf}<span size='x-small'{fg}> [{rd}]</span>")
        else:
            parts.append(surf)
    return "".join(parts)


def _copy_row(window, label_widget, text, copy_label="Copy",
              speak_fn=None, speak_text=None, read_label="Read aloud"):
    """Wrap a label in a row with a flat copy-to-clipboard button.

    When `speak_fn` and `speak_text` are given, a 🔊 read-aloud button is added
    before the copy button (used for the reading row).
    """
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    label_widget.set_hexpand(True)
    row.append(label_widget)
    if speak_fn is not None and speak_text:
        speak_btn = Gtk.Button(icon_name="audio-volume-high-symbolic")
        speak_btn.add_css_class("flat")
        speak_btn.add_css_class("zenbuji-icon")
        speak_btn.set_valign(Gtk.Align.START)
        speak_btn.set_tooltip_text(read_label)
        speak_btn.connect("clicked", lambda _b: speak_fn(speak_text))
        row.append(speak_btn)
    btn = Gtk.Button(icon_name="edit-copy-symbolic")
    btn.add_css_class("flat")
    btn.add_css_class("zenbuji-icon")
    btn.set_valign(Gtk.Align.START)
    btn.set_tooltip_text(copy_label)
    btn.connect("clicked", lambda _b: window.get_clipboard().set(text))
    row.append(btn)
    return row


def show_popup(languages, *, result=None, ocr_image=None,
               process_fn=None, ocr_fn=None, ui_language="en",
               close_on_focus_loss=True, quota_fn=None, char_limit=200,
               speak_fn=None, auto_speak=False) -> int:
    """Display the popup.

    Exactly one of `result` (already-processed) or `ocr_image` (recognise text
    asynchronously) seeds the window. `process_fn(text) -> Result` runs a fresh
    lookup when the text is edited; `ocr_fn(path) -> (text, notes)` does OCR.
    `ui_language` ("en"/"ja") selects the interface language.
    `close_on_focus_loss` dismisses the window when it stops being the active
    window (HUD-style); set False to keep it open until Escape/closed.
    `quota_fn() -> deepl_usage dict | None` feeds the small DeepL quota node
    (shown only when it returns an ok result).
    """
    t = _make_tr(ui_language)
    lang_names = LANG_NAMES_BY_UI.get(ui_language, LANG_NAMES_BY_UI["en"])
    # NON_UNIQUE so a popup and the dictionary window (same app-id, kept for the
    # Blur My Shell whitelist) can run as independent processes side by side.
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        win, box = make_glass_window(
            application, title="zenbuji 全部字", default_size=(460, -1),
            resizable=False, draggable=True,
            close_on_focus_loss=close_on_focus_loss)

        # --- Optional OCR screenshot preview ------------------------------ //
        if ocr_image:
            try:
                texture = Gdk.Texture.new_from_filename(ocr_image)
                pic = Gtk.Picture.new_for_paintable(texture)
                pic.set_content_fit(Gtk.ContentFit.CONTAIN)
                pic.set_can_shrink(True)
                pic.set_size_request(-1, 120)
                pic.add_css_class("zenbuji-ocr-image")
                # border-radius on a GtkPicture only rounds the CSS box; the
                # texture itself is clipped to it only with overflow=HIDDEN.
                pic.set_overflow(Gtk.Overflow.HIDDEN)
                box.append(pic)
            except Exception:  # noqa: BLE001  (unreadable capture)
                pass

        # --- Editable input row ------------------------------------------- //
        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        entry = Gtk.Entry(hexpand=True, placeholder_text=t("placeholder"))
        entry.add_css_class("zenbuji-original")
        entry.set_max_length(int(char_limit) if char_limit else 0)
        dict_btn = Gtk.Button(icon_name="accessories-dictionary-symbolic")
        dict_btn.add_css_class("flat")
        dict_btn.add_css_class("zenbuji-icon")
        dict_btn.set_valign(Gtk.Align.CENTER)
        dict_btn.set_tooltip_text(t("dictionary"))
        dict_btn.connect("clicked", lambda _b: _spawn_dictionary())
        lookup_btn = Gtk.Button(label=t("look_up"))
        lookup_btn.add_css_class("zenbuji-action")
        lookup_btn.set_valign(Gtk.Align.CENTER)
        input_row.append(entry)
        input_row.append(dict_btn)
        input_row.append(lookup_btn)
        box.append(input_row)

        # --- Busy / status row -------------------------------------------- //
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        spinner = Gtk.Spinner()
        status_label = Gtk.Label(xalign=0, wrap=True)
        status_label.add_css_class("zenbuji-status")
        status_row.append(spinner)
        status_row.append(status_label)
        status_row.set_visible(False)
        box.append(status_row)

        hairline = Gtk.Box()
        hairline.add_css_class("zenbuji-hairline")
        hairline.set_margin_top(2)
        hairline.set_margin_bottom(2)
        box.append(hairline)

        # --- Result area (rebuilt on each lookup) ------------------------- //
        result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(result_box)

        # --- DeepL quota node (filled async; hidden until/unless available) - //
        quota_label = Gtk.Label(xalign=0, wrap=True)
        quota_label.add_css_class("zenbuji-quota")
        quota_label.set_visible(False)
        box.append(quota_label)

        def refresh_quota():
            if quota_fn is None:
                return

            def work():
                try:
                    info = quota_fn()
                except Exception:  # noqa: BLE001
                    info = None
                GLib.idle_add(show_quota, info)

            threading.Thread(target=work, daemon=True).start()

        def show_quota(info):
            if info and info.get("ok"):
                used, limit = info.get("used", 0), info.get("limit", 0)
                left = max(0, limit - used)
                quota_label.set_text(
                    f"DeepL  {used:,} / {limit:,}  ({left:,} left)")
                quota_label.set_visible(True)
            else:
                quota_label.set_visible(False)
            return GLib.SOURCE_REMOVE

        def set_busy(message):
            status_label.set_text(message)
            status_row.set_visible(True)
            spinner.set_visible(True)
            spinner.start()

        def clear_busy(message=None):
            spinner.stop()
            spinner.set_visible(False)
            if message:
                status_label.set_text(message)
                status_row.set_visible(True)
            else:
                status_row.set_visible(False)

        def clear_results():
            child = result_box.get_first_child()
            while child is not None:
                result_box.remove(child)
                child = result_box.get_first_child()

        def render(res):
            clear_results()
            if res.reading and res.reading != res.text:
                reading = Gtk.Label(label=res.reading, wrap=True, xalign=0,
                                    selectable=True)
                reading.add_css_class("zenbuji-reading")
                result_box.append(_copy_row(
                    win, reading, res.reading, t("copy"),
                    speak_fn=speak_fn, speak_text=res.reading,
                    read_label=t("read_aloud")))

            if any(getattr(t, "has_kanji", False) for t in res.tokens):
                ruby = Gtk.Label(wrap=True, xalign=0, selectable=True)
                accent = accent_hex(Adw.StyleManager.get_default().get_dark())
                ruby.set_markup(_ruby_markup(res.tokens, accent))
                ruby.add_css_class("zenbuji-token-kanji")
                result_box.append(ruby)

            for lang in languages:
                val = res.translations.get(lang)
                lbl = Gtk.Label(label=lang_names.get(lang, lang.upper()), xalign=0)
                lbl.add_css_class("zenbuji-lang-label")
                result_box.append(lbl)
                tr = Gtk.Label(label=val if val else "—", wrap=True, xalign=0,
                               selectable=True)
                tr.add_css_class("zenbuji-translation")
                if val:
                    result_box.append(_copy_row(win, tr, val, t("copy")))
                else:
                    result_box.append(tr)

            for note in res.notes:
                n = Gtk.Label(label=note, wrap=True, xalign=0)
                n.add_css_class("zenbuji-note")
                result_box.append(n)

            # Read the reading aloud automatically when enabled (tts_on_lookup).
            if auto_speak and speak_fn is not None:
                spoken = res.reading or res.text
                if spoken:
                    speak_fn(spoken)

        # --- Lookup (threaded) -------------------------------------------- //
        def do_lookup(text):
            text = text.strip()
            if not text or process_fn is None:
                return
            set_busy(t("looking_up"))

            def work():
                try:
                    res = process_fn(text)
                    err = None
                except Exception as exc:  # noqa: BLE001
                    res, err = None, f"{exc}"
                GLib.idle_add(finish, res, err)

            threading.Thread(target=work, daemon=True).start()

        def finish(res, err):
            if res is None:
                clear_busy(err or t("lookup_failed"))
            else:
                clear_busy()
                render(res)
                refresh_quota()  # a lookup may have consumed DeepL quota
            return GLib.SOURCE_REMOVE

        def run_ocr(image):
            set_busy(t("recognising"))

            def work():
                try:
                    text, notes = ocr_fn(image)
                except Exception as exc:  # noqa: BLE001
                    text, notes = "", [f"{exc}"]
                GLib.idle_add(ocr_finish, text, notes)

            threading.Thread(target=work, daemon=True).start()

        def ocr_finish(text, notes):
            entry.set_text(text)
            if text.strip():
                do_lookup(text)
            else:
                clear_busy(notes[0] if notes else t("no_text"))
            return GLib.SOURCE_REMOVE

        entry.connect("activate", lambda _e: do_lookup(entry.get_text()))
        lookup_btn.connect("clicked", lambda _b: do_lookup(entry.get_text()))

        # Escape-to-close, drag and focus-loss dismissal are handled by
        # make_glass_window().
        win.present()
        refresh_quota()

        # Seed the window.
        if ocr_image is not None:
            run_ocr(ocr_image)
        elif result is not None:
            entry.set_text(result.text)
            render(result)
            entry.grab_focus()
        else:
            entry.grab_focus()

    app.connect("activate", on_activate)
    return app.run([])
