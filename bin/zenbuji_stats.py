#!/usr/bin/env python3
"""GTK4 frosted-glass statistics window — an overview of SRS learning progress.

Shows, over the cached dictionary + SRS schedule: how many words sit at each
learning level (new / learning / young / mature), how many are due, overall
review accuracy, the current daily streak, and a 14-day activity strip plus the
words you miss most. All data is injected by `launch_stats` in zenbuji.py via
`stats_fn` (which returns `srs_stats()`), so this module stays storage-agnostic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

try:
    from zenbuji_glass import make_glass_window
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zenbuji_glass import make_glass_window

# Learning levels, lowest→highest. Kept in sync with srs_status() in zenbuji.py.
LEVEL_ORDER = ("new", "learning", "young", "mature")

STATUS_NAMES = {
    "en": {"new": "New", "learning": "Learning", "young": "Young", "mature": "Mature"},
    "ja": {"new": "新規", "learning": "学習中", "young": "定着中", "mature": "習得"},
}

STATS_STRINGS = {
    "title":      {"en": "Statistics",        "ja": "統計"},
    "words":      {"en": "Words",             "ja": "単語"},
    "reviewed":   {"en": "Studied",           "ja": "学習済み"},
    "due_today":  {"en": "Due today",         "ja": "本日の復習"},
    "accuracy":   {"en": "Accuracy",          "ja": "正答率"},
    "streak":     {"en": "Day streak",        "ja": "連続日数"},
    "today":      {"en": "Today",             "ja": "本日"},
    "levels":     {"en": "Levels",            "ja": "レベル"},
    "activity":   {"en": "Last 14 days",      "ja": "直近14日"},
    "hardest":    {"en": "Hardest words",     "ja": "苦手な単語"},
    "practice":   {"en": "Practice now",      "ja": "練習する"},
    "close":      {"en": "Close",             "ja": "閉じる"},
    "empty":      {"en": "No words to learn yet — look up some Japanese first.",
                   "ja": "学習する単語がありません。まず日本語を調べてください。"},
    "reviews_n":  {"en": "{n} reviews",       "ja": "{n} 回復習"},
}


def _make_tr(ui_language):
    def t(key, **kw):
        entry = STATS_STRINGS.get(key, {})
        s = entry.get(ui_language) or entry.get("en") or key
        return s.format(**kw) if kw else s
    return t


def _spawn_learn():
    cli = str(Path(__file__).resolve().parent / "zenbuji.py")
    try:
        subprocess.Popen([sys.executable, cli, "learn"], start_new_session=True)
    except OSError:
        pass


def show_statistics(*, ui_language="en", languages=("en", "de"), stats_fn) -> int:
    t = _make_tr(ui_language)
    status_names = STATUS_NAMES.get(ui_language, STATUS_NAMES["en"])
    stats = stats_fn() or {}
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        win, card = make_glass_window(
            application, title="zenbuji 統計", default_size=(460, -1),
            resizable=False, draggable=True, close_on_focus_loss=False)

        title = Gtk.Label(label=t("title"), xalign=0)
        title.add_css_class("zenbuji-title")
        card.append(title)

        if not stats.get("total"):
            msg = Gtk.Label(label=t("empty"), wrap=True, xalign=0)
            msg.set_max_width_chars(36)
            msg.add_css_class("zenbuji-note")
            card.append(msg)
            win.present()
            return

        card.append(_summary_tiles(stats, t))

        card.append(_hairline())
        card.append(_section_label(t("levels")))
        card.append(_level_rows(stats, status_names))

        if any(d["reviews"] for d in stats.get("recent", [])):
            card.append(_hairline())
            card.append(_section_label(t("activity")))
            card.append(_activity_strip(stats, t))

        if stats.get("hardest"):
            card.append(_hairline())
            card.append(_section_label(t("hardest")))
            card.append(_hardest_list(stats))

        # --- footer ---------------------------------------------------------- //
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                      homogeneous=True)
        row.set_margin_top(8)
        close = Gtk.Button(label=t("close"))
        close.add_css_class("zenbuji-secondary")
        close.connect("clicked", lambda _b: win.close())
        practice = Gtk.Button(label=t("practice"))
        practice.add_css_class("zenbuji-action")
        practice.connect("clicked", lambda _b: (_spawn_learn(), win.close()))
        row.append(close)
        row.append(practice)
        card.append(row)

        win.present()

    app.connect("activate", on_activate)
    return app.run([])


# --- building blocks --------------------------------------------------------- #
def _hairline():
    h = Gtk.Box()
    h.add_css_class("zenbuji-hairline")
    h.set_margin_top(4)
    h.set_margin_bottom(4)
    return h


def _section_label(text):
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.add_css_class("zenbuji-lang-label")
    return lbl


def _tile(value, caption):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    box.set_hexpand(True)
    num = Gtk.Label(label=value, xalign=0.5)
    num.add_css_class("zenbuji-stat-num")
    cap = Gtk.Label(label=caption, xalign=0.5, wrap=True,
                    justify=Gtk.Justification.CENTER)
    cap.add_css_class("zenbuji-stat-label")
    box.append(num)
    box.append(cap)
    return box


def _summary_tiles(stats, t):
    acc = stats.get("accuracy")
    acc_str = f"{round(acc * 100)}%" if acc is not None else "—"
    streak = stats.get("streak", 0)
    grid = Gtk.Grid(column_spacing=6, row_spacing=10, column_homogeneous=True)
    grid.set_margin_top(4)
    tiles = [
        (str(stats.get("total", 0)), t("words")),
        (str(stats.get("reviewed", 0)), t("reviewed")),
        (str(stats.get("due_today", 0)), t("due_today")),
        (acc_str, t("accuracy")),
        (f"🔥 {streak}" if streak else "—", t("streak")),
        (str(stats.get("today_reviews", 0)), t("today")),
    ]
    for i, (val, cap) in enumerate(tiles):
        grid.attach(_tile(val, cap), i % 3, i // 3, 1, 1)
    return grid


def _level_rows(stats, status_names):
    by_level = stats.get("by_level", {})
    total = max(1, sum(by_level.values()))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    for level in LEVEL_ORDER:
        count = by_level.get(level, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        chip = Gtk.Label(label=status_names.get(level, level))
        chip.add_css_class("zenbuji-level")
        chip.add_css_class(f"zenbuji-level-{level}")
        chip.set_valign(Gtk.Align.CENTER)
        row.append(chip)
        bar = Gtk.LevelBar()
        bar.set_min_value(0)
        bar.set_max_value(total)
        bar.set_value(count)
        bar.set_hexpand(True)
        bar.set_valign(Gtk.Align.CENTER)
        bar.add_css_class("zenbuji-level-bar")
        row.append(bar)
        num = Gtk.Label(label=str(count))
        num.add_css_class("zenbuji-count")
        num.set_valign(Gtk.Align.CENTER)
        row.append(num)
        box.append(row)
    return box


def _activity_strip(stats, t):
    recent = stats.get("recent", [])
    peak = max((d["reviews"] for d in recent), default=0) or 1
    strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
    strip.set_margin_top(2)
    for d in recent:
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col.set_hexpand(True)
        col.set_valign(Gtk.Align.END)
        bar = Gtk.Box()
        bar.add_css_class("zenbuji-activity-bar")
        bar.set_valign(Gtk.Align.END)
        bar.set_hexpand(True)
        bar.set_size_request(-1, max(2, round(48 * d["reviews"] / peak)))
        if d["reviews"] == 0:
            bar.add_css_class("zenbuji-activity-empty")
        bar.set_tooltip_text(f"{d['date']} · {t('reviews_n', n=d['reviews'])}")
        col.append(bar)
        strip.append(col)
    return strip


def _hardest_list(stats):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    for h in stats.get("hardest", []):
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        text = h.get("text", "")
        reading = h.get("reading", "")
        label = f"{text}（{reading}）" if reading and reading != text else text
        jp = Gtk.Label(label=label, xalign=0, wrap=True,
                       halign=Gtk.Align.START)
        jp.add_css_class("zenbuji-dict-jp")
        jp.set_hexpand(True)
        jp.set_max_width_chars(28)
        line.append(jp)
        miss = Gtk.Label(label=f"✗{h.get('wrong', 0)}")
        miss.add_css_class("zenbuji-wrong")
        miss.set_valign(Gtk.Align.CENTER)
        line.append(miss)
        box.append(line)
    return box
