#!/usr/bin/env python3
"""GTK4 popup window for zenbuji results.

Shows the original text, a full hiragana reading, a per-word breakdown, and the
configured translations. Closes on Escape or when it loses focus, so it behaves
like a quick lookup overlay triggered from a hotkey.
"""

from __future__ import annotations

import html

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

LANG_NAMES = {"en": "English", "de": "Deutsch", "ja": "日本語"}

CSS = b"""
.zenbuji-original { font-size: 22px; font-weight: 600; }
.zenbuji-reading  { font-size: 15px; color: alpha(currentColor, 0.7); }
.zenbuji-token-kanji { font-size: 15px; }
.zenbuji-lang-label { font-weight: 700; opacity: 0.6; font-size: 11px; }
.zenbuji-translation { font-size: 15px; }
.zenbuji-note { font-size: 11px; opacity: 0.6; font-style: italic; }
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


def show_popup(result, languages) -> int:
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
        win.set_default_size(440, -1)
        win.set_resizable(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(18)
        box.set_margin_end(18)
        win.set_child(box)

        original = Gtk.Label(label=result.text, wrap=True, xalign=0, selectable=True)
        original.add_css_class("zenbuji-original")
        box.append(original)

        if result.reading and result.reading != result.text:
            reading = Gtk.Label(label=result.reading, wrap=True, xalign=0,
                                selectable=True)
            reading.add_css_class("zenbuji-reading")
            box.append(reading)

        if any(getattr(t, "has_kanji", False) for t in result.tokens):
            ruby = Gtk.Label(wrap=True, xalign=0, selectable=True)
            ruby.set_markup(_ruby_markup(result.tokens))
            ruby.add_css_class("zenbuji-token-kanji")
            box.append(ruby)

        box.append(Gtk.Separator())

        for lang in languages:
            val = result.translations.get(lang)
            lbl = Gtk.Label(label=LANG_NAMES.get(lang, lang.upper()), xalign=0)
            lbl.add_css_class("zenbuji-lang-label")
            box.append(lbl)
            tr = Gtk.Label(label=val if val else "—", wrap=True, xalign=0,
                           selectable=True)
            tr.add_css_class("zenbuji-translation")
            box.append(tr)

        for note in result.notes:
            n = Gtk.Label(label=note, wrap=True, xalign=0)
            n.add_css_class("zenbuji-note")
            box.append(n)

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

    app.connect("activate", on_activate)
    return app.run([])
