#!/usr/bin/env python3
"""GTK4 popup window for zenbuji results.

Shows the original text (editable, so OCR/selection mistakes can be fixed and
re-looked-up), a full hiragana reading, a per-word breakdown, and the configured
translations. Closes on Escape, so it behaves like a quick lookup overlay
triggered from a hotkey.

Lookups (and OCR) run in a background thread with a spinner, so the window stays
responsive and appears immediately even while the OCR model loads.
"""

from __future__ import annotations

import html
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

# Target-language section labels, shown in the interface language.
LANG_NAMES_BY_UI = {
    "en": {"en": "English", "de": "Deutsch", "ja": "日本語"},
    "ja": {"en": "英語", "de": "ドイツ語", "ja": "日本語"},
}

# UI chrome strings, by interface language. Target-language section labels
# (LANG_NAMES) are intentionally left in their own language.
UI_STRINGS = {
    "placeholder":   {"en": "Japanese text…",        "ja": "日本語のテキスト…"},
    "look_up":       {"en": "Look up",               "ja": "調べる"},
    "copy":          {"en": "Copy",                  "ja": "コピー"},
    "looking_up":    {"en": "Looking up…",           "ja": "検索中…"},
    "recognising":   {"en": "Recognising…",          "ja": "認識中…"},
    "lookup_failed": {"en": "Lookup failed.",        "ja": "検索に失敗しました。"},
    "no_text":       {"en": "No text recognised.",   "ja": "テキストを認識できませんでした。"},
}


def _make_tr(ui_language):
    """Return a translator t(key) for the given interface language."""
    def t(key):
        entry = UI_STRINGS.get(key, {})
        return entry.get(ui_language) or entry.get("en") or key
    return t

# Apple-style frosted glass. The window surface is fully transparent; the
# `.zenbuji-card` is a translucent, rounded, hairline-bordered panel. Real blur
# behind the transparent card is provided by GNOME's Blur My Shell "Applications"
# component (the card's radius tracks its corner-radius, ~15px). Without it the
# card simply degrades to a clean translucent panel.
CSS = b"""
window.zenbuji-window { background-color: transparent; box-shadow: none; }
.zenbuji-window windowhandle { background-color: transparent; }

.zenbuji-card {
    border-radius: 15px;
    padding: 18px 18px 16px 18px;
    background-image: linear-gradient(to bottom,
        alpha(#ffffff, 0.06), alpha(#ffffff, 0.0));
}
.zenbuji-card.dark {
    background-color: rgba(34, 34, 38, 0.55);
    color: #f2f2f7;
    border: 1px solid rgba(255, 255, 255, 0.12);
}
.zenbuji-card.light {
    background-color: rgba(250, 250, 252, 0.66);
    color: #1c1c1e;
    border: 1px solid rgba(255, 255, 255, 0.55);
}

.zenbuji-lookup { border-radius: 10px; font-weight: 600; }

.zenbuji-hairline { min-height: 1px; background-color: alpha(currentColor, 0.12); }

.zenbuji-original { font-size: 20px; font-weight: 600; }
.zenbuji-reading  { font-size: 15px; color: alpha(currentColor, 0.7); }
.zenbuji-token-kanji { font-size: 15px; }
.zenbuji-lang-label { font-weight: 700; opacity: 0.55; font-size: 11px;
    letter-spacing: 0.04em; }
.zenbuji-translation { font-size: 15px; }
.zenbuji-note { font-size: 11px; opacity: 0.6; font-style: italic; }
.zenbuji-status { font-size: 12px; opacity: 0.7; }
"""


def _ruby_markup(tokens) -> str:
    """Build Pango markup approximating furigana: reading shown small in-line."""
    parts = []
    for t in tokens:
        surf = html.escape(t.surface)
        if t.has_kanji and t.reading and t.reading != t.surface:
            rd = html.escape(t.reading)
            parts.append(f"{surf}<span size='x-small'> [{rd}]</span>")
        else:
            parts.append(surf)
    return "".join(parts)


def _copy_row(window, label_widget, text, copy_label="Copy"):
    """Wrap a label in a row with a flat copy-to-clipboard button."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    label_widget.set_hexpand(True)
    row.append(label_widget)
    btn = Gtk.Button(icon_name="edit-copy-symbolic")
    btn.add_css_class("flat")
    btn.set_valign(Gtk.Align.START)
    btn.set_tooltip_text(copy_label)
    btn.connect("clicked", lambda _b: window.get_clipboard().set(text))
    row.append(btn)
    return row


def show_popup(languages, *, result=None, ocr_image=None,
               process_fn=None, ocr_fn=None, ui_language="en",
               close_on_focus_loss=True) -> int:
    """Display the popup.

    Exactly one of `result` (already-processed) or `ocr_image` (recognise text
    asynchronously) seeds the window. `process_fn(text) -> Result` runs a fresh
    lookup when the text is edited; `ocr_fn(path) -> (text, notes)` does OCR.
    `ui_language` ("en"/"ja") selects the interface language.
    `close_on_focus_loss` dismisses the window when it stops being the active
    window (HUD-style); set False to keep it open until Escape/closed.
    """
    t = _make_tr(ui_language)
    lang_names = LANG_NAMES_BY_UI.get(ui_language, LANG_NAMES_BY_UI["en"])
    app = Adw.Application(application_id="com.meeksi39.zenbuji")

    def on_activate(application):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )

        win = Gtk.ApplicationWindow(application=application)
        win.set_title("zenbuji 全部字")
        win.set_default_size(460, -1)
        win.set_decorated(False)   # headerless floating overlay
        win.set_resizable(False)
        win.add_css_class("zenbuji-window")  # transparent surface (see CSS)

        # The frosted glass card is the only visible surface; padding lives in CSS.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("zenbuji-card")

        # Tint follows the system light/dark scheme, live.
        style_mgr = Adw.StyleManager.get_default()

        def apply_scheme(*_a):
            box.remove_css_class("dark")
            box.remove_css_class("light")
            box.add_css_class("dark" if style_mgr.get_dark() else "light")

        apply_scheme()
        style_mgr.connect("notify::dark", apply_scheme)

        # WindowHandle lets the headerless card be dragged; child widgets (entry,
        # buttons) keep working normally.
        handle = Gtk.WindowHandle()
        handle.set_child(box)
        win.set_child(handle)

        # --- Editable input row ------------------------------------------- //
        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        entry = Gtk.Entry(hexpand=True, placeholder_text=t("placeholder"))
        entry.add_css_class("zenbuji-original")
        lookup_btn = Gtk.Button(label=t("look_up"))
        lookup_btn.add_css_class("suggested-action")
        lookup_btn.add_css_class("zenbuji-lookup")
        lookup_btn.set_valign(Gtk.Align.CENTER)
        input_row.append(entry)
        input_row.append(lookup_btn)
        box.append(input_row)

        # --- Busy / status row -------------------------------------------- //
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        spinner = Gtk.Spinner()
        status_label = Gtk.Label(xalign=0, wrap=True)
        status_label.add_css_class("zenbuji-status")
        status_row.append(spinner)
        status_row.append(status_label)
        status_row.set_visible(False)
        box.append(status_row)

        hairline = Gtk.Box()
        hairline.add_css_class("zenbuji-hairline")
        hairline.set_margin_top(2)
        hairline.set_margin_bottom(2)
        box.append(hairline)

        # --- Result area (rebuilt on each lookup) ------------------------- //
        result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(result_box)

        def set_busy(message):
            status_label.set_text(message)
            status_row.set_visible(True)
            spinner.set_visible(True)
            spinner.start()

        def clear_busy(message=None):
            spinner.stop()
            spinner.set_visible(False)
            if message:
                status_label.set_text(message)
                status_row.set_visible(True)
            else:
                status_row.set_visible(False)

        def clear_results():
            child = result_box.get_first_child()
            while child is not None:
                result_box.remove(child)
                child = result_box.get_first_child()

        def render(res):
            clear_results()
            if res.reading and res.reading != res.text:
                reading = Gtk.Label(label=res.reading, wrap=True, xalign=0,
                                    selectable=True)
                reading.add_css_class("zenbuji-reading")
                result_box.append(_copy_row(win, reading, res.reading, t("copy")))

            if any(getattr(t, "has_kanji", False) for t in res.tokens):
                ruby = Gtk.Label(wrap=True, xalign=0, selectable=True)
                ruby.set_markup(_ruby_markup(res.tokens))
                ruby.add_css_class("zenbuji-token-kanji")
                result_box.append(ruby)

            for lang in languages:
                val = res.translations.get(lang)
                lbl = Gtk.Label(label=lang_names.get(lang, lang.upper()), xalign=0)
                lbl.add_css_class("zenbuji-lang-label")
                result_box.append(lbl)
                tr = Gtk.Label(label=val if val else "—", wrap=True, xalign=0,
                               selectable=True)
                tr.add_css_class("zenbuji-translation")
                if val:
                    result_box.append(_copy_row(win, tr, val, t("copy")))
                else:
                    result_box.append(tr)

            for note in res.notes:
                n = Gtk.Label(label=note, wrap=True, xalign=0)
                n.add_css_class("zenbuji-note")
                result_box.append(n)

        # --- Lookup (threaded) -------------------------------------------- //
        def do_lookup(text):
            text = text.strip()
            if not text or process_fn is None:
                return
            set_busy(t("looking_up"))

            def work():
                try:
                    res = process_fn(text)
                    err = None
                except Exception as exc:  # noqa: BLE001
                    res, err = None, f"{exc}"
                GLib.idle_add(finish, res, err)

            threading.Thread(target=work, daemon=True).start()

        def finish(res, err):
            if res is None:
                clear_busy(err or t("lookup_failed"))
            else:
                clear_busy()
                render(res)
            return GLib.SOURCE_REMOVE

        def run_ocr(image):
            set_busy(t("recognising"))

            def work():
                try:
                    text, notes = ocr_fn(image)
                except Exception as exc:  # noqa: BLE001
                    text, notes = "", [f"{exc}"]
                GLib.idle_add(ocr_finish, text, notes)

            threading.Thread(target=work, daemon=True).start()

        def ocr_finish(text, notes):
            entry.set_text(text)
            if text.strip():
                do_lookup(text)
            else:
                clear_busy(notes[0] if notes else t("no_text"))
            return GLib.SOURCE_REMOVE

        entry.connect("activate", lambda _e: do_lookup(entry.get_text()))
        lookup_btn.connect("clicked", lambda _b: do_lookup(entry.get_text()))

        # Close on Escape.
        key = Gtk.EventControllerKey()

        def on_key(_ctrl, keyval, _code, _state):
            if keyval == Gdk.KEY_Escape:
                win.close()
                return True
            return False

        key.connect("key-pressed", on_key)
        win.add_controller(key)

        # Optionally dismiss when the window loses focus (overlay/HUD behaviour).
        # Dragging the headerless window starts a compositor move that briefly
        # deactivates it — so we must NOT treat a deactivation that happens while
        # the pointer is pressed *inside* the window as a focus switch, or the
        # window would close the instant you try to drag it.
        if close_on_focus_loss:
            focus_state = {"was_active": False, "interacting": False}

            def clear_interacting():
                focus_state["interacting"] = False
                return GLib.SOURCE_REMOVE

            def on_active_changed(*_a):
                if win.is_active():
                    focus_state["was_active"] = True
                    focus_state["interacting"] = False  # regained focus
                elif focus_state["was_active"] and not focus_state["interacting"]:
                    win.close()

            win.connect("notify::is-active", on_active_changed)

            # Passive observer (returns False → never consumes events, so clicks,
            # drags and text selection all keep working). CAPTURE phase so it sees
            # the press before a child or the WindowHandle does.
            watcher = Gtk.EventControllerLegacy()
            watcher.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

            def on_event(controller, *_a):
                event = controller.get_current_event()
                if event is None:
                    return False
                et = event.get_event_type()
                if et == Gdk.EventType.BUTTON_PRESS:
                    focus_state["interacting"] = True
                elif et == Gdk.EventType.BUTTON_RELEASE:
                    GLib.timeout_add(150, clear_interacting)
                return False

            watcher.connect("event", on_event)
            win.add_controller(watcher)

        win.present()

        # Seed the window.
        if ocr_image is not None:
            run_ocr(ocr_image)
        elif result is not None:
            entry.set_text(result.text)
            render(result)
            entry.grab_focus()
        else:
            entry.grab_focus()

    app.connect("activate", on_activate)
    return app.run([])
