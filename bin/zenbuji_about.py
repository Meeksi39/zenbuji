#!/usr/bin/env python3
"""GTK4 frosted-glass About window.

A small calm card: the zenbuji logo, a one-line tagline, the version, a short
"what it is" blurb, and footer links (project page) + Close. Built on the shared
glass scaffold like every other surface; all data (version, url, ui language) is
injected by `launch_about` in zenbuji/cli.py so this module stays self-contained.
"""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

try:
    from zenbuji_glass import accent_hex, make_glass_window
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zenbuji_glass import accent_hex, make_glass_window

# The wordmark+mascot logo lives in the repo's docs/ (source of truth; install.sh
# symlinks rather than copies, so it stays reachable relative to this module).
LOGO_PATH = Path(__file__).resolve().parent.parent / "docs" / "logo.png"

DEFAULT_URL = "https://github.com/Meeksi39/zenbuji"

ABOUT_STRINGS = {
    "title":    {"en": "About",              "ja": "情報"},
    "tagline":  {"en": "Furigana + English & German translation for Japanese, "
                       "anywhere on your screen.",
                 "ja": "画面のどこでも、日本語にふりがなと英語・ドイツ語訳を。"},
    "blurb":    {"en": "Offline-first and runs entirely on your own machine. "
                       "Look up a selection, OCR the screen, build a dictionary, "
                       "and practise with spaced repetition.",
                 "ja": "オフライン優先で、すべてご自身の端末で動作します。選択範囲の"
                       "辞書引き、画面OCR、辞書づくり、間隔反復での練習ができます。"},
    "version":  {"en": "Version {v}",        "ja": "バージョン {v}"},
    "devbuild": {"en": "Development build",   "ja": "開発ビルド"},
    "project":  {"en": "Project page",        "ja": "プロジェクトページ"},
    "close":    {"en": "Close",               "ja": "閉じる"},
    "madeby":   {"en": "Made for immersion learners.",
                 "ja": "イマージョン学習者のために。"},
}


def _make_tr(ui_language):
    def t(key, **kw):
        entry = ABOUT_STRINGS.get(key, {})
        s = entry.get(ui_language) or entry.get("en") or key
        return s.format(**kw) if kw else s
    return t


def _open_url(url):
    try:
        Gio.AppInfo.launch_default_for_uri(url, None)
    except GLib.Error:
        pass


def show_about(*, ui_language="en", version=None, url=DEFAULT_URL) -> int:
    t = _make_tr(ui_language)
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        win, card = make_glass_window(
            application, title="zenbuji 情報", default_size=(380, -1),
            resizable=False, draggable=True, close_on_focus_loss=False)

        # --- logo --------------------------------------------------------- //
        if LOGO_PATH.exists():
            logo = Gtk.Picture.new_for_filename(str(LOGO_PATH))
            logo.set_content_fit(Gtk.ContentFit.CONTAIN)
            logo.set_can_shrink(True)
            logo.set_size_request(300, 132)
            logo.set_halign(Gtk.Align.CENTER)
            logo.set_margin_top(4)
            logo.add_css_class("zenbuji-ocr-image")
            card.append(logo)
        else:
            # Fall back to a plain wordmark if the asset is missing.
            mark = Gtk.Label(label="zenbuji 〜 全部字", xalign=0.5)
            mark.add_css_class("zenbuji-title")
            card.append(mark)

        # --- tagline ------------------------------------------------------ //
        tagline = Gtk.Label(label=t("tagline"), wrap=True, justify=Gtk.Justification.CENTER)
        tagline.set_max_width_chars(34)
        tagline.set_halign(Gtk.Align.CENTER)
        tagline.set_margin_top(6)
        tagline.add_css_class("zenbuji-translation")
        card.append(tagline)

        # --- version ------------------------------------------------------ //
        ver_label = Gtk.Label(
            label=t("version", v=version) if version else t("devbuild"),
            xalign=0.5)
        ver_label.set_halign(Gtk.Align.CENTER)
        ver_label.set_margin_top(2)
        accent = accent_hex(Adw.StyleManager.get_default().get_dark())
        if accent:
            ver_label.set_markup(
                f'<span foreground="{accent}" weight="700">'
                f'{GLib.markup_escape_text(ver_label.get_text())}</span>')
        ver_label.add_css_class("zenbuji-meta")
        card.append(ver_label)

        # --- blurb -------------------------------------------------------- //
        blurb = Gtk.Label(label=t("blurb"), wrap=True, justify=Gtk.Justification.CENTER)
        blurb.set_max_width_chars(38)
        blurb.set_halign(Gtk.Align.CENTER)
        blurb.set_margin_top(12)
        blurb.add_css_class("zenbuji-note")
        card.append(blurb)

        made = Gtk.Label(label=t("madeby"), xalign=0.5)
        made.set_halign(Gtk.Align.CENTER)
        made.set_margin_top(8)
        made.add_css_class("zenbuji-meta")
        card.append(made)

        # --- footer ------------------------------------------------------- //
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                      homogeneous=True)
        row.set_margin_top(16)
        close = Gtk.Button(label=t("close"))
        close.add_css_class("zenbuji-secondary")
        close.connect("clicked", lambda _b: win.close())
        project = Gtk.Button(label=t("project"))
        project.add_css_class("zenbuji-action")
        project.connect("clicked", lambda _b: _open_url(url))
        row.append(close)
        row.append(project)
        card.append(row)

        win.present()

    app.connect("activate", on_activate)
    return app.run([])
