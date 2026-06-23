#!/usr/bin/env python3
"""Small shared GTK widgets + helpers used across the zenbuji windows
(dictionary, game overlay, and others). Keeps each window module slim and the
look consistent. The glass scaffold/CSS/tabs/footer live in `zenbuji_glass.py`;
this holds the tiny reusable atoms.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

# Target-language names shown in the UI language.
LANG_NAMES_BY_UI = {
    "en": {"en": "English", "de": "Deutsch", "ja": "日本語"},
    "ja": {"en": "英語", "de": "ドイツ語", "ja": "日本語"},
}

# SRS level labels, mirrored from srs_status() / zenbuji_learn.py.
STATUS_NAMES = {
    "en": {"new": "New", "learning": "Learning", "young": "Young", "mature": "Mature"},
    "ja": {"new": "新規", "learning": "学習中", "young": "定着中", "mature": "習得"},
}


def make_tr(strings, ui_language):
    """A translator closure over a ``{key: {lang: text}}`` map (falls back to en).
    Callable as ``t(key)`` or ``t(key, n=…)`` for ``{…}`` placeholders."""
    def t(key, **kw):
        entry = strings.get(key, {})
        s = entry.get(ui_language) or entry.get("en") or key
        return s.format(**kw) if kw else s
    return t


def icon_button(icon, tooltip, on_click, *, danger=False):
    """A flat symbolic icon button in the shared glass style (neutral, accent on
    hover; red when destructive)."""
    b = Gtk.Button(icon_name=icon)
    b.add_css_class("flat")
    b.add_css_class("zenbuji-icon-danger" if danger else "zenbuji-icon")
    b.set_valign(Gtk.Align.CENTER)
    if tooltip:
        b.set_tooltip_text(tooltip)
    b.connect("clicked", on_click)
    return b


def langs_in(languages, trans):
    """The configured languages first, then any extra languages present in
    `trans` (so unexpected target languages still show)."""
    return [*languages, *[l for l in trans if l not in languages]]


def short_dt(iso: str) -> str:
    """'2026-06-17T12:30:00' → '2026-06-17 12:30'."""
    if not iso:
        return "—"
    return iso.replace("T", " ")[:16]


def translation_lines(trans, languages, lang_names, max_chars=36):
    """A `.zenbuji-translation` label per non-empty translation, in language
    order. Used by both the dict row and the game card."""
    out = []
    for lang in langs_in(languages, trans):
        val = trans.get(lang)
        if not val:
            continue
        line = Gtk.Label(label=f"{lang_names.get(lang, lang.upper())}:  {val}",
                         xalign=0, wrap=True, selectable=True)
        line.add_css_class("zenbuji-translation")
        line.set_max_width_chars(max_chars)
        out.append(line)
    return out
