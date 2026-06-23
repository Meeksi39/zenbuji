#!/usr/bin/env python3
"""GTK4 frosted-glass learning window — spaced-repetition quiz over the cache.

Shows a cached word as large kanji (no furigana); the learner types the reading
and (unless the translation is given as a hint) the translation. The answer is
graded, the correct reading/translation is revealed, the learner confirms the
result (self-grade override), and that feeds the SRS schedule. A progress bar
tracks the round and a summary lists each word's new learning status.

All data/grading logic is injected by `launch_learning` in zenbuji/cli.py:
`grade_fn(card, reading, translation)` and `review_fn(text, correct)`.
"""

from __future__ import annotations

import difflib
import random
import subprocess
import sys
import time
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

LANG_NAMES_BY_UI = {
    "en": {"en": "English", "de": "Deutsch", "ja": "日本語"},
    "ja": {"en": "英語", "de": "ドイツ語", "ja": "日本語"},
}

# How long the correct-answer ribbon holds (after flying in, before flying out);
# with the ~0.3s fly-out the next word loads ~1.4s after a correct answer.
_BANNER_HOLD_MS = 1100

# Announced (in the punchy fanfare voice) as the drill-done ribbon flies in.
# VOICEVOX is Japanese-only, so this is the spoken form regardless of UI language.
_DRILL_DONE_VOICE = "ドリル完了！！"

def _reading_markup(correct: str, typed: str, accent: str) -> str:
    """Pango markup for `correct`: the characters the learner got right are shown
    in the accent colour, the ones they missed are muted (the default colour
    dimmed), so a missed word highlights what they nailed and fades the rest.
    The matched run is the longest common subsequence (difflib)."""
    matched = set()
    sm = difflib.SequenceMatcher(None, (typed or "").strip(), correct,
                                 autojunk=False)
    for blk in sm.get_matching_blocks():
        for i in range(blk.b, blk.b + blk.size):
            matched.add(i)
    out = []
    for i, ch in enumerate(correct):
        esc = GLib.markup_escape_text(ch)
        out.append(f'<span foreground="{accent}">{esc}</span>' if i in matched
                   else f'<span alpha="40%">{esc}</span>')
    return "".join(out)

LEARN_STRINGS = {
    "title":        {"en": "Practice",        "ja": "練習"},
    "reading":      {"en": "Reading (furigana)…", "ja": "読み（ふりがな）…"},
    "translation":  {"en": "Translation (EN / DE)…", "ja": "翻訳（英 / 独）…"},
    "check":        {"en": "Check",           "ja": "確認"},
    "got_it":       {"en": "✓ Got it",        "ja": "✓ 正解"},
    "missed":       {"en": "✗ Missed",        "ja": "✗ 不正解"},
    "verdict_ok":   {"en": "Correct",         "ja": "正解"},
    "verdict_no":   {"en": "Not quite",       "ja": "惜しい"},
    "reading_lbl":  {"en": "Reading",         "ja": "読み"},
    "read_aloud":   {"en": "Read aloud",      "ja": "読み上げる"},
    "you":          {"en": "You typed",       "ja": "あなたの入力"},
    "blank":        {"en": "(blank)",         "ja": "（空欄）"},
    "score":        {"en": "Score",           "ja": "スコア"},
    "done":         {"en": "Done!",           "ja": "完了！"},
    "again":        {"en": "Practice again",  "ja": "もう一度"},
    "close":        {"en": "Close",           "ja": "閉じる"},
    "view_stats":   {"en": "View stats",      "ja": "統計を見る"},
    "level_up":     {"en": "Level up!",       "ja": "レベルアップ！"},
    "leveled_up":   {"en": "{n} leveled up!", "ja": "{n} 個レベルアップ！"},
    "banner_correct": {"en": "✦ Correct! ✦",  "ja": "✦ 正解！ ✦"},
    "banner_levelup": {"en": "✦ Level up! ✦", "ja": "✦ レベルアップ！ ✦"},
    "banner_drill":   {"en": "✦ Drill done!! ✦", "ja": "✦ ドリル完了！！ ✦"},
    "drill_prompt":     {"en": "Type the reading to lock it in",
                         "ja": "読みを入力して覚えよう"},
    "drill_progress":   {"en": "{n} / {total}", "ja": "{n} / {total}"},
    "drill_placeholder": {"en": "Type the reading…", "ja": "読みを入力…"},
    "drill_override":   {"en": "I was right", "ja": "実は正解"},
    "empty":        {"en": "No words to practise yet — look up some Japanese first.",
                     "ja": "練習する単語がありません。まず日本語を調べてください。"},
}

STATUS_NAMES = {
    "en": {"new": "New", "learning": "Learning", "young": "Young", "mature": "Mature"},
    "ja": {"new": "新規", "learning": "学習中", "young": "定着中", "mature": "習得"},
}

# Learning levels, lowest→highest — used to detect when a card graduates.
LEVEL_ORDER = ("new", "learning", "young", "mature")


def _level_rank(level: str) -> int:
    try:
        return LEVEL_ORDER.index(level)
    except ValueError:
        return 0

# Casual Japanese "let's start" greetings shown (and spoken, if TTS auto-read is
# on) when a practice round opens — a random one each time. A spread of cute,
# funny, and playfully-creepy, because ずんだもん should have range. Toggle with
# the learn_greeting config / the prefs switch.
GREETINGS = [
    # — cute —
    "やっほー！いっしょにがんばろうね！",
    "きょうも勉強えらい！大好き！",
    "さあ、はじめよう！きみならできるよ！",
    "ふぁいと〜！むりはしないでね。",
    "おかえり！待ってたよ〜。",
    "いっしょに単語、おぼえよっ！",
    "きみのやる気、サイコー！",
    "ちょっとだけでも、えらいよ！",
    "つぎの単語、いってみよ〜！",
    "リラックスして、たのしくいこ！",
    "きみのペースでいいんだよ。",
    "ちいさな一歩が、大きな上達！",
    "深呼吸して、いっぽずつね。",
    "まちがえても大丈夫、それが勉強だよ。",
    "さあ、ことばのぼうけんへ出発！",
    "つかれたら、いつでも休んでいいからね。",
    "いっしょなら、なんでもできる気がする！",
    "今日のきみ、いつもよりかしこく見える！",
    # — funny —
    "さぼってないで、勉強の時間だよ！",
    "ねむい？コーヒーでものんで、はじめよ！",
    "逃げちゃだめだよ、単語が待ってる！",
    "脳みそ、あたためていこ〜！",
    "今日サボったら、明日の自分が泣くよ？",
    "やる気スイッチ、ポチッとな！",
    "漢字はともだち、こわくないよ…たぶん。",
    "はい、言い訳タイムはおしまい！",
    "勉強しないと、ずんだもんが食べちゃうぞ！",
    "単語帳が「会いたい」って言ってるよ。",
    "おはよ！…って、もう夜かな？まあいっか、勉強しよ！",
    # — playfully creepy —
    "ふふ…逃がさないよ。さあ、勉強しよ？",
    "ずっと…見てたよ。べんきょうの時間だね。",
    "きみの後ろにいるよ。ふりむかないで、勉強して。",
    "まだ起きてるの？…ちょうどいい、勉強しよ。",
    "その単語、おぼえるまで帰さないよ。",
    "ねえ、いっしょにいようね。ずっと、ずっと。",
    "暗いところで勉強するの、すきでしょ？",
    "きみの夢に出てきちゃうかも。さあ、はじめよ。",
    "一問まちがえるごとに、ちょっとずつ近づくよ…。",
    "しずかに…単語が聞いてるよ。",
]

# Casual Japanese goodbyes shown (and spoken, if TTS auto-read is on) on the
# summary screen when a round wraps up. Same cute / funny / creepy spread, same
# learn_greeting toggle.
FAREWELLS = [
    # — cute —
    "またね！おつかれさま！",
    "きょうもよくがんばったね！",
    "バイバイ！また会おうね！",
    "おつかれ！ゆっくり休んでね。",
    "また あした、まってるよ。",
    "すごいすごい！えらかったよ！",
    "きょうの勉強、かんぺき！おやすみ〜。",
    "また来てね、たのしみにしてる！",
    "よくできました！はなまるあげる！",
    "きみの努力、ちゃんと見てたよ。えらい！",
    "じゃあね、また単語であおうね！",
    "ナイスファイト！また今度！",
    "きょうのきみ、かっこよかったよ！",
    "ばいばーい！わすれないでね〜。",
    # — funny —
    "もう終わり？はやいね…さぼっちゃダメだよ！",
    "つぎはもっとできるはず！…たぶんね！",
    "帰る前に、もう一問どう？…うそうそ、またね！",
    "単語たちが「また会おうね」って手をふってるよ。",
    "脳みそ、つかれた？アイスでも食べて！",
    "きょうのノルマ、クリア！えらいぞ！",
    "ふっかつの呪文：「また勉強する」。となえてね！",
    "やったね！レベルアップの音が聞こえる…気がする！",
    # — playfully creepy —
    "また来てね…ぜったいだよ？まってるからね。",
    "きみが帰っても、単語はずっと見てるよ。",
    "行かないで…なんてね。またあした、ね？",
    "きみの夢の中で、また勉強しようね。",
    "さよならは言わないよ。だって、また来るでしょ？",
    "この単語帳、きみのこと覚えてるからね。ふふ。",
    "今夜、思い出してくれる？…単語のこと、だよ？",
    "また会えるよね…ぜったい、ぜったいに。",
]


def _spawn_learn():
    cli = str(Path(__file__).resolve().parent / "zenbuji_main.py")
    try:
        subprocess.Popen([sys.executable, cli, "learn"], start_new_session=True)
    except OSError:
        pass


def _spawn_stats():
    cli = str(Path(__file__).resolve().parent / "zenbuji_main.py")
    try:
        subprocess.Popen([sys.executable, cli, "stats"], start_new_session=True)
    except OSError:
        pass


def _answer_col(width=300, spacing=12):
    """A centered, fixed-width column so the answer input/buttons sit in a tidy
    measure instead of stretching the full card width."""
    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    col.set_halign(Gtk.Align.CENTER)
    col.set_size_request(width, -1)
    return col


def _resolve_xkb_engine(bus, gnome_id):
    """Map a GNOME xkb source id (e.g. ``de`` / ``de+nodeadkeys``) to its IBus
    engine name (e.g. ``xkb:de::deu``)."""
    layout, _, variant = gnome_id.partition("+")
    try:
        for e in bus.list_engines():
            name = e.get_name()
            if not name.startswith("xkb:"):
                continue
            parts = name.split(":")
            if len(parts) >= 3 and parts[1] == layout and parts[2] == variant:
                return name
    except Exception:
        pass
    return None


def _ime_switcher():
    """Best-effort input-method switching for the quiz fields.

    Setting ``org.gnome.desktop.input-sources current`` does NOT make
    gnome-shell switch the live engine, so we drive IBus directly:
    ``Bus.set_global_engine`` actually swaps the active engine for the focused
    window. We pick the first kana-capable IBus engine (mozc/anthy/…) for the
    reading field and a latin layout for the translation field, both resolved
    from the user's configured GNOME sources. Returns ``(to_kana, to_latin,
    restore)`` callables; ``restore`` puts back whatever engine was active when
    the quiz opened. When IBus or a suitable engine is missing they are no-ops,
    so other setups keep their default and nothing breaks.
    """
    noop = (lambda: None, lambda: None, lambda: None)
    try:
        gi.require_version("IBus", "1.0")
        from gi.repository import IBus
        IBus.init()
        bus = IBus.Bus()
        if not bus.is_connected():
            return noop
    except (ValueError, ImportError):
        return noop
    except Exception:
        return noop

    # Engines that actually produce kana — skip mozc-off and plain xkb:jp,
    # which are latin despite the Japanese label.
    kana_hint = ("mozc-on", "mozc-jp", "mozc", "anthy", "kkc", "skk", "kana")
    kana_engine = latin_engine = None
    try:
        schema_id = "org.gnome.desktop.input-sources"
        ss = Gio.SettingsSchemaSource.get_default()
        if ss is not None and ss.lookup(schema_id, True) is not None:
            sources = Gio.Settings.new(schema_id).get_value("sources")
            for i in range(sources.n_children()):
                typ, ident = sources.get_child_value(i).unpack()  # (type, id)
                low = ident.lower()
                if (typ == "ibus" and "off" not in low and "xkb" not in low
                        and any(h in low for h in kana_hint)):
                    kana_engine = kana_engine or ident  # ibus id == engine name
                elif typ == "xkb" and latin_engine is None:
                    latin_engine = _resolve_xkb_engine(bus, ident)
                elif (typ == "ibus" and latin_engine is None
                        and ("off" in low or "xkb" in low)):
                    latin_engine = ident
    except Exception:
        pass

    try:
        active = bus.get_global_engine()
        original = active.get_name() if active is not None else None
    except Exception:
        original = None
    # Fall back to the engine active at open (usually latin) if no xkb source.
    if latin_engine is None:
        latin_engine = original

    def make(name):
        if not name:
            return lambda: None

        def switch():
            try:
                bus.set_global_engine(name)
            except Exception:
                pass

        return switch

    return make(kana_engine), make(latin_engine), make(original)


def show_learning(*, cards, show_translation=True, languages=("en", "de"),
                  ui_language="en", grade_fn, review_fn, speak_fn=None,
                  auto_speak=False, greeting=True, drill_repeats=5,
                  match_reading_fn=None, speak_phrase_fn=None,
                  sfx_fn=None, fanfare_fn=None, log_time_fn=None) -> int:
    def t(key):
        e = LEARN_STRINGS.get(key, {})
        return e.get(ui_language) or e.get("en") or key

    # How the drill decides a retype is correct — injected so it stays in sync
    # with the quiz's grading; a plain trimmed compare if nothing is passed.
    match_reading = match_reading_fn or (
        lambda a, b: (a or "").strip() == (b or "").strip())

    lang_names = LANG_NAMES_BY_UI.get(ui_language, LANG_NAMES_BY_UI["en"])
    status_names = STATUS_NAMES.get(ui_language, STATUS_NAMES["en"])
    total = len(cards)
    state = {"idx": 0, "score": 0, "results": []}
    app = Adw.Application(application_id="com.meeksi39.zenbuji",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        # Height follows the content (resizable=False makes the window re-fit as
        # the question / reveal / summary phases change size).
        win, card_box = make_glass_window(
            application, title="zenbuji 練習", default_size=(460, -1),
            resizable=False, draggable=True, close_on_focus_loss=False)

        if not cards:
            msg = Gtk.Label(label=t("empty"), wrap=True, xalign=0)
            msg.set_max_width_chars(36)
            card_box.append(msg)
            win.present()
            return

        # Best-effort: hiragana IME on the reading field, latin on translation;
        # put the user's original input source back when the quiz closes.
        to_kana, to_latin, restore_ime = _ime_switcher()
        win.connect("close-request", lambda *_a: (restore_ime(), False)[1])

        progress = Gtk.ProgressBar()
        progress.add_css_class("zenbuji-quiz-progress")
        card_box.append(progress)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        counter = Gtk.Label(xalign=0, hexpand=True)
        counter.add_css_class("zenbuji-score")
        score_lbl = Gtk.Label(xalign=1)
        score_lbl.add_css_class("zenbuji-score")
        status_row.append(counter)
        status_row.append(score_lbl)
        card_box.append(status_row)

        # A random casual greeting when the round opens — shown on the first
        # card, then it steps aside. Spoken too when TTS auto-read is on.
        greet_lbl = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        greet_lbl.add_css_class("zenbuji-hint")
        greet_lbl.set_max_width_chars(40)
        card_box.append(greet_lbl)
        if greeting and GREETINGS:
            hello = random.choice(GREETINGS)
            greet_lbl.set_text(hello)
            if auto_speak and speak_fn is not None:
                speak_fn(hello)
        else:
            greet_lbl.set_visible(False)

        kanji = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        kanji.add_css_class("zenbuji-kanji")
        kanji.set_max_width_chars(16)
        kanji.set_margin_top(8)
        kanji.set_margin_bottom(8)
        # The card's current SRS level, shown as a chip under the counter row.
        level_badge = Gtk.Label()
        level_badge.add_css_class("zenbuji-level")
        level_badge.set_halign(Gtk.Align.CENTER)
        level_badge.set_margin_top(2)
        card_box.append(level_badge)

        # Overlay hosts the transient celebration ribbon on a correct answer.
        kanji_overlay = Gtk.Overlay()
        kanji_overlay.set_child(kanji)
        card_box.append(kanji_overlay)

        def _animate(widget, setter, frm, to, dur, easing, on_done=None):
            """Smooth, eased property tween (see the animation note in CLAUDE.md).
            Keeps the animation referenced so it isn't GC'd mid-flight."""
            setter(frm)
            tgt = Adw.CallbackAnimationTarget.new(setter)
            anim = Adw.TimedAnimation.new(widget, frm, to, dur, tgt)
            anim.set_easing(easing)
            if on_done is not None:
                anim.connect("done", lambda *_a: on_done())
            state.setdefault("_anims", []).append(anim)  # keep refs alive
            anim.play()
            return anim

        _BANNER_FLY = 90   # px the ribbon travels as it flies in / out

        def _show_banner(levelup=False, *, text=None, style=None):
            """JRPG-style ribbon over the result on a correct answer (the same
            look as the game-helper capture banner). It flies in from the right
            to centre; `_hide_banner` flies it back out. Returns the widget.

            `text`/`style` override the default Correct/Level up ribbon so the
            same fly-in/out can carry other messages (e.g. the drill-done one)."""
            banner = Gtk.Label(label=text if text is not None else (
                t("banner_levelup") if levelup else t("banner_correct")))
            banner.add_css_class("zenbuji-ribbon")
            banner.add_css_class("zenbuji-ribbon-lg")  # SRS ribbons are double-size
            banner.add_css_class(style if style else (
                "zenbuji-ribbon-levelup" if levelup else "zenbuji-ribbon-new"))
            banner.set_halign(Gtk.Align.CENTER)
            banner.set_valign(Gtk.Align.CENTER)
            banner.set_can_target(False)
            kanji_overlay.add_overlay(banner)
            # Fly in: ease OUT (decelerate into place) — fade + slide from right.
            _animate(banner, banner.set_opacity, 0.0, 1.0, 300,
                     Adw.Easing.EASE_OUT_CUBIC)
            _animate(banner,
                     lambda v: banner.set_margin_start(max(0, int(round(v)))),
                     _BANNER_FLY, 0, 460, Adw.Easing.EASE_OUT_CUBIC)
            return banner

        def _hide_banner(banner, on_done):
            """Fly the ribbon back out (ease IN — accelerate away) then call
            `on_done` (which removes it and loads the next word)."""
            def done():
                kanji_overlay.remove_overlay(banner)
                on_done()
            _animate(banner, banner.set_opacity, 1.0, 0.0, 300,
                     Adw.Easing.EASE_IN_CUBIC)
            _animate(banner,
                     lambda v: banner.set_margin_end(max(0, int(round(v)))),
                     0, _BANNER_FLY, 300, Adw.Easing.EASE_IN_CUBIC, on_done=done)

        # Translation hint: one label per language, divided by a vrule so the
        # EN / DE glosses read as clearly separate (not run together by spaces).
        hint = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hint.set_halign(Gtk.Align.CENTER)
        hint.set_margin_top(4)
        hint.set_margin_bottom(6)
        card_box.append(hint)

        def set_hint(values):
            child = hint.get_first_child()
            while child is not None:
                hint.remove(child)
                child = hint.get_first_child()
            for i, val in enumerate(values):
                if i:
                    sep = Gtk.Box()
                    sep.add_css_class("zenbuji-vrule")
                    sep.set_margin_top(2)
                    sep.set_margin_bottom(2)
                    hint.append(sep)
                lbl = Gtk.Label(label=val)
                lbl.add_css_class("zenbuji-hint")
                hint.append(lbl)
            hint.set_visible(bool(values))

        # Phase area, rebuilt for question vs reveal vs summary.
        phase = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        phase.set_margin_top(6)
        card_box.append(phase)

        def clear_phase():
            # Unset the window's default/focus BEFORE destroying the phase
            # children. The phase holds the current default widget (the Got it /
            # Missed button); if we destroy it while the window still points at
            # it as default, GTK later dereferences the freed widget
            # (set_default_widget → remove_css_class) and segfaults — the
            # intermittent "window just closed" on confirming an answer.
            try:
                win.set_default_widget(None)
                win.set_focus(None)
            except Exception:  # noqa: BLE001
                pass
            child = phase.get_first_child()
            while child is not None:
                phase.remove(child)
                child = phase.get_first_child()

        def refresh_header():
            progress.set_fraction(state["idx"] / total)
            counter.set_text(f"{min(state['idx'] + 1, total)} / {total}")
            score_lbl.set_text(f"{t('score')} {state['score']} / {total}")

        def show_question():
            refresh_header()
            greet_lbl.set_visible(greeting and bool(GREETINGS)
                                  and state["idx"] == 0)
            cur = cards[state["idx"]]
            state["question_shown_at"] = time.monotonic()   # for answer timing
            lvl = cur.get("status") or "new"
            for l in LEVEL_ORDER:
                level_badge.remove_css_class(f"zenbuji-level-{l}")
            level_badge.add_css_class(f"zenbuji-level-{lvl}")
            level_badge.set_text(status_names.get(lvl, lvl))
            level_badge.set_visible(True)
            kanji.set_text(cur["text"])
            if show_translation:
                vals = [cur["translations"].get(l) for l in languages]
                set_hint([v for v in vals if v])
            else:
                hint.set_visible(False)

            clear_phase()

            def on_field_focus(entry, switch):
                ctl = Gtk.EventControllerFocus()
                ctl.connect("enter", lambda *_a: switch())
                entry.add_controller(ctl)

            col = _answer_col()
            phase.append(col)

            # Reading field + arrow tile fused into one search-style pill: the
            # field grows, the tile matches its height (valign FILL, no gap).
            reading_entry = Gtk.Entry(placeholder_text=t("reading"), hexpand=True)
            reading_entry.add_css_class("zenbuji-quiz-input")
            reading_entry.add_css_class("zenbuji-combo")
            reading_entry.set_alignment(0.5)
            on_field_focus(reading_entry, to_kana)

            check_btn = Gtk.Button(icon_name="go-next-symbolic")
            check_btn.add_css_class("zenbuji-action")
            check_btn.add_css_class("zenbuji-quiz-go")
            check_btn.set_valign(Gtk.Align.FILL)
            check_btn.set_tooltip_text(t("check"))

            input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            input_row.append(reading_entry)
            input_row.append(check_btn)
            col.append(input_row)

            trans_entry = None
            if not show_translation:
                trans_entry = Gtk.Entry(placeholder_text=t("translation"))
                trans_entry.add_css_class("zenbuji-quiz-input")
                trans_entry.set_alignment(0.5)
                on_field_focus(trans_entry, to_latin)
                col.append(trans_entry)

            def submit(*_a):
                show_reveal(cur, reading_entry.get_text(),
                            trans_entry.get_text() if trans_entry else "")

            reading_entry.connect("activate", submit)
            if trans_entry is not None:
                trans_entry.connect("activate", submit)
            check_btn.connect("clicked", submit)
            reading_entry.grab_focus()

        def show_reveal(cur, reading_in, translation_in):
            # Recall time = question shown -> this first answer submit (the
            # per-word speed). The total card time is taken later, at advance().
            start = state.get("question_shown_at")
            state["recall_ms"] = (round((time.monotonic() - start) * 1000)
                                  if start is not None else None)
            res = grade_fn(cur, reading_in, translation_in)
            # The reading (furigana) decides the default: "Got it" only when it
            # actually matched, otherwise "Missed" is the primary/default button.
            reading_ok = bool(res["reading_ok"])
            correct_reading = res["correct_reading"]
            if sfx_fn:
                sfx_fn("correct" if reading_ok else "error")
            clear_phase()

            # A missed reading with the drill on splits into two columns — the
            # review on the left, the retype drill on the right — so the card
            # stays wide-and-short instead of one very tall stack. Otherwise it's
            # a single centered column.
            do_drill = (not reading_ok and drill_repeats > 0
                        and bool(correct_reading))
            if do_drill:
                cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
                cols.set_halign(Gtk.Align.CENTER)
                cols.set_margin_top(4)
                phase.append(cols)
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                col.set_size_request(250, -1)
                col.set_valign(Gtk.Align.CENTER)
                vrule = Gtk.Box()
                vrule.add_css_class("zenbuji-vrule")
                drill_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                drill_col.set_size_request(250, -1)
                drill_col.set_valign(Gtk.Align.CENTER)
                cols.append(col)
                cols.append(vrule)
                cols.append(drill_col)
            else:
                col = _answer_col(width=320, spacing=10)
                phase.append(col)

            def you_row(answer):
                row = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER,
                                halign=Gtk.Align.CENTER)
                row.set_max_width_chars(40)
                row.set_text(f"{t('you')}: {answer.strip() or t('blank')}")
                row.add_css_class("zenbuji-meta")
                return row

            # 1. Verdict chip — colour carries right/wrong.
            verdict = Gtk.Label(label=f"{'✓' if reading_ok else '✗'}  "
                                      f"{t('verdict_ok') if reading_ok else t('verdict_no')}")
            verdict.add_css_class("zenbuji-verdict")
            verdict.add_css_class("zenbuji-verdict-ok" if reading_ok
                                  else "zenbuji-verdict-no")
            verdict.set_halign(Gtk.Align.CENTER)
            col.append(verdict)

            # 2. The correct reading, large and in accent, with the speak button.
            reading_label = None
            if correct_reading:
                reading_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                      spacing=6, halign=Gtk.Align.CENTER)
                rl = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
                rl.add_css_class("zenbuji-reveal-reading")
                rl.set_max_width_chars(20)
                # Whole word missed → show the kana they got right in accent and
                # mute (fade) the ones they missed; otherwise plain accent.
                accent = accent_hex(Adw.StyleManager.get_default().get_dark())
                if reading_ok or not accent:
                    rl.set_text(correct_reading)
                else:
                    rl.add_css_class("zenbuji-graded")   # base = default fg to dim
                    rl.set_markup(_reading_markup(correct_reading, reading_in,
                                                  accent))
                reading_label = rl       # toggled blurry/clear during the drill
                reading_row.append(rl)
                if speak_fn is not None:
                    speak_btn = Gtk.Button(icon_name="audio-volume-high-symbolic")
                    speak_btn.add_css_class("flat")
                    speak_btn.add_css_class("zenbuji-icon")
                    speak_btn.set_valign(Gtk.Align.CENTER)
                    speak_btn.set_tooltip_text(t("read_aloud"))
                    speak_btn.connect("clicked",
                                      lambda _b, r=correct_reading: speak_fn(r))
                    reading_row.append(speak_btn)
                col.append(reading_row)
                # Read the correct reading aloud automatically (right or wrong)
                # when TTS auto-read is enabled.
                if auto_speak and speak_fn is not None:
                    speak_fn(correct_reading)

            # 3. What the learner typed — only when the reading was wrong.
            if not reading_ok:
                col.append(you_row(reading_in))

            # 4. Translations, centered.
            for lang in languages:
                val = res["correct_translations"].get(lang)
                if not val:
                    continue
                lbl = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER,
                                halign=Gtk.Align.CENTER)
                lbl.set_max_width_chars(40)
                lbl.set_text(f"{lang_names.get(lang, lang.upper())}:  {val}")
                lbl.add_css_class("zenbuji-translation")
                col.append(lbl)
            if res["translation_ok"] is not None:
                col.append(you_row(translation_in))

            # 5a. Missed reading + drill on → retype the correct reading a few
            # times to burn it in, reading it aloud each time. Still recorded as
            # a miss; the "I was right" escape covers an over-strict grade. The
            # drill lives in its own right-hand column (built above).
            if do_drill:
                build_drill(drill_col, cur, correct_reading, reading_label,
                            accent if not reading_ok else None)
                return

            # 5b. Correct → celebrate over the result and auto-advance (no click).
            if reading_ok:
                finalize(cur, True)
                return

            # 5c. Missed (no drill) → self-grade buttons so an over-strict grade
            # can still be marked correct.
            btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                           homogeneous=True)
            btns.set_margin_top(8)
            got = Gtk.Button(label=t("got_it"))
            missed = Gtk.Button(label=t("missed"))
            got.add_css_class("zenbuji-secondary")
            missed.add_css_class("zenbuji-action")
            got.connect("clicked", lambda _b: finalize(cur, True))
            missed.connect("clicked", lambda _b: finalize(cur, False))
            btns.append(missed)
            btns.append(got)
            col.append(btns)
            missed.grab_focus()
            try:
                win.set_default_widget(missed)
            except Exception:  # noqa: BLE001 — focus alone is enough
                pass

        def build_drill(col, cur, target, reveal_reading=None, accent=None):
            """The copy-the-correction drill: retype `target` (the correct
            reading) `drill_repeats` times, each correct retype spoken aloud.

            `reveal_reading` is the furigana label in the review column: clear
            for the first rep (copy it), blurred (in place, so the layout doesn't
            jump) after each correct retype so the rest are from recall, and
            shown clearly again whenever a retype is wrong."""
            progress = {"n": 0}
            # One cached speaker for this reading: synthesise once, replay on
            # every retype (no per-retype synthesis storm / overlapping audio).
            player = speak_phrase_fn(target) if speak_phrase_fn else None

            prompt = Gtk.Label(label=t("drill_prompt"), wrap=True,
                               justify=Gtk.Justification.CENTER,
                               halign=Gtk.Align.CENTER)
            prompt.add_css_class("zenbuji-hint")
            prompt.set_max_width_chars(40)
            prompt.set_margin_top(6)
            col.append(prompt)

            counter = Gtk.Label(halign=Gtk.Align.CENTER)
            counter.add_css_class("zenbuji-score")
            counter.set_text(t("drill_progress").format(n=0, total=drill_repeats))
            col.append(counter)

            # Same fused entry+arrow pill as the question phase, kana IME on focus.
            entry = Gtk.Entry(placeholder_text=t("drill_placeholder"), hexpand=True)
            entry.add_css_class("zenbuji-quiz-input")
            entry.add_css_class("zenbuji-combo")
            entry.set_alignment(0.5)
            fctl = Gtk.EventControllerFocus()
            fctl.connect("enter", lambda *_a: to_kana())
            entry.add_controller(fctl)

            go = Gtk.Button(icon_name="go-next-symbolic")
            go.add_css_class("zenbuji-action")
            go.add_css_class("zenbuji-quiz-go")
            go.set_valign(Gtk.Align.FILL)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            row.append(entry)
            row.append(go)
            col.append(row)

            # Escape hatch for an over-strict grade — count it correct, skip on.
            override = Gtk.Button(label=t("drill_override"))
            override.add_css_class("zenbuji-secondary")
            override.set_margin_top(6)
            override.connect("clicked", lambda _b: finalize(cur, True))
            col.append(override)

            def attempt(*_a):
                typed = entry.get_text()
                if match_reading(typed, target):
                    # Stays red (from a previous miss) until they get one right.
                    counter.remove_css_class("zenbuji-wrong")
                    # Blur the furigana now they've reproduced it — the remaining
                    # reps are from memory (shown clearly again only on a slip).
                    # Drop the markup first so the blur (a transparent text
                    # colour) obscures it fully.
                    if reveal_reading is not None:
                        reveal_reading.set_text(target)
                        reveal_reading.add_css_class("zenbuji-blur")
                    if player is not None:
                        player()
                    elif speak_fn is not None:
                        speak_fn(target)
                    progress["n"] += 1
                    counter.set_text(t("drill_progress").format(
                        n=progress["n"], total=drill_repeats))
                    entry.set_text("")
                    if progress["n"] >= drill_repeats:
                        # Drill cleared — the slash caps it off and the accent
                        # "Drill done!!" ribbon flies in (paced to the slash).
                        if sfx_fn:
                            sfx_fn("sword")
                        finalize(cur, False, drill_done=True)
                        return
                    if sfx_fn:
                        sfx_fn("correct")
                    entry.grab_focus()
                else:
                    # Slipped: flash the counter, reveal the reading again with
                    # this attempt's mistakes in accent (right kana stay plain),
                    # clear the box, and keep focus. No increment.
                    if sfx_fn:
                        sfx_fn("error")
                    counter.add_css_class("zenbuji-wrong")
                    if reveal_reading is not None:
                        reveal_reading.remove_css_class("zenbuji-blur")
                        if accent:
                            reveal_reading.set_markup(
                                _reading_markup(target, typed, accent))
                    entry.set_text("")
                    entry.grab_focus()

            entry.connect("activate", attempt)
            go.connect("clicked", attempt)
            entry.grab_focus()
            try:
                win.set_default_widget(go)
            except Exception:  # noqa: BLE001 — focus alone is enough
                pass

        def finalize(cur, correct, *, drill_done=False):
            old_status = cur.get("status", "")
            info = review_fn(cur["text"], correct, state.get("recall_ms")) or {}
            state["recall_ms"] = None        # consume so it can't double-count
            new_status = info.get("status", old_status)
            leveled_up = (correct
                          and _level_rank(new_status) > _level_rank(old_status))
            state["results"].append({
                "text": cur["text"],
                "correct": correct,
                "status": new_status,
                "leveled_up": leveled_up,
            })
            state["idx"] += 1

            def advance():
                # Full time on this card (question -> moving on, incl. reveal /
                # drill) feeds the cumulative learning-time total.
                start = state.pop("question_shown_at", None)
                if start is not None and log_time_fn is not None:
                    try:
                        log_time_fn(round((time.monotonic() - start) * 1000))
                    except Exception:  # noqa: BLE001 — timing must never break
                        pass
                if state["idx"] < total:
                    show_question()
                else:
                    show_summary()

            if correct or drill_done:
                # Celebrate: ribbon flies in, holds a beat, flies out, next word.
                # (The pass/fail chime / sword slash already fired at grade time.)
                if correct:
                    state["score"] += 1
                    banner = _show_banner(leveled_up)
                else:
                    # Finished the retype drill: accent ribbon, same motion,
                    # announced in the fanfare voice as it flies in (like 新規ゲット).
                    banner = _show_banner(text=t("banner_drill"),
                                          style="zenbuji-ribbon-drill")
                    if fanfare_fn:
                        fanfare_fn(_DRILL_DONE_VOICE)

                def _out():
                    if win.get_mapped():       # window not closed during the hold
                        _hide_banner(banner,
                                     lambda: win.get_mapped() and advance())
                    return GLib.SOURCE_REMOVE

                GLib.timeout_add(_BANNER_HOLD_MS, _out)
            else:
                advance()                       # missed → straight on, no banner

        def show_summary():
            progress.set_fraction(1.0)
            counter.set_text(f"{total} / {total}")
            score_lbl.set_text(f"{t('score')} {state['score']} / {total}")
            kanji.set_text(t("done"))
            hint.set_visible(False)
            level_badge.set_visible(False)
            n_up = sum(1 for r in state["results"] if r.get("leveled_up"))
            # A random casual goodbye to send you off (spoken too, if enabled).
            if greeting and FAREWELLS:
                bye = random.choice(FAREWELLS)
                greet_lbl.set_text(bye)
                greet_lbl.set_visible(True)
                if auto_speak and speak_fn is not None:
                    speak_fn(bye)
            clear_phase()

            # Grows with content up to a cap, then scrolls — keeps height dynamic.
            scroll = Gtk.ScrolledWindow()
            scroll.add_css_class("zenbuji-dict-scroll")
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_propagate_natural_width(False)
            scroll.set_propagate_natural_height(True)
            scroll.set_max_content_height(280)
            lst = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            for r in state["results"]:
                line = Gtk.Label(xalign=0, wrap=True, halign=Gtk.Align.START)
                line.set_max_width_chars(40)
                mark = "✓" if r["correct"] else "✗"
                stname = status_names.get(r["status"], r["status"])
                up = "  ⬆" if r.get("leveled_up") else ""
                line.set_text(f"{mark}  {r['text']}   ·   {stname}{up}")
                line.add_css_class("zenbuji-correct" if r["correct"]
                                   else "zenbuji-wrong")
                lst.append(line)
            scroll.set_child(lst)
            phase.append(scroll)

            # Celebrate any cards that graduated a level this round.
            if n_up:
                up_lbl = Gtk.Label(label=f"⬆ {t('leveled_up').format(n=n_up)}",
                                   justify=Gtk.Justification.CENTER)
                up_lbl.add_css_class("zenbuji-levelup-note")
                up_lbl.set_halign(Gtk.Align.CENTER)
                up_lbl.set_margin_top(4)
                phase.append(up_lbl)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          homogeneous=True)
            again = Gtk.Button(label=t("again"))
            again.add_css_class("zenbuji-action")
            again.connect("clicked", lambda _b: (_spawn_learn(), win.close()))
            stats = Gtk.Button(label=t("view_stats"))
            stats.add_css_class("zenbuji-secondary")
            stats.connect("clicked", lambda _b: (_spawn_stats(), win.close()))
            close = Gtk.Button(label=t("close"))
            close.add_css_class("zenbuji-secondary")
            close.connect("clicked", lambda _b: win.close())
            row.append(close)
            row.append(stats)
            row.append(again)
            phase.append(row)

            # The summary is built right where the just-confirmed "Got it" button
            # stood, and clear_phase() dropped the stale default/focus. Briefly
            # disable the buttons so the keypress that confirmed the last card
            # can't carry straight into one of them; once armed, make "Practice
            # again" the default so Enter starts a fresh round.
            for b in (close, stats, again):
                b.set_sensitive(False)

            def _arm_buttons():
                for b in (close, stats, again):
                    b.set_sensitive(True)
                again.grab_focus()
                try:
                    win.set_default_widget(again)   # Enter -> start a new round
                except Exception:  # noqa: BLE001 — focus alone is enough
                    pass
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(350, _arm_buttons)

        show_question()
        win.present()

    app.connect("activate", on_activate)
    return app.run([])
