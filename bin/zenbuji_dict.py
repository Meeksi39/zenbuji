#!/usr/bin/env python3
"""GTK4 frosted-glass window to browse the local dictionary.

Lists the DeepL translations zenbuji has cached, with per-entry usage count and
first/last-seen timestamps. Supports searching, sorting, filtering, deleting an
entry, clearing all, re-translating (a fresh DeepL call), inline editing, and
opening an entry back in the lookup popup. The list is a virtualized
`Gtk.GridView` so it scales to a large dictionary. All data access is injected
by `launch_dictionary` in zenbuji/cli.py, so this module stays storage-agnostic.

The game-helper overlay lives in `zenbuji_game.py`; shared UI atoms in
`zenbuji_widgets.py`; the glass scaffold in `zenbuji_glass.py`.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk  # noqa: E402

try:
    from zenbuji_glass import fmt_ms, make_glass_window, make_tabs
    from zenbuji_widgets import (LANG_NAMES_BY_UI, STATUS_NAMES, icon_button,
                                 langs_in, make_tr, short_dt, translation_lines)
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zenbuji_glass import fmt_ms, make_glass_window, make_tabs
    from zenbuji_widgets import (LANG_NAMES_BY_UI, STATUS_NAMES, icon_button,
                                 langs_in, make_tr, short_dt, translation_lines)


class DictItem(GObject.Object):
    """Wraps one dictionary entry for the virtualized list model. Holds the live
    entry dict (mutated in place for the exclude flag) and its key (surface word).
    """
    __gtype_name__ = "ZenbujiDictItem"

    def __init__(self, key, entry):
        super().__init__()
        self.key = key
        self.entry = entry


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
    "add_word":   {"en": "Add word",     "ja": "単語を追加"},
    "create":     {"en": "Create",       "ja": "作成"},
    "word":       {"en": "Word",         "ja": "単語"},
    "reading":    {"en": "Reading",      "ja": "読み"},
    "fill_reading": {"en": "Fill reading (offline)",
                     "ja": "読みを自動入力（オフライン）"},
    "exclude":    {"en": "Exclude from practice", "ja": "練習から除外"},
    "excluded":   {"en": "Excluded from practice", "ja": "練習から除外中"},
    "first":      {"en": "first",        "ja": "初回"},
    "last":       {"en": "last",         "ja": "最終"},
    "due":        {"en": "due",          "ja": "次回"},
    "avg":        {"en": "avg",          "ja": "平均"},
    # Header button → the review window, when caption words are waiting ({n} in code).
    "new_words":  {"en": "New words ({n})", "ja": "新着 ({n})"},
    # Sort orders (dropdown) + filter chips + the shown/total count.
    "sort_recent": {"en": "Recent",     "ja": "新しい順"},
    "sort_oldest": {"en": "Oldest",     "ja": "古い順"},
    "sort_alpha":  {"en": "A–Z",        "ja": "あいうえお順"},
    "sort_count":  {"en": "Most seen",  "ja": "回数順"},
    "sort_due":    {"en": "Due first",  "ja": "復習順"},
    "filt_all":          {"en": "All",          "ja": "すべて"},
    "filt_due":          {"en": "Due",          "ja": "復習"},
    "filt_untranslated": {"en": "Untranslated", "ja": "未翻訳"},
    "filt_excluded":     {"en": "Excluded",     "ja": "除外"},
    "count_shown": {"en": "{shown} / {total}", "ja": "{shown} / {total}"},
}


def _stats_text(stats, ui_language):
    e, lu, sv = stats["entries"], stats["lookups"], stats["saved"]
    if ui_language == "ja":
        return f"{e} 語 · {lu} 回検索 · {sv} 回キャッシュ利用"
    return f"{e} words · {lu} lookups · {sv} served from cache"


def _spawn(command, *args):
    cli = str(Path(__file__).resolve().parent / "zenbuji_main.py")
    try:
        subprocess.Popen([sys.executable, cli, command, *args],
                         start_new_session=True)
    except OSError:
        pass


# Sort orders + filter chips for the dictionary grid. Pure functions so the
# logic is unit-testable without GTK (the view just calls them via the model).
SORT_ORDERS = ("recent", "oldest", "alpha", "count", "due")
DICT_FILTERS = ("all", "due", "untranslated", "excluded")


def _is_due(srs) -> bool:
    due = (srs or {}).get("due")
    if not due:
        return False
    try:
        return datetime.fromisoformat(due).date() <= datetime.now().date()
    except (ValueError, TypeError):
        return False


def dict_sort_key(entry: dict, order: str):
    """An *ascending* comparable key for `order`. "recent" is sorted descending
    on this key (the only reversed order) — the view's comparator handles that."""
    text = entry.get("text", "")
    if order == "alpha":
        return (entry.get("reading") or text, text)
    if order == "count":            # most-seen first (negate so ascending works)
        return (-int(entry.get("count", 0)), entry.get("last_seen", ""))
    if order == "due":              # soonest due first, no-due entries last
        due = (entry.get("srs") or {}).get("due") or ""
        return (0 if due else 1, due, text)
    return (entry.get("last_seen", ""), text)   # recent (reversed) / oldest


def dict_matches(entry: dict, needle: str, filt: str) -> bool:
    """Whether `entry` passes the active filter chip AND the search needle."""
    if filt == "excluded" and not entry.get("exclude"):
        return False
    if filt == "untranslated" and any(
            (v or "").strip() for v in (entry.get("translations") or {}).values()):
        return False
    if filt == "due" and not _is_due(entry.get("srs")):
        return False
    if needle:
        hay = " ".join([entry.get("text", ""), entry.get("reading", ""),
                        *(entry.get("translations") or {}).values()]).lower()
        if needle not in hay:
            return False
    return True


def show_dictionary(*, ui_language="en", languages=("en", "de"),
                    load_fn, delete_fn, clear_fn, stats_fn,
                    refresh_fn=None, save_fn=None, analyze_fn=None,
                    set_exclude_fn=None, watch_path=None, quota_fn=None,
                    speak_fn=None, captured_count_fn=None) -> int:
    """Show the dictionary window. The *_fn callables provide the data layer.

    `save_fn(text, reading, {lang: value}, original=None)` creates or edits an
    entry by hand (no lookup) — it backs both the "Add word" form and the inline
    editor (which can also fix the reading and rename the surface word; pass the
    old key as `original`). `analyze_fn(text)->reading` optionally fills the
    reading offline. `set_exclude_fn(text, bool)` toggles a word out of the
    practice quiz, and `watch_path` (the dictionary file) drives live
    auto-refresh so background OCR-adds show up in an already-open window.
    `captured_count_fn() -> int` is how many words are waiting in the review
    window; when > 0 a "New words (N)" header button appears that opens it.
    """
    t = make_tr(DICT_STRINGS, ui_language)
    lang_names = LANG_NAMES_BY_UI.get(ui_language, LANG_NAMES_BY_UI["en"])
    status_names = STATUS_NAMES.get(ui_language, STATUS_NAMES["en"])
    # `editing` pauses auto-refresh so an external add can't wipe a half-typed
    # correction; the deferred refresh runs when the edit closes.
    state = {"editing": False, "editing_key": None, "pending": False,
             "token": 0, "monitors": [], "sort": "recent", "filter": "all",
             "items_by_key": {}, "search_token": 0}
    # NON_UNIQUE so this can run alongside an open popup (same app-id, kept for
    # the Blur My Shell whitelist).
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def _icon_btn(icon, key, cb, danger=False):
        return icon_button(icon, t(key), cb, danger=danger)

    def on_activate(application):
        win, card = make_glass_window(
            application, title="zenbuji 辞書", default_size=(940, 720),
            resizable=True, draggable=True, close_on_focus_loss=False)

        def make_reading_field(get_surface, value=""):
            """A reading entry fused with an optional offline-fill (↻) button.
            `get_surface()` supplies the text to analyse. Returns (row, entry)."""
            entry = Gtk.Entry(text=value, hexpand=True)
            entry.set_placeholder_text(t("reading"))
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.append(entry)
            if analyze_fn is not None:
                fill = Gtk.Button(icon_name="view-refresh-symbolic")
                fill.add_css_class("flat")
                fill.add_css_class("zenbuji-icon")
                fill.set_valign(Gtk.Align.CENTER)
                fill.set_tooltip_text(t("fill_reading"))

                def do_fill(_b):
                    surface = (get_surface() or "").strip()
                    if surface:
                        try:
                            entry.set_text(analyze_fn(surface) or "")
                        except Exception:  # noqa: BLE001 — fill is best-effort
                            pass

                fill.connect("clicked", do_fill)
                row.append(fill)
            return row, entry

        # --- Header: title + (new words) + add + stats -------------------- //
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=t("title"), xalign=0)
        title.add_css_class("zenbuji-title")
        title.set_hexpand(True)
        header.append(title)
        # When caption-captured words are waiting, a button to the review window.
        _new_n = 0
        if captured_count_fn is not None:
            try:
                _new_n = int(captured_count_fn() or 0)
            except Exception:  # noqa: BLE001
                _new_n = 0
        if _new_n > 0:
            new_btn = Gtk.Button(label=t("new_words", n=_new_n))
            new_btn.add_css_class("zenbuji-secondary")
            new_btn.add_css_class("zenbuji-small")
            new_btn.set_valign(Gtk.Align.CENTER)
            new_btn.set_tooltip_text(t("new_words", n=_new_n))
            new_btn.connect("clicked", lambda _b: _spawn("review"))
            header.append(new_btn)
        if save_fn is not None:
            add_btn = Gtk.Button(label=t("add_word"))
            add_btn.add_css_class("zenbuji-secondary")
            add_btn.add_css_class("zenbuji-small")
            add_btn.set_valign(Gtk.Align.CENTER)
            add_btn.set_tooltip_text(t("add_word"))
            add_btn.connect("clicked", lambda _b: toggle_add_form())
            header.append(add_btn)
        stats_btn = Gtk.Button(label=t("stats"))
        stats_btn.add_css_class("zenbuji-secondary")
        stats_btn.add_css_class("zenbuji-small")
        stats_btn.set_valign(Gtk.Align.CENTER)
        stats_btn.set_tooltip_text(t("stats"))
        stats_btn.connect("clicked", lambda _b: _spawn("stats"))
        header.append(stats_btn)
        # Destructive: kept out of the header, tucked into the footer below.
        clear_btn = Gtk.Button(label=t("clear_all"))
        clear_btn.add_css_class("zenbuji-secondary")
        clear_btn.add_css_class("zenbuji-small")
        clear_btn.add_css_class("zenbuji-icon-danger")
        clear_btn.set_valign(Gtk.Align.CENTER)
        card.append(header)

        # The "Add word" form lives just under the header, hidden until shown.
        add_form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_form.add_css_class("zenbuji-add-form")
        add_form.set_visible(False)
        card.append(add_form)

        def close_add_form():
            child = add_form.get_first_child()
            while child is not None:
                add_form.remove(child)
                child = add_form.get_first_child()
            add_form.set_visible(False)
            state["editing"] = False
            _run_pending()

        def toggle_add_form():
            if add_form.get_visible():
                close_add_form()
                return
            state["editing"] = True
            word = Gtk.Entry(hexpand=True)
            word.set_placeholder_text(t("word"))
            add_form.append(word)
            reading_row, reading = make_reading_field(word.get_text)
            add_form.append(reading_row)
            fields = {}
            for lang in languages:
                e = Gtk.Entry(hexpand=True)
                e.set_placeholder_text(lang_names.get(lang, lang.upper()))
                fields[lang] = e
                add_form.append(e)

            def do_create(*_a):
                surface = word.get_text().strip()
                if not surface or save_fn is None:
                    return
                try:
                    save_fn(surface, reading.get_text(),
                            {l: w.get_text() for l, w in fields.items()})
                except Exception:  # noqa: BLE001
                    pass
                close_add_form()
                refresh_list()

            btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                           homogeneous=True)
            cancel_b = Gtk.Button(label=t("cancel"))
            cancel_b.add_css_class("zenbuji-secondary")
            cancel_b.connect("clicked", lambda _b: close_add_form())
            create_b = Gtk.Button(label=t("create"))
            create_b.add_css_class("zenbuji-action")
            create_b.connect("clicked", do_create)
            for w in [word, reading, *fields.values()]:
                w.connect("activate", do_create)
            btns.append(cancel_b)
            btns.append(create_b)
            add_form.append(btns)
            rule = Gtk.Box()
            rule.add_css_class("zenbuji-hairline")
            rule.set_margin_top(6)
            add_form.append(rule)
            add_form.set_visible(True)
            word.grab_focus()

        stats_label = Gtk.Label(xalign=0, wrap=True)
        stats_label.add_css_class("zenbuji-quota")
        stats_label.set_max_width_chars(44)
        card.append(stats_label)

        quota_label = Gtk.Label(xalign=0, wrap=True)
        quota_label.add_css_class("zenbuji-quota")
        quota_label.set_max_width_chars(44)
        quota_label.set_visible(False)
        card.append(quota_label)

        # --- search + sort dropdown + filter chips + count ----------------- //
        search = Gtk.SearchEntry(hexpand=True)
        search.set_placeholder_text(t("search"))
        sort_keys = ["recent", "oldest", "alpha", "count", "due"]
        filt_keys = ["all", "due", "untranslated", "excluded"]

        sort_dd = Gtk.DropDown.new_from_strings([t(f"sort_{k}") for k in sort_keys])
        sort_dd.add_css_class("zenbuji-dropdown")
        sort_dd.set_valign(Gtk.Align.CENTER)
        srow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        srow.append(search)
        srow.append(sort_dd)
        card.append(srow)

        tabs_box, _filt_tabs = make_tabs(
            [(k, t(f"filt_{k}")) for k in filt_keys],
            lambda name: _set_filter(name))
        tabs_box.set_hexpand(True)
        count_lbl = Gtk.Label(xalign=1)
        count_lbl.add_css_class("zenbuji-meta")
        count_lbl.set_valign(Gtk.Align.CENTER)
        chips_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        chips_row.set_margin_top(2)
        chips_row.append(tabs_box)
        chips_row.append(count_lbl)
        card.append(chips_row)

        hairline = Gtk.Box()
        hairline.add_css_class("zenbuji-hairline")
        card.append(hairline)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add_css_class("zenbuji-dict-scroll")
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_width(False)
        scroll.set_min_content_width(380)

        dict_store = Gio.ListStore(item_type=DictItem)

        def _sort_cmp(a, b, _u=None):
            order = state["sort"]
            ka, kb = dict_sort_key(a.entry, order), dict_sort_key(b.entry, order)
            if order == "recent":
                ka, kb = kb, ka              # newest first
            return (ka > kb) - (ka < kb)

        def _filt(item, _u=None):
            return dict_matches(item.entry, search.get_text().strip().lower(),
                                state["filter"])

        dict_sorter = Gtk.CustomSorter.new(_sort_cmp)
        dict_filter = Gtk.CustomFilter.new(_filt)
        sorted_model = Gtk.SortListModel(model=dict_store, sorter=dict_sorter)
        filter_model = Gtk.FilterListModel(model=sorted_model, filter=dict_filter)
        factory = Gtk.SignalListItemFactory()
        factory.connect(
            "bind", lambda _f, li: li.set_child(build_dict_item(li.get_item())))
        factory.connect("unbind", lambda _f, li: li.set_child(None))
        gridview = Gtk.GridView(model=Gtk.NoSelection(model=filter_model),
                                factory=factory)
        gridview.add_css_class("zenbuji-dict-list")
        gridview.set_min_columns(1)
        gridview.set_max_columns(4)
        gridview.set_enable_rubberband(False)
        gridview.set_single_click_activate(False)
        scroll.set_child(gridview)
        card.append(scroll)
        # GridView has no placeholder; an empty-state label toggled below.
        empty_label = Gtk.Label(label=t("empty"), xalign=0.5, wrap=True)
        empty_label.add_css_class("zenbuji-note")
        empty_label.set_margin_top(18)
        empty_label.set_halign(Gtk.Align.CENTER)
        empty_label.set_visible(False)
        card.append(empty_label)

        def _update_count():
            count_lbl.set_text(t("count_shown").format(
                shown=filter_model.get_n_items(), total=dict_store.get_n_items()))

        filter_model.connect("items-changed", lambda *_a: _update_count())

        def _set_filter(name):
            state["filter"] = name
            dict_filter.changed(Gtk.FilterChange.DIFFERENT)

        def _on_sort(dd, _p):
            state["sort"] = sort_keys[dd.get_selected()]
            dict_sorter.changed(Gtk.SorterChange.DIFFERENT)

        sort_dd.connect("notify::selected", _on_sort)

        def _do_search(_s):
            state["search_token"] += 1
            tok = state["search_token"]

            def fire():
                if win.get_mapped() and tok == state["search_token"]:
                    dict_filter.changed(Gtk.FilterChange.DIFFERENT)
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(120, fire)

        search.connect("search-changed", _do_search)

        # Footer: the destructive "Clear all", away from the everyday actions.
        foot_rule = Gtk.Box()
        foot_rule.add_css_class("zenbuji-hairline")
        card.append(foot_rule)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_halign(Gtk.Align.END)
        footer.set_margin_top(6)
        footer.append(clear_btn)
        card.append(footer)

        def build_dict_item(item):
            # Full editable row, rebuilt on bind (only for visible cells), so
            # handlers close over the current item with no stale state. The
            # view<->edit swap lives in `holder`, keyed on state["editing_key"]
            # so an edited row re-enters edit on rebind.
            entry = item.entry
            text = item.key
            reading = entry.get("reading", "")
            trans = entry.get("translations", {})
            holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            holder.add_css_class("zenbuji-dict-card")   # grid cell card

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
                                     lambda _b, x=text: _spawn("popup", x)))
                if save_fn is not None:
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

                for line in translation_lines(trans, languages, lang_names,
                                              max_chars=40):
                    outer.append(line)

                meta_parts = [
                    f"{t('first')} {short_dt(entry.get('first_seen', ''))}",
                    f"{t('last')} {short_dt(entry.get('last_seen', ''))}",
                ]
                if srs:
                    if srs.get("due"):
                        meta_parts.append(f"{t('due')} {short_dt(srs['due'])[:10]}")
                    if srs.get("correct") or srs.get("wrong"):
                        meta_parts.append(
                            f"✓{srs.get('correct', 0)} ✗{srs.get('wrong', 0)}")
                    if srs.get("avg_ms"):
                        meta_parts.append(f"{t('avg')} {fmt_ms(srs['avg_ms'])}")
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
                surface_entry = Gtk.Entry(text=text, hexpand=True)
                surface_entry.set_placeholder_text(t("word"))
                outer.append(surface_entry)
                reading_row, reading_entry = make_reading_field(
                    lambda: surface_entry.get_text() or text, value=reading)
                outer.append(reading_row)
                fields = {}
                for lang in languages:
                    e = Gtk.Entry(text=trans.get(lang, ""), hexpand=True)
                    e.set_placeholder_text(lang_names.get(lang, lang.upper()))
                    fields[lang] = e
                    outer.append(e)

                def on_save(*_a):
                    do_save(surface_entry.get_text(),
                            {l: w.get_text() for l, w in fields.items()},
                            reading=reading_entry.get_text(), original=text)

                btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                               homogeneous=True)
                cancel_b = Gtk.Button(label=t("cancel"))
                cancel_b.add_css_class("zenbuji-secondary")
                cancel_b.connect("clicked", lambda _b: cancel_edit())
                save_b = Gtk.Button(label=t("save"))
                save_b.add_css_class("zenbuji-action")
                save_b.connect("clicked", on_save)
                for w in [surface_entry, reading_entry, *fields.values()]:
                    w.connect("activate", on_save)
                btns.append(cancel_b)
                btns.append(save_b)
                outer.append(btns)
                return outer

            def _swap(child):
                old = holder.get_first_child()
                if old is not None:
                    holder.remove(old)
                holder.append(child)

            def show_view():
                _swap(build_view())

            def show_edit():
                state["editing"] = True
                state["editing_key"] = item.key
                _swap(build_edit())

            def cancel_edit():
                state["editing"] = False
                state["editing_key"] = None
                _run_pending()
                show_view()

            if state.get("editing_key") == item.key:
                show_edit()
            else:
                show_view()
            return holder

        def repopulate():
            # Update the model incrementally — remove gone keys, append new ones,
            # refresh existing entries in place — then let the sort/filter models
            # re-evaluate. No full reallocation, so scroll position survives a
            # background add. (GridView realizes only visible cells regardless.)
            data = load_fn()
            by_key = state["items_by_key"]
            if not data:
                dict_store.remove_all()
                by_key.clear()
            else:
                for k in [k for k in by_key if k not in data]:
                    ok, pos = dict_store.find(by_key[k])
                    if ok:
                        dict_store.remove(pos)
                    by_key.pop(k, None)
                added = []
                for k, e in data.items():
                    it = by_key.get(k)
                    if it is None:
                        it = DictItem(k, e)
                        by_key[k] = it
                        added.append(it)
                    else:
                        it.entry = e          # refresh in place (count/srs/etc.)
                for it in added:
                    dict_store.append(it)
                dict_sorter.changed(Gtk.SorterChange.DIFFERENT)
                dict_filter.changed(Gtk.FilterChange.DIFFERENT)
            empty_label.set_visible(not data)
            stats_label.set_text(_stats_text(stats_fn(), ui_language))

        def refresh_list():
            repopulate()

        def do_delete(text):
            delete_fn(text)
            refresh_list()

        def do_save(text, translations, reading=None, original=None):
            state["editing"] = False
            state["editing_key"] = None
            try:
                if save_fn is not None:
                    save_fn(text, reading or "", translations, original=original)
            except Exception:  # noqa: BLE001
                pass
            state["pending"] = False
            refresh_list()

        def _run_pending():
            if state["pending"] and not state["editing"]:
                state["pending"] = False
                refresh_list()

        def schedule_rebuild():
            # Debounce a burst of file-monitor events into one refresh, and hold
            # off entirely while the user is editing a row.
            if state["editing"]:
                state["pending"] = True
                return
            state["token"] += 1
            tok = state["token"]

            def fire():
                if not win.get_mapped():
                    return GLib.SOURCE_REMOVE
                if tok == state["token"] and not state["editing"]:
                    refresh_list()
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(300, fire)

        def setup_watch():
            if not watch_path:
                return

            def _mtime():
                try:
                    return Path(watch_path).stat().st_mtime
                except OSError:
                    return 0

            try:
                gfile = Gio.File.new_for_path(str(watch_path))
                mon = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
                mon.connect("changed", lambda *_a: schedule_rebuild())
                state["monitors"].append(mon)  # keep a ref so it isn't GC'd
            except Exception:  # noqa: BLE001
                pass

            # ...plus an mtime poll as a reliable backstop (file monitors can
            # silently miss writes on some setups). Coalesced by the debounce.
            last = {"m": _mtime()}

            def poll():
                if not win.get_mapped():
                    return GLib.SOURCE_REMOVE
                m = _mtime()
                if m != last["m"]:
                    last["m"] = m
                    schedule_rebuild()
                return True

            GLib.timeout_add(1000, poll)

        def do_refresh(text):
            if refresh_fn is None:
                return
            targets = list(languages)

            def work():
                try:
                    refresh_fn(text, targets)
                except Exception:  # noqa: BLE001
                    pass
                GLib.idle_add(lambda: (refresh_list() if win.get_mapped() else None,
                                       GLib.SOURCE_REMOVE)[1])

            threading.Thread(target=work, daemon=True).start()

        def do_clear(_b):
            clear_fn()
            refresh_list()

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

        refresh_list()
        win.present()
        refresh_quota()
        setup_watch()

    app.connect("activate", on_activate)
    return app.run([])
