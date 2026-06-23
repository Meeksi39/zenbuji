#!/usr/bin/env python3
"""GTK4 frosted-glass game-helper overlay.

A JRPG-flavoured companion for immersion gaming: a hero spotlight that
celebrates the word you just captured (Super+Shift+K and friends), a live list
of the rest of the dictionary, the background-add shortcut chips, and a busy
spinner + idle quips. Read-only — adding/editing happens elsewhere. Built on the
shared glass scaffold; data is injected by `launch_game` in zenbuji/cli.py.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

try:
    from zenbuji_glass import make_footer, make_glass_window
    from zenbuji_widgets import (LANG_NAMES_BY_UI, DictItem, langs_in, make_tr,
                                 make_card_gridview, scroll_with_edge_shadows,
                                 translation_lines)
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zenbuji_glass import make_footer, make_glass_window
    from zenbuji_widgets import (LANG_NAMES_BY_UI, DictItem, langs_in, make_tr,
                                 make_card_gridview, scroll_with_edge_shadows,
                                 translation_lines)

# The game overlay is intentionally Japanese-only for flavour (immersion):
GAME_TITLE = "✦ 漢字キャプチャー ✦"   # "KanjiCapture", JRPG-style
GAME_QUIPS = ["ずんだもん、見てるよ…ことばを集めよう！",
              "クエストログが単語を求めている…！",
              "気になることば、見つけた？ゲットだ！",
              "ぼうけんはこれから！フレーズをつかめ！",
              "狩りはつづく…"]
# Transient capture banners (JRPG flourish): new word vs. re-captured word.
GAME_BANNER_NEW = "✦ 新規ゲット！ ✦"        # brand-new word -> pink "Booster"
GAME_BANNER_LEVELUP = "✦ レベルアップ！ ✦"  # re-captured -> gold "LEVEL UP"

GAME_STRINGS = {
    "search":           {"en": "Search…",       "ja": "検索…"},
    "new_word":         {"en": "NEW",            "ja": "新規"},
    "known":            {"en": "KNOWN",          "ja": "既習"},
    "busy_reading":     {"en": "Reading…",       "ja": "読み取り中…"},
    "busy_translating": {"en": "Translating…",   "ja": "翻訳中…"},
}


def _read_busy(path, max_age=120.0):
    """Current background-busy state ({stage,ts}), or None when idle/stale."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    ts = data.get("ts")
    if ts:
        try:
            if (datetime.now() - datetime.fromisoformat(ts)).total_seconds() > max_age:
                return None
        except (ValueError, TypeError):
            pass
    return data


def show_game(*, ui_language="en", languages=("en", "de"), load_fn,
              speak_fn=None, sfx_fn=None, shortcuts=None, busy_path=None,
              watch_path=None) -> int:
    """Show the game-helper overlay. `load_fn()` returns the dictionary; a
    background add rewriting `watch_path` triggers the capture celebration.
    `sfx_fn(name)` plays a sound effect (the sword on a new-word capture)."""
    t = make_tr(GAME_STRINGS, ui_language)
    lang_names = LANG_NAMES_BY_UI.get(ui_language, LANG_NAMES_BY_UI["en"])
    state = {"monitors": [], "seen": {}, "primed": False, "anims": [],
             "session": 0, "quip_mode": "idle", "seq_token": 0, "token": 0}
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        win, card = make_glass_window(
            application, title="zenbuji ゲーム", default_size=(420, 560),
            resizable=True, draggable=True, close_on_focus_loss=False)
        # Drop the card's horizontal padding so the card grid spans edge to edge
        # (like the dict); every non-list row is re-inset by INSET below.
        card.add_css_class("zenbuji-flush-window")
        INSET = 18

        # --- header: title + combo, with the quip as a tied subtitle -------- //
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        gtitle = Gtk.Label(label=GAME_TITLE, xalign=0, hexpand=True,
                           halign=Gtk.Align.START)
        gtitle.add_css_class("zenbuji-game-title")
        banner.append(gtitle)
        combo_lbl = Gtk.Label(label="★ 0")
        combo_lbl.add_css_class("zenbuji-combo")
        combo_lbl.set_valign(Gtk.Align.CENTER)
        banner.append(combo_lbl)
        header.append(banner)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_row.set_margin_start(10)
        status_row.set_margin_top(4)
        spinner = Gtk.Spinner()
        spinner.set_valign(Gtk.Align.CENTER)
        spinner.set_size_request(14, 14)
        quip_lbl = Gtk.Label(xalign=0, wrap=True, halign=Gtk.Align.START)
        quip_lbl.add_css_class("zenbuji-quip")
        quip_lbl.set_valign(Gtk.Align.CENTER)
        quip_lbl.set_max_width_chars(44)
        status_row.append(spinner)
        status_row.append(quip_lbl)
        header.append(status_row)
        card.append(header)

        hheader = Gtk.Box()
        hheader.add_css_class("zenbuji-hairline")
        hheader.set_margin_top(6)
        card.append(hheader)

        # --- hero spotlight: the freshly-captured word, big and gold -------- //
        hero = Gtk.Overlay()
        hero.set_margin_top(8)
        hero.set_visible(False)
        hero_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hero_frame.add_css_class("zenbuji-hero")
        hero_frame.set_margin_top(13)
        hero_frame.set_margin_end(8)
        hero_word = Gtk.Label(xalign=0, wrap=True, selectable=True)
        hero_word.add_css_class("zenbuji-hero-word")
        hero_word.set_max_width_chars(14)
        hero_reading = Gtk.Label(xalign=0, wrap=True)
        hero_reading.add_css_class("zenbuji-hero-reading")
        hero_trans = Gtk.Label(xalign=0, wrap=True)
        hero_trans.add_css_class("zenbuji-hero-trans")
        hero_trans.set_max_width_chars(40)
        hero_frame.append(hero_word)
        hero_frame.append(hero_reading)
        hero_frame.append(hero_trans)
        hero.set_child(hero_frame)
        ribbon = Gtk.Label()
        ribbon.add_css_class("zenbuji-ribbon")
        ribbon.set_halign(Gtk.Align.END)
        ribbon.set_valign(Gtk.Align.START)
        ribbon.set_margin_end(0)
        ribbon.set_can_target(False)
        ribbon.set_visible(False)
        hero.add_overlay(ribbon)
        card.append(hero)

        search = Gtk.SearchEntry(hexpand=True)
        search.set_placeholder_text(t("search"))
        card.append(search)

        # Recent words: the SAME virtualized card grid as the dictionary (cards,
        # responsive columns, inset edge shadows), shared via zenbuji_widgets.
        # Read-only glance cells (see build_game_cell).
        game_store = Gio.ListStore(item_type=DictItem)

        def _filt(item, _u=None):
            needle = search.get_text().strip().lower()
            if not needle:
                return True
            e = item.entry
            hay = " ".join([e.get("text", ""), e.get("reading", ""),
                            *e.get("translations", {}).values()]).lower()
            return needle in hay

        game_filter = Gtk.CustomFilter.new(_filt)
        filter_model = Gtk.FilterListModel(model=game_store, filter=game_filter)
        gridview = make_card_gridview(Gtk.NoSelection(model=filter_model),
                                      lambda it: build_game_cell(it))
        list_box, _scroll = scroll_with_edge_shadows(gridview)
        card.append(list_box)
        search.connect(
            "search-changed",
            lambda _s: game_filter.changed(Gtk.FilterChange.DIFFERENT))

        # --- footer: the background-add shortcut chips ---------------------- //
        game_footer, frow = make_footer()
        keys_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        keys_box.set_halign(Gtk.Align.END)
        keys_box.set_hexpand(True)
        for sc in (shortcuts or []):
            pair = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            chip = Gtk.Label(label=sc.get("keys", ""))
            chip.add_css_class("zenbuji-kbd-sm")
            cap = Gtk.Label(label=sc.get("label", ""))
            cap.add_css_class("zenbuji-meta")
            pair.append(chip)
            pair.append(cap)
            keys_box.append(pair)
        frow.append(keys_box)
        card.append(game_footer)

        # --- card builder: a clean, big-kanji second-screen glance card ----- //
        def build_game_cell(item):
            entry = item.entry
            text = entry.get("text", "")
            reading = entry.get("reading", "")
            trans = entry.get("translations", {})
            holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            holder.add_css_class("zenbuji-dict-card")
            holder.add_css_class("zenbuji-game-card")   # inner padding for the cell
            holder.set_hexpand(True)
            jp = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
            jp.add_css_class("zenbuji-game-jp")          # large kanji
            jp.set_max_width_chars(22)
            holder.append(jp)
            if reading and reading != text:
                rl = Gtk.Label(label=reading, xalign=0, wrap=True)
                rl.add_css_class("zenbuji-reading")
                rl.set_max_width_chars(36)
                holder.append(rl)
            for line in translation_lines(trans, languages, lang_names, max_chars=36):
                holder.append(line)
            # Corner ribbon: new (unreviewed) vs already known (has SRS progress).
            known = (entry.get("srs") or {}).get("level") in (
                "learning", "young", "mature")
            ribbon = Gtk.Label(label=t("known") if known else t("new_word"))
            ribbon.add_css_class("zenbuji-card-ribbon")
            ribbon.add_css_class("zenbuji-ribbon-levelup" if known
                                 else "zenbuji-ribbon-new")
            ribbon.set_halign(Gtk.Align.END)
            ribbon.set_valign(Gtk.Align.START)
            ribbon.set_can_target(False)
            cell = Gtk.Overlay()
            cell.set_child(holder)
            cell.add_overlay(ribbon)
            return cell

        # --- animation primitives (smooth eased; margins stay >= 0) --------- //
        def _fade(widget, frm, to, dur=240, easing=None):
            widget.set_opacity(frm)
            tgt = Adw.CallbackAnimationTarget.new(widget.set_opacity)
            anim = Adw.TimedAnimation.new(widget, frm, to, dur, tgt)
            anim.set_easing(easing or Adw.Easing.EASE_OUT_CUBIC)
            state["anims"].append(anim)
            anim.play()

        def _slide_margin(widget, frm, to, dur, set_margin,
                          easing=Adw.Easing.EASE_IN_OUT_CUBIC):
            set_margin(max(0, int(round(frm))))
            tgt = Adw.CallbackAnimationTarget.new(
                lambda v: set_margin(max(0, int(round(v)))))
            anim = Adw.TimedAnimation.new(widget, frm, to, dur, tgt)
            anim.set_easing(easing)
            state["anims"].append(anim)
            anim.play()

        def _pulse(widget, lo=0.35):
            widget.set_opacity(lo)
            tgt = Adw.CallbackAnimationTarget.new(widget.set_opacity)
            anim = Adw.TimedAnimation.new(widget, lo, 1.0, 350, tgt)
            anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)
            state["anims"].append(anim)
            anim.play()

        def _show_hero(entry):
            text = entry.get("text", "")
            reading = entry.get("reading", "")
            trans = entry.get("translations", {})
            hero_word.set_text(text)
            hero_reading.set_text(reading if reading and reading != text else "")
            hero_reading.set_visible(bool(hero_reading.get_text()))
            parts = []
            for lang in langs_in(languages, trans):
                if trans.get(lang):
                    parts.append(f"{lang_names.get(lang, lang.upper())}: {trans[lang]}")
            hero_trans.set_text("  ·  ".join(parts))
            for w in (hero_word, hero_reading, hero_trans):
                w.set_opacity(1.0)
            hero_word.set_margin_start(0)
            hero_reading.set_margin_start(0)
            hero.set_visible(True)

        def _ribbon_slide_in(any_new):
            ribbon.remove_css_class("zenbuji-ribbon-new")
            ribbon.remove_css_class("zenbuji-ribbon-levelup")
            ribbon.set_text(GAME_BANNER_NEW if any_new else GAME_BANNER_LEVELUP)
            ribbon.add_css_class("zenbuji-ribbon-new" if any_new
                                 else "zenbuji-ribbon-levelup")
            ribbon.set_visible(True)
            _fade(ribbon, 0.0, 1.0, dur=260)
            _slide_margin(ribbon, 70, 0, 480, ribbon.set_margin_end)

        def _word_set_margin(v):
            hero_word.set_margin_start(v)
            hero_reading.set_margin_start(v)

        def _celebrate(new_entry, any_new):
            # Points: a brand-new word is worth 500, an already-known one 100.
            state["session"] += 500 if any_new else 100
            combo_lbl.set_text(f"★ {state['session']}")
            _pulse(combo_lbl)
            state["seq_token"] += 1
            tok = state["seq_token"]
            had_word = hero.get_visible() and bool(hero_word.get_text())

            def alive():
                return tok == state["seq_token"]

            if had_word:
                _fade(hero_word, 1.0, 0.0, dur=220)
                _fade(hero_reading, 1.0, 0.0, dur=220)
                _fade(hero_trans, 1.0, 0.0, dur=220)
                _slide_margin(hero_word, 0, 26, 220, _word_set_margin)
                _fade(ribbon, ribbon.get_opacity(), 0.0, dur=200,
                      easing=Adw.Easing.EASE_IN_CUBIC)
            out_delay = 260 if had_word else 0

            def _word_in():
                if not alive():
                    return GLib.SOURCE_REMOVE
                ribbon.set_visible(False)
                _show_hero(new_entry)
                hero_word.set_opacity(0.0)
                hero_reading.set_opacity(0.0)
                hero_trans.set_opacity(0.0)
                _word_set_margin(28)
                _fade(hero_word, 0.0, 1.0, dur=320)
                _fade(hero_reading, 0.0, 1.0, dur=320)
                _slide_margin(hero_word, 28, 0, 380, _word_set_margin)
                return GLib.SOURCE_REMOVE

            def _trans_in():
                if not alive():
                    return GLib.SOURCE_REMOVE
                _fade(hero_trans, 0.0, 1.0, dur=300)
                return GLib.SOURCE_REMOVE

            def _banner_in():
                if alive():
                    _ribbon_slide_in(any_new)
                    # The slash lands as the 新規ゲット ribbon flies in (new only).
                    if any_new and sfx_fn:
                        sfx_fn("sword")
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(out_delay, _word_in)
            GLib.timeout_add(out_delay + 380, _trans_in)
            GLib.timeout_add(out_delay + 660, _banner_in)

        # --- data refresh + capture detection ------------------------------- //
        def rebuild():
            data = load_fn()
            entries = sorted(data.values(),
                             key=lambda e: e.get("last_seen", ""), reverse=True)
            prev = state["seen"]
            current = {e.get("text", ""): e.get("last_seen", "") for e in entries}

            captured = any_new = False
            top = None
            if entries:
                top = entries[0]
                if state["primed"] and prev.get(top["text"]) != top.get("last_seen"):
                    captured = True
                    any_new = top["text"] not in prev
                if not captured:
                    _show_hero(top)
            else:
                hero.set_visible(False)

            # The list shows everything but the hero word, as cards.
            items = [DictItem(e.get("text", ""), e) for e in entries[1:]]
            game_store.splice(0, game_store.get_n_items(), items)

            state["seen"] = current
            if not state["primed"]:
                state["primed"] = True
            elif captured:
                _celebrate(top, any_new)

        def schedule_rebuild():
            state["token"] += 1
            tok = state["token"]

            def fire():
                if not win.get_mapped():
                    return GLib.SOURCE_REMOVE
                if tok == state["token"]:
                    rebuild()
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
                state["monitors"].append(mon)
            except Exception:  # noqa: BLE001
                pass

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

        # --- busy spinner + idle quips -------------------------------------- //
        def _set_idle_quip():
            if state["quip_mode"] == "idle":
                quip_lbl.set_text(random.choice(GAME_QUIPS))

        def update_busy():
            info = _read_busy(busy_path) if busy_path else None
            if info:
                state["quip_mode"] = "busy"
                spinner.start()
                quip_lbl.set_text(t("busy_translating") if info.get("stage") ==
                                  "translating" else t("busy_reading"))
            else:
                spinner.stop()
                if state["quip_mode"] != "idle":
                    state["quip_mode"] = "idle"
                    _set_idle_quip()

        def setup_busy_watch():
            _set_idle_quip()
            update_busy()
            if busy_path:
                try:
                    gfile = Gio.File.new_for_path(str(busy_path))
                    mon = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
                    mon.connect("changed", lambda *_a: update_busy())
                    state["monitors"].append(mon)
                except Exception:  # noqa: BLE001
                    pass
                GLib.timeout_add_seconds(4, lambda: (update_busy(), True)[1])
            GLib.timeout_add_seconds(18, lambda: (_set_idle_quip(), True)[1])

        # Re-inset every row except the card grid, so the list spans full width
        # while the header/hero/search/footer keep the window's side padding.
        child = card.get_first_child()
        while child is not None:
            if child is not list_box:
                child.set_margin_start(INSET)
                child.set_margin_end(INSET)
            child = child.get_next_sibling()

        rebuild()
        win.present()
        setup_watch()
        setup_busy_watch()

    app.connect("activate", on_activate)
    return app.run([])
