#!/usr/bin/env python3
"""Small shared GTK widgets + helpers used across the zenbuji windows
(dictionary, game overlay, and others). Keeps each window module slim and the
look consistent. The glass scaffold/CSS/tabs/footer live in `zenbuji_glass.py`;
this holds the tiny reusable atoms.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk  # noqa: E402

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


class DictItem(GObject.Object):
    """List-model wrapper for one dictionary entry: its key (surface word) + the
    live entry dict (mutated in place for the exclude flag)."""
    __gtype_name__ = "ZenbujiDictItem"

    def __init__(self, key, entry):
        super().__init__()
        self.key = key
        self.entry = entry


def make_card_gridview(model, build_cell, *, min_columns=1, max_columns=4):
    """A virtualized `Gtk.GridView` of cards: the factory builds each cell from
    ``build_cell(item)`` on bind and clears it on unbind. `model` is the
    selection model wrapping the (filtered/sorted) item list. Responsive columns."""
    factory = Gtk.SignalListItemFactory()
    factory.connect("bind", lambda _f, li: li.set_child(build_cell(li.get_item())))
    factory.connect("unbind", lambda _f, li: li.set_child(None))
    grid = Gtk.GridView(model=model, factory=factory)
    grid.add_css_class("zenbuji-dict-list")
    grid.set_hexpand(True)
    grid.set_min_columns(min_columns)
    grid.set_max_columns(max_columns)
    grid.set_enable_rubberband(False)
    grid.set_single_click_activate(False)
    return grid


def _hairline():
    h = Gtk.Box()
    h.add_css_class("zenbuji-hairline")
    return h


def scroll_with_edge_shadows(child, *, min_content_width=380):
    """Wrap a scrollable `child` (GridView/ListView) in a vertical box with top
    and bottom hairlines packed flush and inset edge shadows shown only when
    there's more content past that edge. Returns ``(box, scroll)`` — append
    `box` to the card. The shadows track the scroll's vertical adjustment."""
    scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroll.add_css_class("zenbuji-dict-scroll")
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_propagate_natural_width(False)
    scroll.set_min_content_width(min_content_width)
    scroll.set_child(child)

    overlay = Gtk.Overlay()
    overlay.set_vexpand(True)
    overlay.set_child(scroll)
    top = Gtk.Box()
    top.add_css_class("zenbuji-scroll-shadow-top")
    top.set_valign(Gtk.Align.START)
    top.set_can_target(False)
    top.set_visible(False)
    bot = Gtk.Box()
    bot.add_css_class("zenbuji-scroll-shadow-bottom")
    bot.set_valign(Gtk.Align.END)
    bot.set_can_target(False)
    bot.set_visible(False)
    overlay.add_overlay(top)
    overlay.add_overlay(bot)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    box.set_vexpand(True)
    box.set_hexpand(True)
    box.append(_hairline())
    box.append(overlay)
    box.append(_hairline())

    vadj = scroll.get_vadjustment()

    def _update(*_a):
        v, up, pg = vadj.get_value(), vadj.get_upper(), vadj.get_page_size()
        top.set_visible(v > 0.5)
        bot.set_visible(v < up - pg - 0.5)

    vadj.connect("value-changed", _update)
    vadj.connect("changed", _update)
    return box, scroll
