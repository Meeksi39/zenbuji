#!/usr/bin/env python3
"""GTK4 frosted-glass learning window — spaced-repetition quiz over the cache.

Shows a cached word as large kanji (no furigana); the learner types the reading
and (unless the translation is given as a hint) the translation. The answer is
graded, the correct reading/translation is revealed, the learner confirms the
result (self-grade override), and that feeds the SRS schedule. A progress bar
tracks the round and a summary lists each word's new learning status.

All data/grading logic is injected by `launch_learning` in zenbuji.py:
`grade_fn(card, reading, translation)` and `review_fn(text, correct)`.
"""

from __future__ import annotations

import random
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

LANG_NAMES_BY_UI = {
    "en": {"en": "English", "de": "Deutsch", "ja": "日本語"},
    "ja": {"en": "英語", "de": "ドイツ語", "ja": "日本語"},
}

LEARN_STRINGS = {
    "title":        {"en": "Practice",        "ja": "練習"},
    "reading":      {"en": "Reading (furigana)…", "ja": "読み（ふりがな）…"},
    "translation":  {"en": "Translation (EN / DE)…", "ja": "翻訳（英 / 独）…"},
    "check":        {"en": "Check",           "ja": "確認"},
    "got_it":       {"en": "✓ Got it",        "ja": "✓ 正解"},
    "missed":       {"en": "✗ Missed",        "ja": "✗ 不正解"},
    "reading_lbl":  {"en": "Reading",         "ja": "読み"},
    "read_aloud":   {"en": "Read aloud",      "ja": "読み上げる"},
    "you":          {"en": "You typed",       "ja": "あなたの入力"},
    "blank":        {"en": "(blank)",         "ja": "（空欄）"},
    "score":        {"en": "Score",           "ja": "スコア"},
    "done":         {"en": "Done!",           "ja": "完了！"},
    "again":        {"en": "Practice again",  "ja": "もう一度"},
    "close":        {"en": "Close",           "ja": "閉じる"},
    "empty":        {"en": "No words to practise yet — look up some Japanese first.",
                     "ja": "練習する単語がありません。まず日本語を調べてください。"},
}

STATUS_NAMES = {
    "en": {"new": "New", "learning": "Learning", "young": "Young", "mature": "Mature"},
    "ja": {"new": "新規", "learning": "学習中", "young": "定着中", "mature": "習得"},
}

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
    cli = str(Path(__file__).resolve().parent / "zenbuji.py")
    try:
        subprocess.Popen([sys.executable, cli, "learn"], start_new_session=True)
    except OSError:
        pass


_SOUND_CTX = None


def _play_correct_sound():
    """Play the freedesktop 'bell' chime via GSound (no-op if unavailable)."""
    global _SOUND_CTX
    if _SOUND_CTX is False:
        return
    try:
        if _SOUND_CTX is None:
            gi.require_version("GSound", "1.0")
            from gi.repository import GSound
            ctx = GSound.Context()
            ctx.init()
            _SOUND_CTX = ctx
        _SOUND_CTX.play_simple({"event.id": "bell"}, None)
    except Exception:  # noqa: BLE001  (no sound server / GSound missing)
        _SOUND_CTX = False


def show_learning(*, cards, show_translation=True, languages=("en", "de"),
                  ui_language="en", grade_fn, review_fn, speak_fn=None,
                  auto_speak=False, greeting=True) -> int:
    def t(key):
        e = LEARN_STRINGS.get(key, {})
        return e.get(ui_language) or e.get("en") or key

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

        progress = Gtk.ProgressBar()
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
        # Overlay hosts the transient celebration mark on a correct answer.
        kanji_overlay = Gtk.Overlay()
        kanji_overlay.set_child(kanji)
        card_box.append(kanji_overlay)

        def celebrate():
            _play_correct_sound()
            mark = Gtk.Label(label="✓")
            mark.add_css_class("zenbuji-celebrate")
            mark.set_halign(Gtk.Align.CENTER)
            mark.set_valign(Gtk.Align.CENTER)
            mark.set_can_target(False)
            kanji_overlay.add_overlay(mark)
            target = Adw.CallbackAnimationTarget.new(lambda v: mark.set_opacity(v))
            anim = Adw.TimedAnimation.new(mark, 1.0, 0.0, 700, target)
            anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)
            anim.connect("done", lambda *_a: kanji_overlay.remove_overlay(mark))
            state["_anim"] = anim  # keep a ref so it isn't GC'd mid-play
            anim.play()

        hint = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        hint.add_css_class("zenbuji-hint")
        hint.set_max_width_chars(40)
        card_box.append(hint)

        # Phase area, rebuilt for question vs reveal vs summary.
        phase = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        phase.set_margin_top(6)
        card_box.append(phase)

        def clear_phase():
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
            kanji.set_text(cur["text"])
            if show_translation:
                vals = [cur["translations"].get(l) for l in languages]
                hint.set_text("   ".join(v for v in vals if v))
                hint.set_visible(True)
            else:
                hint.set_visible(False)

            clear_phase()
            reading_entry = Gtk.Entry(placeholder_text=t("reading"))
            phase.append(reading_entry)
            trans_entry = None
            if not show_translation:
                trans_entry = Gtk.Entry(placeholder_text=t("translation"))
                phase.append(trans_entry)
            check_btn = Gtk.Button(label=t("check"))
            check_btn.add_css_class("zenbuji-action")
            phase.append(check_btn)

            def submit(*_a):
                show_reveal(cur, reading_entry.get_text(),
                            trans_entry.get_text() if trans_entry else "")

            reading_entry.connect("activate", submit)
            if trans_entry is not None:
                trans_entry.connect("activate", submit)
            check_btn.connect("clicked", submit)
            reading_entry.grab_focus()

        def show_reveal(cur, reading_in, translation_in):
            res = grade_fn(cur, reading_in, translation_in)
            # The reading (furigana) decides the default: "Got it" only when it
            # actually matched, otherwise "Missed" is the primary/default button.
            reading_ok = bool(res["reading_ok"])
            clear_phase()

            def verdict_row(label_text, ok, answer):
                row = Gtk.Label(xalign=0, wrap=True, halign=Gtk.Align.START)
                row.set_max_width_chars(40)
                mark = "✓" if ok else "✗"
                row.set_text(f"{mark}  {label_text}: {answer}")
                row.add_css_class("zenbuji-correct" if ok else "zenbuji-wrong")
                return row

            def you_row(answer):
                row = Gtk.Label(xalign=0, wrap=True, halign=Gtk.Align.START)
                row.set_max_width_chars(40)
                row.set_text(f"{t('you')}: {answer.strip() or t('blank')}")
                row.add_css_class("zenbuji-meta")
                return row

            correct_reading = res["correct_reading"]
            if speak_fn is not None and correct_reading:
                reading_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                      spacing=6)
                vr = verdict_row(t("reading_lbl"), res["reading_ok"],
                                 correct_reading)
                vr.set_hexpand(True)
                reading_row.append(vr)
                speak_btn = Gtk.Button(icon_name="audio-volume-high-symbolic")
                speak_btn.add_css_class("flat")
                speak_btn.set_valign(Gtk.Align.CENTER)
                speak_btn.set_tooltip_text(t("read_aloud"))
                speak_btn.connect("clicked",
                                  lambda _b, r=correct_reading: speak_fn(r))
                reading_row.append(speak_btn)
                phase.append(reading_row)
            else:
                phase.append(verdict_row(t("reading_lbl"), res["reading_ok"],
                                         correct_reading))
            # Read the correct reading aloud automatically (right or wrong) when
            # TTS auto-read is enabled.
            if auto_speak and speak_fn is not None and correct_reading:
                speak_fn(correct_reading)
            phase.append(you_row(reading_in))
            for lang in languages:
                val = res["correct_translations"].get(lang)
                if not val:
                    continue
                lbl = Gtk.Label(xalign=0, wrap=True)
                lbl.set_max_width_chars(40)
                lbl.set_text(f"{lang_names.get(lang, lang.upper())}: {val}")
                lbl.add_css_class("zenbuji-translation")
                phase.append(lbl)
            # When the translation was tested, show what the user typed too.
            if res["translation_ok"] is not None:
                phase.append(you_row(translation_in))

            btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                           homogeneous=True)
            btns.set_margin_top(6)
            got = Gtk.Button(label=t("got_it"))
            missed = Gtk.Button(label=t("missed"))
            # Whichever matches the reading result is the primary/default button.
            (got if reading_ok else missed).add_css_class("zenbuji-action")
            (missed if reading_ok else got).add_css_class("zenbuji-secondary")
            got.connect("clicked", lambda _b: finalize(cur, True))
            missed.connect("clicked", lambda _b: finalize(cur, False))
            btns.append(missed)
            btns.append(got)
            phase.append(btns)
            default_btn = got if reading_ok else missed
            default_btn.grab_focus()
            try:
                win.set_default_widget(default_btn)
            except Exception:  # noqa: BLE001 — focus alone is enough
                pass

        def finalize(cur, correct):
            info = review_fn(cur["text"], correct) or {}
            if correct:
                state["score"] += 1
                celebrate()
            state["results"].append({
                "text": cur["text"],
                "correct": correct,
                "status": info.get("status", cur.get("status", "")),
            })
            state["idx"] += 1
            if state["idx"] < total:
                show_question()
            else:
                show_summary()

        def show_summary():
            progress.set_fraction(1.0)
            counter.set_text(f"{total} / {total}")
            score_lbl.set_text(f"{t('score')} {state['score']} / {total}")
            kanji.set_text(t("done"))
            hint.set_visible(False)
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
                line.set_text(f"{mark}  {r['text']}   ·   {stname}")
                line.add_css_class("zenbuji-correct" if r["correct"]
                                   else "zenbuji-wrong")
                lst.append(line)
            scroll.set_child(lst)
            phase.append(scroll)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          homogeneous=True)
            again = Gtk.Button(label=t("again"))
            again.add_css_class("zenbuji-action")
            again.connect("clicked", lambda _b: (_spawn_learn(), win.close()))
            close = Gtk.Button(label=t("close"))
            close.add_css_class("zenbuji-secondary")
            close.connect("clicked", lambda _b: win.close())
            row.append(close)
            row.append(again)
            phase.append(row)

        show_question()
        win.present()

    app.connect("activate", on_activate)
    return app.run([])
