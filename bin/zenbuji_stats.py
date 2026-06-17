#!/usr/bin/env python3
"""GTK4 frosted-glass statistics window — an overview of SRS learning progress.

Shows, over the cached dictionary + SRS schedule: a hero row (due today / day
streak / accuracy), a segmented "maturity" bar of how many words sit at each
learning level (new / learning / young / mature) with a dot legend, a 14-day
activity chart, and the words you miss most. All data is injected by
`launch_stats` in zenbuji.py via `stats_fn` (which returns `srs_stats()`), so this
module stays storage-agnostic.
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
    from zenbuji_glass import accent_rgba, make_glass_window
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zenbuji_glass import accent_rgba, make_glass_window

# Learning levels, lowest→highest. Kept in sync with srs_status() in zenbuji.py.
LEVEL_ORDER = ("new", "learning", "young", "mature")

# Distinct, legible level colours (GNOME palette: grey / amber / blue / green).
LEVEL_HEX = {
    "new": "#8a8f96",
    "learning": "#e5a50a",
    "young": "#3584e4",
    "mature": "#2ec27e",
}

STATUS_NAMES = {
    "en": {"new": "New", "learning": "Learning", "young": "Young", "mature": "Mature"},
    "ja": {"new": "新規", "learning": "学習中", "young": "定着中", "mature": "習得"},
}

STATS_STRINGS = {
    "title":      {"en": "Statistics",        "ja": "統計"},
    "words":      {"en": "words",             "ja": "単語"},
    "due_today":  {"en": "Due today",         "ja": "本日の復習"},
    "accuracy":   {"en": "Accuracy",          "ja": "正答率"},
    "streak":     {"en": "Day streak",        "ja": "連続日数"},
    "levels":     {"en": "Levels",            "ja": "レベル"},
    "activity":   {"en": "Last 14 days",      "ja": "直近14日"},
    "hardest":    {"en": "Needs review",      "ja": "苦手な単語"},
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


def _hex_rgb(h):
    """'#rrggbb' → (r, g, b) floats in 0–1."""
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rounded_rect(cr, x, y, w, h, r):
    """Append a rounded-rectangle path to the cairo context."""
    import math
    r = min(r, w / 2, h / 2)
    if r <= 0:
        cr.rectangle(x, y, w, h)
        return
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def show_statistics(*, ui_language="en", languages=("en", "de"), stats_fn) -> int:
    t = _make_tr(ui_language)
    status_names = STATUS_NAMES.get(ui_language, STATUS_NAMES["en"])
    stats = stats_fn() or {}
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        win, card = make_glass_window(
            application, title="zenbuji 統計", default_size=(480, -1),
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

        # Charts that need a manual repaint when the light/dark scheme flips.
        redraws = []

        card.append(_hero_row(stats, t))

        # --- levels ------------------------------------------------------- //
        card.append(_section_header(t("levels"),
                                    f"{stats['total']} {t('words')}"))
        bar = _maturity_bar(stats)
        redraws.append(bar)
        card.append(bar)
        card.append(_legend(stats, status_names))

        # --- activity ----------------------------------------------------- //
        recent = stats.get("recent", [])
        if any(d["reviews"] for d in recent):
            total_14 = sum(d["reviews"] for d in recent)
            card.append(_section_header(t("activity"),
                                        t("reviews_n", n=total_14)))
            chart = _activity_chart(recent)
            redraws.append(chart)
            card.append(chart)

        # --- needs review ------------------------------------------------- //
        if stats.get("hardest"):
            card.append(_section_header(t("hardest")))
            card.append(_hardest_list(stats))

        # --- footer ------------------------------------------------------- //
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

        style_mgr = Adw.StyleManager.get_default()
        style_mgr.connect("notify::dark",
                          lambda *_a: [d.queue_draw() for d in redraws])

        win.present()

    app.connect("activate", on_activate)
    return app.run([])


# --- building blocks --------------------------------------------------------- #
def _section_header(text, count=None):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    box.set_margin_top(18)
    cap = Gtk.Label(label=text.upper(), xalign=0)
    cap.add_css_class("zenbuji-lang-label")
    cap.set_hexpand(True)
    box.append(cap)
    if count:
        cnt = Gtk.Label(label=count, xalign=1)
        cnt.add_css_class("zenbuji-section-count")
        box.append(cnt)
    return box


def _stat(value, caption, accent=False):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    box.set_hexpand(True)
    num = Gtk.Label(label=value, xalign=0.5)
    num.add_css_class("zenbuji-stat-num")
    if accent:
        num.add_css_class("zenbuji-stat-num-accent")
    cap = Gtk.Label(label=caption.upper(), xalign=0.5, wrap=True,
                    justify=Gtk.Justification.CENTER)
    cap.add_css_class("zenbuji-stat-label")
    box.append(num)
    box.append(cap)
    return box


def _vrule():
    sep = Gtk.Box()
    sep.add_css_class("zenbuji-vrule")
    sep.set_margin_top(2)
    sep.set_margin_bottom(2)
    return sep


def _hero_row(stats, t):
    acc = stats.get("accuracy")
    acc_str = f"{round(acc * 100)}%" if acc is not None else "—"
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    row.add_css_class("zenbuji-panel")
    row.set_margin_top(8)
    row.append(_stat(str(stats.get("due_today", 0)), t("due_today"), accent=True))
    row.append(_vrule())
    row.append(_stat(str(stats.get("streak", 0)), t("streak")))
    row.append(_vrule())
    row.append(_stat(acc_str, t("accuracy")))
    return row


def _maturity_bar(stats):
    by_level = stats.get("by_level", {})
    da = Gtk.DrawingArea()
    da.set_content_height(13)
    da.set_hexpand(True)
    da.set_margin_top(4)

    def draw(_area, cr, width, height, *_a):
        counts = [(lvl, by_level.get(lvl, 0)) for lvl in LEVEL_ORDER
                  if by_level.get(lvl, 0) > 0]
        total = sum(c for _l, c in counts)
        radius = height / 2
        if total <= 0:
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.15)
            _rounded_rect(cr, 0, 0, width, height, radius)
            cr.fill()
            return
        gap = 3.0
        avail = max(0.0, width - gap * (len(counts) - 1))
        x = 0.0
        for lvl, c in counts:
            w = avail * c / total
            r, g, b = _hex_rgb(LEVEL_HEX[lvl])
            cr.set_source_rgb(r, g, b)
            _rounded_rect(cr, x, 0, w, height, radius)
            cr.fill()
            x += w + gap

    da.set_draw_func(draw)
    return da


def _legend(stats, status_names):
    by_level = stats.get("by_level", {})
    grid = Gtk.Grid(column_spacing=16, row_spacing=2)
    grid.set_margin_top(8)
    for i, lvl in enumerate(LEVEL_ORDER):
        label = Gtk.Label(xalign=0)
        label.add_css_class("zenbuji-legend")
        label.set_markup(
            f'<span foreground="{LEVEL_HEX[lvl]}">●</span>  '
            f'{status_names.get(lvl, lvl)}  {by_level.get(lvl, 0)}')
        grid.attach(label, i % 2, i // 2, 1, 1)
    return grid


def _activity_chart(recent):
    peak = max((d["reviews"] for d in recent), default=0) or 1
    da = Gtk.DrawingArea()
    da.set_content_height(52)
    da.set_hexpand(True)
    da.set_margin_top(8)

    def draw(area, cr, width, height, *_a):
        n = len(recent)
        if n == 0:
            return
        slot = width / n
        # Thin, fully-rounded vertical pills centered in each day's slot.
        pillw = max(5.0, min(10.0, slot * 0.45))
        accent = accent_rgba(Adw.StyleManager.get_default().get_dark())
        fg = area.get_color()
        for i, d in enumerate(recent):
            x = i * slot + (slot - pillw) / 2
            if d["reviews"] > 0:
                bh = max(pillw, height * d["reviews"] / peak)
                cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.92)
                _rounded_rect(cr, x, height - bh, pillw, bh, pillw / 2)
            else:
                # Empty day: a faint baseline dot.
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.13)
                _rounded_rect(cr, x, height - pillw, pillw, pillw, pillw / 2)
            cr.fill()

    da.set_draw_func(draw)
    return da


def _hardest_list(stats):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_margin_top(4)
    for h in stats.get("hardest", [])[:3]:
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
        miss = Gtk.Label(label=f"×{h.get('wrong', 0)}", xalign=1)
        miss.add_css_class("zenbuji-meta")
        miss.set_valign(Gtk.Align.CENTER)
        line.append(miss)
        box.append(line)
    return box
