#!/usr/bin/env python3
"""GTK4 frosted-glass window to review words captured from YouTube captions.

Two tabs: **New** (words staged from captions, not yet added or ignored) and
**Ignored** (words you've set aside). Adding or ignoring a word removes it from
the list *immediately* — no graying-out, no waiting — while the translation runs
in the background behind one shared progress indicator. If an add fails (e.g. no
translation backend reachable) the row slides back in with a warning so you can
retry. Ignored words can be restored. All data access is injected by
`launch_review` in zenbuji/cli.py, so this module stays storage-agnostic.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

try:
    from zenbuji_glass import make_footer, make_glass_window, make_tabs
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zenbuji_glass import make_footer, make_glass_window, make_tabs

REVIEW_STRINGS = {
    "title":        {"en": "New words from videos",
                     "ja": "動画で見つけた新しい単語"},
    "tab_new":      {"en": "New ({n})",      "ja": "新着 ({n})"},
    "tab_ignored":  {"en": "Ignored ({m})",  "ja": "無視 ({m})"},
    "add":          {"en": "Add",            "ja": "追加"},
    "ignore":       {"en": "Ignore",         "ja": "無視"},
    "restore":      {"en": "Restore",        "ja": "戻す"},
    "add_all":      {"en": "Add all",        "ja": "すべて追加"},
    "ignore_all":   {"en": "Ignore all",     "ja": "すべて無視"},
    "restore_all":  {"en": "Restore all",    "ja": "すべて戻す"},
    "close":        {"en": "Close",          "ja": "閉じる"},
    "adding":       {"en": "Adding {n}…", "ja": "{n} 件を追加中…"},
    "add_failed":   {"en": "couldn't add — retry",
                     "ja": "追加できませんでした（再試行）"},
    "empty_new":    {"en": "No new words right now — capture some from "
                           "YouTube captions.",
                     "ja": "新着の単語はありません。YouTubeの字幕から取り込んでください。"},
    "empty_ignored": {"en": "Nothing ignored.", "ja": "無視した単語はありません。"},
}


def _make_tr(ui_language):
    def t(key, **kw):
        entry = REVIEW_STRINGS.get(key, {})
        s = entry.get(ui_language) or entry.get("en") or key
        return s.format(**kw) if kw else s
    return t


def show_review(*, ui_language="en", languages=("en", "de"),
                new_fn, ignored_fn, add_fn, ignore_fn, unignore_fn) -> int:
    """Show the review window.

    `new_fn()` / `ignored_fn()` return ``[{lemma, reading, sample, count}]``.
    `add_fn(word) -> bool` translates + stores (True iff it's now in the dict).
    `ignore_fn(word)` / `unignore_fn(word)` move a word in/out of the ignore list.
    """
    t = _make_tr(ui_language)
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        win, card = make_glass_window(
            application, title="zenbuji 新着", default_size=(460, 560),
            resizable=True, draggable=True, close_on_focus_loss=False)

        # Window-owned model: each record carries its widget + a stable capture
        # index (`idx`) so a failed add re-inserts at the right spot. Mutated
        # only on the GTK main thread.
        state = {"anims": [], "inflight": 0, "active": "new"}
        new_records, ignored_records = [], []

        def _seed(records, items):
            for i, w in enumerate(items):
                records.append({
                    "lemma": w.get("lemma", ""), "reading": w.get("reading", ""),
                    "sample": w.get("sample", ""), "count": w.get("count", 0),
                    "idx": i, "row": None, "failed": False})

        _seed(new_records, list(new_fn() or []))
        # Ignored keep their own idx space (offset so restores still sort sanely).
        _seed(ignored_records, list(ignored_fn() or []))

        # --- animation primitives (eased; refs kept so they don't get GC'd) -- //
        def _fade(widget, frm, to, dur=240, easing=None):
            widget.set_opacity(frm)
            tgt = Adw.CallbackAnimationTarget.new(widget.set_opacity)
            anim = Adw.TimedAnimation.new(widget, frm, to, dur, tgt)
            anim.set_easing(easing or Adw.Easing.EASE_OUT_CUBIC)
            state["anims"].append(anim)
            anim.play()

        def _slide_margin(widget, frm, to, dur, set_margin,
                          easing=Adw.Easing.EASE_OUT_CUBIC):
            set_margin(max(0, int(round(frm))))
            tgt = Adw.CallbackAnimationTarget.new(
                lambda v: set_margin(max(0, int(round(v)))))
            anim = Adw.TimedAnimation.new(widget, frm, to, dur, tgt)
            anim.set_easing(easing)
            state["anims"].append(anim)
            anim.play()

        def _animate_in(row):
            _fade(row, 0.0, 1.0, dur=300)
            _slide_margin(row, 18, 0, 320, row.set_margin_top,
                          easing=Adw.Easing.EASE_OUT_CUBIC)

        def _animate_out(listbox, row, on_done=None):
            if not win.get_mapped():
                listbox.remove(row)
                if on_done:
                    on_done()
                return
            _fade(row, 1.0, 0.0, dur=200, easing=Adw.Easing.EASE_IN_CUBIC)
            tgt = Adw.CallbackAnimationTarget.new(
                lambda v: row.set_margin_start(max(0, int(round(v)))))
            anim = Adw.TimedAnimation.new(row, 0, 36, 220, tgt)
            anim.set_easing(Adw.Easing.EASE_IN_CUBIC)

            def done(*_a):
                if row.get_parent() is not None:
                    listbox.remove(row)
                if on_done:
                    on_done()
            anim.connect("done", done)
            state["anims"].append(anim)
            anim.play()

        # --- header + tabs ------------------------------------------------- //
        title = Gtk.Label(label=t("title"), xalign=0)
        title.add_css_class("zenbuji-title")
        card.append(title)

        tabs_box, tabs = make_tabs(
            [("new", t("tab_new", n=len(new_records))),
             ("ignored", t("tab_ignored", m=len(ignored_records)))],
            lambda name: _select(name))
        card.append(tabs_box)

        # --- global processing indicator (only while adds are in flight) --- //
        indicator = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                            halign=Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.set_valign(Gtk.Align.CENTER)
        busy_lbl = Gtk.Label()
        busy_lbl.add_css_class("zenbuji-busy")
        indicator.append(spinner)
        indicator.append(busy_lbl)
        indicator.set_visible(False)
        card.append(indicator)

        # --- two list pages in a stack ------------------------------------- //
        def _make_page():
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_vexpand(True)
            listbox = Gtk.ListBox()
            listbox.add_css_class("zenbuji-dict-list")
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            scroll = Gtk.ScrolledWindow()
            scroll.add_css_class("zenbuji-dict-scroll")
            scroll.set_vexpand(True)
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_child(listbox)
            empty = Gtk.Label(xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER)
            empty.add_css_class("zenbuji-note")
            empty.set_margin_top(24)
            empty.set_valign(Gtk.Align.CENTER)
            empty.set_vexpand(True)
            box.append(scroll)
            box.append(empty)
            return box, listbox, scroll, empty

        page_new, listbox_new, scroll_new, empty_new = _make_page()
        page_ign, listbox_ign, scroll_ign, empty_ign = _make_page()
        empty_new.set_label(t("empty_new"))
        empty_ign.set_label(t("empty_ignored"))

        stack = Gtk.Stack()
        stack.set_vexpand(True)
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(180)
        stack.add_named(page_new, "new")
        stack.add_named(page_ign, "ignored")
        card.append(stack)

        # --- footer (buttons depend on the active tab) --------------------- //
        footer, frow = make_footer()
        frow.set_homogeneous(True)
        ignore_all_b = Gtk.Button(label=t("ignore_all"))
        ignore_all_b.add_css_class("zenbuji-secondary")
        add_all_b = Gtk.Button(label=t("add_all"))
        add_all_b.add_css_class("zenbuji-action")
        restore_all_b = Gtk.Button(label=t("restore_all"))
        restore_all_b.add_css_class("zenbuji-secondary")
        close_b = Gtk.Button(label=t("close"))
        close_b.add_css_class("zenbuji-secondary")
        close_b.connect("clicked", lambda _b: win.close())
        for b in (ignore_all_b, add_all_b, restore_all_b, close_b):
            frow.append(b)
        card.append(footer)

        # --- helpers ------------------------------------------------------- //
        def _refresh_tabs():
            tabs.set_label("new", t("tab_new", n=len(new_records)))
            tabs.set_label("ignored", t("tab_ignored", m=len(ignored_records)))
            empty_new.set_visible(not new_records)
            scroll_new.set_visible(bool(new_records))
            empty_ign.set_visible(not ignored_records)
            scroll_ign.set_visible(bool(ignored_records))

        def _refresh_indicator():
            n = state["inflight"]
            if n > 0:
                spinner.start()
                busy_lbl.set_text(t("adding", n=n))
                indicator.set_visible(True)
            else:
                spinner.stop()
                indicator.set_visible(False)

        def _sync_footer():
            new_tab = state["active"] == "new"
            ignore_all_b.set_visible(new_tab)
            add_all_b.set_visible(new_tab)
            restore_all_b.set_visible(not new_tab)

        def _insert_by_idx(records, listbox, rec):
            pos = next((i for i, r in enumerate(records) if r["idx"] > rec["idx"]),
                       len(records))
            records.insert(pos, rec)
            listbox.insert(rec["row"], pos)
            return pos

        def _make_row(rec, kind):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(4)
            box.set_margin_end(4)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col.set_hexpand(True)
            jp = Gtk.Label(label=rec["lemma"], xalign=0, wrap=True, selectable=True)
            jp.add_css_class("zenbuji-dict-jp")
            jp.set_max_width_chars(22)
            col.append(jp)
            if rec["reading"] and rec["reading"] != rec["lemma"]:
                rl = Gtk.Label(label=rec["reading"], xalign=0, wrap=True)
                rl.add_css_class("zenbuji-reading")
                rl.set_max_width_chars(30)
                col.append(rl)
            if rec.get("failed"):
                wl = Gtk.Label(xalign=0)
                wl.add_css_class("zenbuji-meta")
                wl.set_markup(
                    f'<span foreground="#e01b24">'
                    f'{GLib.markup_escape_text(t("add_failed"))}</span>')
                col.append(wl)
            elif rec["sample"]:
                sm = Gtk.Label(label=rec["sample"], xalign=0, wrap=True)
                sm.add_css_class("zenbuji-meta")
                sm.set_max_width_chars(40)
                col.append(sm)
            box.append(col)

            def _icon_btn(icon, key, cb):
                b = Gtk.Button(icon_name=icon)
                b.add_css_class("flat")
                b.add_css_class("zenbuji-icon")
                b.set_valign(Gtk.Align.CENTER)
                b.set_tooltip_text(t(key))
                b.connect("clicked", cb)
                return b

            if kind == "new":
                box.append(_icon_btn("list-add-symbolic", "add",
                                     lambda _b, r=rec: on_add_one(r)))
                box.append(_icon_btn("action-unavailable-symbolic", "ignore",
                                     lambda _b, r=rec: on_ignore_one(r)))
            else:
                box.append(_icon_btn("edit-undo-symbolic", "restore",
                                     lambda _b, r=rec: on_restore_one(r)))
            row.set_child(box)
            rec["row"] = row
            return row

        # --- actions ------------------------------------------------------- //
        def _drop(records, listbox, rec, on_done=None):
            if rec in records:
                records.remove(rec)
            _animate_out(listbox, rec["row"], on_done=on_done)

        def _finish_add(rec, ok):
            state["inflight"] = max(0, state["inflight"] - 1)
            if not win.get_mapped():
                return GLib.SOURCE_REMOVE
            _refresh_indicator()
            if not ok:                       # re-insert at stable position + warn
                rec["failed"] = True
                _make_row(rec, "new")
                _insert_by_idx(new_records, listbox_new, rec)
                _refresh_tabs()
                _animate_in(rec["row"])
            return GLib.SOURCE_REMOVE

        def _spawn_add(rec):
            def work():
                try:
                    ok = bool(add_fn(rec["lemma"]))
                except Exception:  # noqa: BLE001
                    ok = False
                GLib.idle_add(_finish_add, rec, ok)
            threading.Thread(target=work, daemon=True).start()

        def on_add_one(rec):
            rec["failed"] = False
            _drop(new_records, listbox_new, rec)
            _refresh_tabs()
            state["inflight"] += 1
            _refresh_indicator()
            _spawn_add(rec)

        def on_ignore_one(rec):
            rec["failed"] = False
            _drop(new_records, listbox_new, rec)
            try:
                ignore_fn(rec["lemma"])
            except Exception:  # noqa: BLE001
                pass
            _make_row(rec, "ignored")
            _insert_by_idx(ignored_records, listbox_ign, rec)
            _refresh_tabs()

        def on_restore_one(rec):
            _drop(ignored_records, listbox_ign, rec)
            try:
                unignore_fn(rec["lemma"])
            except Exception:  # noqa: BLE001
                pass
            rec["failed"] = False
            _make_row(rec, "new")
            _insert_by_idx(new_records, listbox_new, rec)
            _refresh_tabs()
            _animate_in(rec["row"])

        def on_add_all(_b):
            todo = list(new_records)
            if not todo:
                return
            for rec in todo:
                rec["failed"] = False
                _drop(new_records, listbox_new, rec)
            state["inflight"] += len(todo)
            _refresh_tabs()
            _refresh_indicator()

            def work():
                for rec in todo:            # sequential so DeepL isn't stampeded
                    try:
                        ok = bool(add_fn(rec["lemma"]))
                    except Exception:  # noqa: BLE001
                        ok = False
                    GLib.idle_add(_finish_add, rec, ok)
            threading.Thread(target=work, daemon=True).start()

        def on_ignore_all(_b):
            for rec in list(new_records):
                rec["failed"] = False
                _drop(new_records, listbox_new, rec)
                try:
                    ignore_fn(rec["lemma"])
                except Exception:  # noqa: BLE001
                    pass
                _make_row(rec, "ignored")
                _insert_by_idx(ignored_records, listbox_ign, rec)
            _refresh_tabs()

        def on_restore_all(_b):
            for rec in list(ignored_records):
                _drop(ignored_records, listbox_ign, rec)
                try:
                    unignore_fn(rec["lemma"])
                except Exception:  # noqa: BLE001
                    pass
                rec["failed"] = False
                _make_row(rec, "new")
                _insert_by_idx(new_records, listbox_new, rec)
            _refresh_tabs()

        add_all_b.connect("clicked", on_add_all)
        ignore_all_b.connect("clicked", on_ignore_all)
        restore_all_b.connect("clicked", on_restore_all)

        # --- tab switching (make_tabs handles the toggle mechanics) -------- //
        def _select(name):
            state["active"] = name
            stack.set_visible_child_name(name)
            _sync_footer()

        # --- initial population -------------------------------------------- //
        for rec in new_records:
            listbox_new.append(_make_row(rec, "new"))
        for rec in ignored_records:
            listbox_ign.append(_make_row(rec, "ignored"))
        _refresh_tabs()
        _sync_footer()
        win.present()

    app.connect("activate", on_activate)
    return app.run([])
