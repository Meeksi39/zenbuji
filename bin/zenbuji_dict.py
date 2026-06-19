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
    "read_aloud": {"en": "Read aloud",   "ja": "読み上げる"},
    "stats":      {"en": "Statistics",   "ja": "統計"},
    "edit":       {"en": "Edit translations", "ja": "翻訳を編集"},
    "save":       {"en": "Save",         "ja": "保存"},
    "cancel":     {"en": "Cancel",       "ja": "キャンセル"},
    "exclude":    {"en": "Exclude from practice", "ja": "練習から除外"},
    "excluded":   {"en": "Excluded from practice", "ja": "練習から除外中"},
    "first":      {"en": "first",        "ja": "初回"},
    "last":       {"en": "last",         "ja": "最終"},
    "due":        {"en": "due",          "ja": "次回"},
}

# SRS level labels, mirrored from srs_status() / zenbuji_learn.py.
STATUS_NAMES = {
    "en": {"new": "New", "learning": "Learning", "young": "Young", "mature": "Mature"},
    "ja": {"new": "新規", "learning": "学習中", "young": "定着中", "mature": "習得"},
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


def _spawn_stats():
    cli = str(Path(__file__).resolve().parent / "zenbuji.py")
    try:
        subprocess.Popen([sys.executable, cli, "stats"], start_new_session=True)
    except OSError:
        pass


def show_dictionary(*, ui_language="en", languages=("en", "de"),
                    load_fn, delete_fn, clear_fn, stats_fn,
                    refresh_fn=None, update_fn=None, set_exclude_fn=None,
                    watch_path=None, quota_fn=None, speak_fn=None) -> int:
    """Show the dictionary window. The *_fn callables provide the data layer.

    `update_fn(text, {lang: value})` corrects an entry's translations,
    `set_exclude_fn(text, bool)` toggles a word out of the practice quiz, and
    `watch_path` (the dictionary file) drives live auto-refresh so background
    OCR-adds show up in an already-open window.
    """
    t = _make_tr(ui_language)
    lang_names = LANG_NAMES_BY_UI.get(ui_language, LANG_NAMES_BY_UI["en"])
    status_names = STATUS_NAMES.get(ui_language, STATUS_NAMES["en"])
    # `editing` pauses auto-refresh so an external add can't wipe a half-typed
    # correction; the deferred refresh runs when the edit closes.
    state = {"editing": False, "pending": False, "token": 0, "monitors": []}
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
        stats_btn = Gtk.Button(label=t("stats"))
        stats_btn.add_css_class("zenbuji-secondary")
        stats_btn.set_valign(Gtk.Align.CENTER)
        stats_btn.set_tooltip_text(t("stats"))
        stats_btn.connect("clicked", lambda _b: _spawn_stats())
        clear_btn = Gtk.Button(label=t("clear_all"))
        clear_btn.add_css_class("zenbuji-secondary")
        clear_btn.add_css_class("zenbuji-icon-danger")  # destructive: red text
        clear_btn.set_valign(Gtk.Align.CENTER)
        header.append(title)
        header.append(stats_btn)
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

        def _langs_in(trans):
            return [*languages, *[l for l in trans if l not in languages]]

        def make_row(entry):
            text = entry.get("text", "")
            reading = entry.get("reading", "")
            trans = entry.get("translations", {})
            row = Gtk.ListBoxRow()
            row._haystack = " ".join([text, reading, *trans.values()]).lower()

            def _icon_btn(icon, key, cb, danger=False):
                b = Gtk.Button(icon_name=icon)
                b.add_css_class("flat")
                b.add_css_class("zenbuji-icon-danger" if danger else "zenbuji-icon")
                b.set_valign(Gtk.Align.CENTER)
                b.set_tooltip_text(t(key))
                b.connect("clicked", cb)
                return b

            def build_view():
                outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                outer.set_margin_top(8)
                outer.set_margin_bottom(8)
                outer.set_margin_start(6)
                outer.set_margin_end(6)
                if entry.get("exclude"):
                    outer.add_css_class("zenbuji-excluded")

                top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                jp = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
                jp.add_css_class("zenbuji-dict-jp")
                jp.set_hexpand(True)
                jp.set_max_width_chars(30)
                top.append(jp)
                srs = entry.get("srs") or {}
                level = srs.get("level")
                if level and not entry.get("exclude"):
                    badge = Gtk.Label(label=status_names.get(level, level))
                    badge.add_css_class("zenbuji-level")
                    badge.add_css_class(f"zenbuji-level-{level}")
                    badge.set_valign(Gtk.Align.CENTER)
                    top.append(badge)
                count = Gtk.Label(label=f"×{entry.get('count', 0)}")
                count.add_css_class("zenbuji-count")
                count.set_valign(Gtk.Align.CENTER)
                top.append(count)

                if speak_fn is not None:
                    top.append(_icon_btn(
                        "audio-volume-high-symbolic", "read_aloud",
                        lambda _b, r=(reading or text): speak_fn(r)))
                top.append(_icon_btn("accessories-dictionary-symbolic", "look_up",
                                     lambda _b, x=text: _spawn_popup(x)))
                if update_fn is not None:
                    top.append(_icon_btn("document-edit-symbolic", "edit",
                                         lambda _b: show_edit()))
                if refresh_fn is not None:
                    top.append(_icon_btn("view-refresh-symbolic", "refresh",
                                         lambda _b, x=text: do_refresh(x)))
                if set_exclude_fn is not None:
                    tog = Gtk.ToggleButton(icon_name="action-unavailable-symbolic")
                    tog.add_css_class("flat")
                    tog.add_css_class("zenbuji-icon")
                    tog.set_valign(Gtk.Align.CENTER)
                    tog.set_active(bool(entry.get("exclude")))
                    tog.set_tooltip_text(t("excluded") if entry.get("exclude")
                                         else t("exclude"))

                    def _on_tog(b, _outer=outer):
                        ex = b.get_active()
                        entry["exclude"] = ex
                        (_outer.add_css_class if ex else _outer.remove_css_class)(
                            "zenbuji-excluded")
                        b.set_tooltip_text(t("excluded") if ex else t("exclude"))
                        try:
                            set_exclude_fn(text, ex)
                        except Exception:  # noqa: BLE001
                            pass

                    tog.connect("toggled", _on_tog)
                    top.append(tog)
                top.append(_icon_btn("user-trash-symbolic", "delete",
                                     lambda _b, x=text: do_delete(x), danger=True))
                outer.append(top)

                if reading and reading != text:
                    rl = Gtk.Label(label=reading, xalign=0, wrap=True)
                    rl.add_css_class("zenbuji-reading")
                    rl.set_max_width_chars(40)
                    outer.append(rl)

                for lang in _langs_in(trans):
                    val = trans.get(lang)
                    if not val:
                        continue
                    line = Gtk.Label(
                        label=f"{lang_names.get(lang, lang.upper())}:  {val}",
                        xalign=0, wrap=True, selectable=True)
                    line.add_css_class("zenbuji-translation")
                    line.set_max_width_chars(40)
                    outer.append(line)

                meta_parts = [
                    f"{t('first')} {_short_dt(entry.get('first_seen', ''))}",
                    f"{t('last')} {_short_dt(entry.get('last_seen', ''))}",
                ]
                if srs:
                    if srs.get("due"):
                        meta_parts.append(f"{t('due')} {_short_dt(srs['due'])[:10]}")
                    if srs.get("correct") or srs.get("wrong"):
                        meta_parts.append(
                            f"✓{srs.get('correct', 0)} ✗{srs.get('wrong', 0)}")
                meta = Gtk.Label(label="   ·   ".join(meta_parts), xalign=0,
                                 wrap=True)
                meta.add_css_class("zenbuji-meta")
                meta.set_max_width_chars(44)
                outer.append(meta)
                return outer

            def build_edit():
                outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                outer.set_margin_top(8)
                outer.set_margin_bottom(8)
                outer.set_margin_start(6)
                outer.set_margin_end(6)
                head = Gtk.Label(label=f"{text}　{reading}" if reading else text,
                                 xalign=0, wrap=True)
                head.add_css_class("zenbuji-dict-jp")
                head.set_max_width_chars(40)
                outer.append(head)

                fields = {}
                for lang in _langs_in(trans):
                    e = Gtk.Entry(text=trans.get(lang, ""), hexpand=True)
                    e.set_placeholder_text(lang_names.get(lang, lang.upper()))
                    fields[lang] = e
                    outer.append(e)

                def on_save(*_a):
                    do_save(text, {l: w.get_text() for l, w in fields.items()})

                btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                               homogeneous=True)
                cancel_b = Gtk.Button(label=t("cancel"))
                cancel_b.add_css_class("zenbuji-secondary")
                cancel_b.connect("clicked", lambda _b: cancel_edit())
                save_b = Gtk.Button(label=t("save"))
                save_b.add_css_class("zenbuji-action")
                save_b.connect("clicked", on_save)
                for w in fields.values():
                    w.connect("activate", on_save)
                btns.append(cancel_b)
                btns.append(save_b)
                outer.append(btns)
                return outer

            def show_view():
                state["editing"] = False
                row.set_child(build_view())
                _run_pending()

            def show_edit():
                state["editing"] = True
                row.set_child(build_edit())

            def cancel_edit():
                show_view()

            row.set_child(build_view())
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

        def do_save(text, translations):
            state["editing"] = False
            if update_fn is not None:
                try:
                    update_fn(text, translations)
                except Exception:  # noqa: BLE001
                    pass
            state["pending"] = False
            rebuild()

        def _run_pending():
            if state["pending"] and not state["editing"]:
                state["pending"] = False
                rebuild()

        def schedule_rebuild():
            # Debounce a burst of file-monitor events into one rebuild, and hold
            # off entirely while the user is editing a row.
            if state["editing"]:
                state["pending"] = True
                return
            state["token"] += 1
            tok = state["token"]

            def fire():
                if tok == state["token"] and not state["editing"]:
                    rebuild()
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(300, fire)

        def setup_watch():
            if not watch_path:
                return
            try:
                gfile = Gio.File.new_for_path(str(watch_path))
                mon = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
                mon.connect("changed", lambda *_a: schedule_rebuild())
                state["monitors"].append(mon)  # keep a ref so it isn't GC'd
                return
            except Exception:  # noqa: BLE001  (fall back to polling)
                pass

            def _mtime():
                try:
                    return Path(watch_path).stat().st_mtime
                except OSError:
                    return 0

            last = {"m": _mtime()}

            def poll():
                m = _mtime()
                if m != last["m"]:
                    last["m"] = m
                    schedule_rebuild()
                return True

            GLib.timeout_add_seconds(2, poll)

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
        setup_watch()

    app.connect("activate", on_activate)
    return app.run([])
