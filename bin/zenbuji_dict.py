#!/usr/bin/env python3
"""GTK4 frosted-glass window to browse the local dictionary.

Lists the DeepL translations zenbuji has cached, with per-entry usage count and
first/last-seen timestamps (progress). Supports searching, deleting an entry,
clearing all, re-translating (a fresh DeepL call), and opening an entry back in
the lookup popup. All dictionary data access is injected by the caller
(`launch_dictionary` in zenbuji.py), so this module stays storage-agnostic.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

try:
    from zenbuji_glass import make_glass_window
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zenbuji_glass import make_glass_window

LANG_NAMES_BY_UI = {
    "en": {"en": "English", "de": "Deutsch", "ja": "日本語"},
    "ja": {"en": "英語", "de": "ドイツ語", "ja": "日本語"},
}

DICT_STRINGS = {
    "title":      {"en": "Dictionary",   "ja": "辞書"},
    "search":     {"en": "Search…",      "ja": "検索…"},
    "clear_all":  {"en": "Clear all",    "ja": "すべて消去"},
    "empty":      {"en": "No cached translations yet.",
                   "ja": "キャッシュされた翻訳はまだありません。"},
    "delete":     {"en": "Delete",       "ja": "削除"},
    "refresh":    {"en": "Re-translate (DeepL)", "ja": "再翻訳（DeepL）"},
    "look_up":    {"en": "Look up",      "ja": "調べる"},
    "first":      {"en": "first",        "ja": "初回"},
    "last":       {"en": "last",         "ja": "最終"},
}


def _make_tr(ui_language):
    def t(key):
        entry = DICT_STRINGS.get(key, {})
        return entry.get(ui_language) or entry.get("en") or key
    return t


def _stats_text(stats, ui_language):
    e, lu, sv = stats["entries"], stats["lookups"], stats["saved"]
    if ui_language == "ja":
        return f"{e} 語 · {lu} 回検索 · {sv} 回キャッシュ利用"
    return f"{e} words · {lu} lookups · {sv} served from cache"


def _short_dt(iso: str) -> str:
    """'2026-06-17T12:30:00' → '2026-06-17 12:30'."""
    if not iso:
        return "—"
    return iso.replace("T", " ")[:16]


def _spawn_popup(text: str):
    cli = str(Path(__file__).resolve().parent / "zenbuji.py")
    try:
        subprocess.Popen([sys.executable, cli, "popup", text],
                         start_new_session=True)
    except OSError:
        pass


def show_dictionary(*, ui_language="en", languages=("en", "de"),
                    load_fn, delete_fn, clear_fn, stats_fn,
                    refresh_fn=None, quota_fn=None) -> int:
    """Show the dictionary window. The *_fn callables provide the data layer."""
    t = _make_tr(ui_language)
    lang_names = LANG_NAMES_BY_UI.get(ui_language, LANG_NAMES_BY_UI["en"])
    # NON_UNIQUE so this can run alongside an open popup (same app-id, kept for
    # the Blur My Shell whitelist).
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        win, card = make_glass_window(
            application, title="zenbuji 辞書", default_size=(500, 640),
            resizable=True, draggable=True, close_on_focus_loss=False)

        # --- Header: title + stats + clear-all ---------------------------- //
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=t("title"), xalign=0)
        title.add_css_class("zenbuji-title")
        title.set_hexpand(True)
        clear_btn = Gtk.Button(label=t("clear_all"))
        clear_btn.add_css_class("flat")
        clear_btn.set_valign(Gtk.Align.CENTER)
        header.append(title)
        header.append(clear_btn)
        card.append(header)

        stats_label = Gtk.Label(xalign=0, wrap=True)
        stats_label.add_css_class("zenbuji-quota")
        stats_label.set_max_width_chars(44)
        card.append(stats_label)

        quota_label = Gtk.Label(xalign=0, wrap=True)
        quota_label.add_css_class("zenbuji-quota")
        quota_label.set_max_width_chars(44)
        quota_label.set_visible(False)
        card.append(quota_label)

        search = Gtk.SearchEntry(hexpand=True)
        search.set_placeholder_text(t("search"))
        card.append(search)

        hairline = Gtk.Box()
        hairline.add_css_class("zenbuji-hairline")
        card.append(hairline)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add_css_class("zenbuji-dict-scroll")
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # Don't let a long entry stretch the window; rows wrap instead.
        scroll.set_propagate_natural_width(False)
        scroll.set_min_content_width(380)
        listbox = Gtk.ListBox()
        listbox.add_css_class("zenbuji-dict-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.set_child(listbox)
        card.append(scroll)

        empty_label = Gtk.Label(label=t("empty"), xalign=0)
        empty_label.add_css_class("zenbuji-note")
        # Shown automatically by GtkListBox whenever there are no rows.
        listbox.set_placeholder(empty_label)

        # --- Search filtering --------------------------------------------- //
        def filter_func(row):
            needle = search.get_text().strip().lower()
            return needle in getattr(row, "_haystack", "") if needle else True

        listbox.set_filter_func(filter_func)
        search.connect("search-changed", lambda _s: listbox.invalidate_filter())

        def make_row(entry):
            text = entry.get("text", "")
            row = Gtk.ListBoxRow()
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            outer.set_margin_top(8)
            outer.set_margin_bottom(8)
            outer.set_margin_start(6)
            outer.set_margin_end(6)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            jp = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
            jp.add_css_class("zenbuji-dict-jp")
            jp.set_hexpand(True)
            jp.set_max_width_chars(30)
            top.append(jp)
            count = Gtk.Label(label=f"×{entry.get('count', 0)}")
            count.add_css_class("zenbuji-count")
            count.set_valign(Gtk.Align.CENTER)
            top.append(count)
            for icon, key, cb in (
                ("accessories-dictionary-symbolic", "look_up",
                 lambda _b, x=text: _spawn_popup(x)),
                ("view-refresh-symbolic", "refresh",
                 lambda _b, x=text: do_refresh(x)),
                ("user-trash-symbolic", "delete",
                 lambda _b, x=text: do_delete(x)),
            ):
                if key == "refresh" and refresh_fn is None:
                    continue
                b = Gtk.Button(icon_name=icon)
                b.add_css_class("flat")
                b.set_valign(Gtk.Align.CENTER)
                b.set_tooltip_text(t(key))
                b.connect("clicked", cb)
                top.append(b)
            outer.append(top)

            reading = entry.get("reading", "")
            if reading and reading != text:
                rl = Gtk.Label(label=reading, xalign=0, wrap=True)
                rl.add_css_class("zenbuji-reading")
                rl.set_max_width_chars(40)
                outer.append(rl)

            trans = entry.get("translations", {})
            for lang in [*languages, *[l for l in trans if l not in languages]]:
                val = trans.get(lang)
                if not val:
                    continue
                line = Gtk.Label(
                    label=f"{lang_names.get(lang, lang.upper())}:  {val}",
                    xalign=0, wrap=True, selectable=True)
                line.add_css_class("zenbuji-translation")
                line.set_max_width_chars(40)
                outer.append(line)

            meta = Gtk.Label(
                label=f"{t('first')} {_short_dt(entry.get('first_seen', ''))}   ·   "
                      f"{t('last')} {_short_dt(entry.get('last_seen', ''))}",
                xalign=0)
            meta.add_css_class("zenbuji-meta")
            outer.append(meta)

            row.set_child(outer)
            hay = " ".join([text, reading, *trans.values()]).lower()
            row._haystack = hay
            return row

        def rebuild():
            listbox.remove_all()
            data = load_fn()
            entries = sorted(data.values(),
                             key=lambda e: e.get("last_seen", ""), reverse=True)
            for e in entries:
                listbox.append(make_row(e))
            stats_label.set_text(_stats_text(stats_fn(), ui_language))
            listbox.invalidate_filter()

        def do_delete(text):
            delete_fn(text)
            rebuild()

        def do_refresh(text):
            if refresh_fn is None:
                return
            targets = list(languages)

            def work():
                try:
                    refresh_fn(text, targets)
                except Exception:  # noqa: BLE001
                    pass
                GLib.idle_add(rebuild)

            threading.Thread(target=work, daemon=True).start()

        def do_clear(_b):
            clear_fn()
            rebuild()

        clear_btn.connect("clicked", do_clear)

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
                quota_label.set_text(
                    f"DeepL  {used:,} / {limit:,}  ({max(0, limit - used):,} left)")
                quota_label.set_visible(True)
            else:
                quota_label.set_visible(False)
            return GLib.SOURCE_REMOVE

        rebuild()
        win.present()
        refresh_quota()

    app.connect("activate", on_activate)
    return app.run([])
