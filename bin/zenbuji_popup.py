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
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LANG_NAMES = {"en": "English", "de": "Deutsch", "ja": "日本語"}

CSS = b"""
.zenbuji-original { font-size: 20px; font-weight: 600; }
.zenbuji-reading  { font-size: 15px; color: alpha(currentColor, 0.7); }
.zenbuji-token-kanji { font-size: 15px; }
.zenbuji-lang-label { font-weight: 700; opacity: 0.6; font-size: 11px; }
.zenbuji-translation { font-size: 15px; }
.zenbuji-note { font-size: 11px; opacity: 0.6; font-style: italic; }
.zenbuji-status { font-size: 12px; opacity: 0.7; }
"""


def _ruby_markup(tokens) -> str:
    """Build Pango markup approximating furigana: reading shown small in-line."""
    parts = []
    for t in tokens:
        surf = html.escape(t.surface)
        if t.has_kanji and t.reading and t.reading != t.surface:
            rd = html.escape(t.reading)
            parts.append(f"{surf}<span size='x-small'> [{rd}]</span>")
        else:
            parts.append(surf)
    return "".join(parts)


def _copy_row(window, label_widget, text):
    """Wrap a label in a row with a flat copy-to-clipboard button."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    label_widget.set_hexpand(True)
    row.append(label_widget)
    btn = Gtk.Button(icon_name="edit-copy-symbolic")
    btn.add_css_class("flat")
    btn.set_valign(Gtk.Align.START)
    btn.set_tooltip_text("Copy")
    btn.connect("clicked", lambda _b: window.get_clipboard().set(text))
    row.append(btn)
    return row


def show_popup(languages, *, result=None, ocr_image=None,
               process_fn=None, ocr_fn=None) -> int:
    """Display the popup.

    Exactly one of `result` (already-processed) or `ocr_image` (recognise text
    asynchronously) seeds the window. `process_fn(text) -> Result` runs a fresh
    lookup when the text is edited; `ocr_fn(path) -> (text, notes)` does OCR.
    """
    app = Gtk.Application(application_id="com.meeksi39.zenbuji")

    def on_activate(application):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        win = Gtk.ApplicationWindow(application=application)
        win.set_title("zenbuji 全部字")
        win.set_default_size(460, -1)
        win.set_resizable(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(18)
        box.set_margin_end(18)
        win.set_child(box)

        # --- Editable input row ------------------------------------------- //
        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        entry = Gtk.Entry(hexpand=True, placeholder_text="Japanese text…")
        entry.add_css_class("zenbuji-original")
        lookup_btn = Gtk.Button(label="Look up")
        input_row.append(entry)
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

        box.append(Gtk.Separator())

        # --- Result area (rebuilt on each lookup) ------------------------- //
        result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(result_box)

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
                result_box.append(_copy_row(win, reading, res.reading))

            if any(getattr(t, "has_kanji", False) for t in res.tokens):
                ruby = Gtk.Label(wrap=True, xalign=0, selectable=True)
                ruby.set_markup(_ruby_markup(res.tokens))
                ruby.add_css_class("zenbuji-token-kanji")
                result_box.append(ruby)

            for lang in languages:
                val = res.translations.get(lang)
                lbl = Gtk.Label(label=LANG_NAMES.get(lang, lang.upper()), xalign=0)
                lbl.add_css_class("zenbuji-lang-label")
                result_box.append(lbl)
                tr = Gtk.Label(label=val if val else "—", wrap=True, xalign=0,
                               selectable=True)
                tr.add_css_class("zenbuji-translation")
                if val:
                    result_box.append(_copy_row(win, tr, val))
                else:
                    result_box.append(tr)

            for note in res.notes:
                n = Gtk.Label(label=note, wrap=True, xalign=0)
                n.add_css_class("zenbuji-note")
                result_box.append(n)

        # --- Lookup (threaded) -------------------------------------------- //
        def do_lookup(text):
            text = text.strip()
            if not text or process_fn is None:
                return
            set_busy("Looking up…")

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
                clear_busy(err or "Lookup failed.")
            else:
                clear_busy()
                render(res)
            return GLib.SOURCE_REMOVE

        def run_ocr(image):
            set_busy("Recognising…")

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
                clear_busy(notes[0] if notes else "No text recognised.")
            return GLib.SOURCE_REMOVE

        entry.connect("activate", lambda _e: do_lookup(entry.get_text()))
        lookup_btn.connect("clicked", lambda _b: do_lookup(entry.get_text()))

        # Close on Escape.
        key = Gtk.EventControllerKey()

        def on_key(_ctrl, keyval, _code, _state):
            if keyval == Gdk.KEY_Escape:
                win.close()
                return True
            return False

        key.connect("key-pressed", on_key)
        win.add_controller(key)

        win.present()

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
