#!/usr/bin/env python3
"""Shared frosted-glass window scaffolding for zenbuji's GTK surfaces.

Both the lookup popup and the dictionary window are Apple-style translucent
cards: the GTK window surface is fully transparent and a `.zenbuji-card` draws a
rounded, hairline-bordered, semi-transparent panel. Real blur behind the card is
supplied by GNOME's Blur My Shell "Applications" component (the card radius
tracks its ~15px corner radius); without it the card degrades to a clean
translucent panel.

The CSS provider must be installed at USER priority and the window background
cleared with an *element-qualified* selector (`window.zenbuji-window`), otherwise
the theme's opaque window background wins and the surface never goes transparent.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

GLASS_CSS = b"""
window.zenbuji-window { background-color: transparent; box-shadow: none; }
.zenbuji-window windowhandle { background-color: transparent; }

.zenbuji-card {
    border-radius: 15px;
    padding: 18px 18px 16px 18px;
    background-image: linear-gradient(to bottom,
        alpha(#ffffff, 0.06), alpha(#ffffff, 0.0));
    /* Crisp glass rim for edge contrast on any background. An *outer* drop
       shadow can't be used: Blur My Shell would blur the transparent margin it
       needs into a halo. Instead a dark 1px border defines the edge against
       bright backgrounds and an inset light hairline defines it against dark
       ones -- both render inside the window, so nothing is clipped/blurred. */
    box-shadow: inset 0 0 0 1px alpha(#ffffff, 0.10),
                inset 0 1px 0 0 alpha(#ffffff, 0.22);
}
.zenbuji-card.dark {
    background-color: rgba(34, 34, 38, 0.58);
    color: #f2f2f7;
    border: 1px solid rgba(0, 0, 0, 0.55);
}
.zenbuji-card.light {
    background-color: rgba(250, 250, 252, 0.68);
    color: #1c1c1e;
    border: 1px solid rgba(0, 0, 0, 0.22);
}

.zenbuji-hairline { min-height: 1px; background-color: alpha(currentColor, 0.12); }

/* --- buttons: Apple-style glass --- */
/* Soft, padded pills so the controls feel friendly across every window. */
/* Primary action: filled with the system accent. */
.zenbuji-action {
    border-radius: 12px;
    padding: 7px 16px;
    min-height: 18px;
    font-weight: 700;
    border: none;
    color: @accent_fg_color;
    /* A vivid gradient + a real drop shadow (plus a faint accent glow) so the
       primary action has depth and pops without being oversized. */
    background-color: @accent_bg_color;
    background-image: linear-gradient(to bottom,
        shade(@accent_bg_color, 1.16), @accent_bg_color);
    box-shadow: 0 3px 8px alpha(#000000, 0.28), 0 1px 2px alpha(@accent_bg_color, 0.5);
}
.zenbuji-action:hover {
    background-image: linear-gradient(to bottom,
        shade(@accent_bg_color, 1.24), shade(@accent_bg_color, 1.07));
    box-shadow: 0 5px 12px alpha(#000000, 0.34), 0 1px 2px alpha(@accent_bg_color, 0.5);
}
.zenbuji-action:active {
    background-image: none;
    background-color: shade(@accent_bg_color, 0.94);
    box-shadow: 0 1px 2px alpha(#000000, 0.22);
}
/* Secondary: translucent glass. */
.zenbuji-secondary {
    border-radius: 12px;
    padding: 7px 16px;
    min-height: 18px;
    font-weight: 500;
    background-image: none;
    background-color: alpha(currentColor, 0.10);
    border: 1px solid alpha(currentColor, 0.14);
}
.zenbuji-secondary:hover { background-color: alpha(currentColor, 0.16); }
/* Explicit pressed state: a faint translucent fill keeps the text (currentColor
   / danger red) readable, instead of the theme's default solid active fill. */
.zenbuji-secondary:active,
.zenbuji-secondary:checked { background-color: alpha(currentColor, 0.24); }
/* Flat icon buttons: neutral by default so dense rows stay calm, accent on
   hover. Destructive stays red so delete reads clearly. */
.zenbuji-icon { color: alpha(currentColor, 0.45); }
.zenbuji-icon:hover { color: @accent_color; }
.zenbuji-icon-danger { color: #e01b24; }

/* Default text inputs (popup / dict search): subtle translucent fields that sit
   quietly on the glass. */
.zenbuji-card entry, .zenbuji-card entry.search {
    border-radius: 11px;
    padding: 7px 12px;
    min-height: 22px;
    background-image: none;
    background-color: alpha(currentColor, 0.06);
    border: 1px solid alpha(currentColor, 0.12);
    box-shadow: none;
}
.zenbuji-card entry:focus-within {
    border-color: @accent_color;
    background-color: alpha(currentColor, 0.09);
}

/* The quiz answer field is the one "type here" hero: a larger, near-white card
   with dark text and a bold accent focus ring, so it pops against the glass. */
.zenbuji-card entry.zenbuji-quiz-input {
    font-size: 19px;
    padding: 13px 18px;
    border-radius: 14px;
    background-color: rgba(255, 255, 255, 0.97);
    color: #1c1c1e;
    border: 1px solid alpha(#000000, 0.10);
    box-shadow: 0 1px 3px alpha(#000000, 0.10);
}
.zenbuji-card entry.zenbuji-quiz-input text {
    color: #1c1c1e; caret-color: #1c1c1e;
}
.zenbuji-card entry.zenbuji-quiz-input text > placeholder {
    color: alpha(#1c1c1e, 0.40);
}
.zenbuji-card entry.zenbuji-quiz-input:focus-within {
    border-color: @accent_color;
    box-shadow: 0 0 0 3px alpha(@accent_color, 0.30), 0 1px 3px alpha(#000000, 0.10);
}
/* When the field is fused with the arrow tile into one pill: square the seam
   side and drop the focus ring so the two read as a single control. */
.zenbuji-card entry.zenbuji-quiz-input.zenbuji-combo {
    border-top-right-radius: 0; border-bottom-right-radius: 0;
    border-right-width: 0;
}
.zenbuji-card entry.zenbuji-quiz-input.zenbuji-combo:focus-within {
    box-shadow: 0 1px 3px alpha(#000000, 0.10);
    border-color: @accent_color;
}

/* --- shared text styles (popup + dictionary) --- */
.zenbuji-original { font-size: 20px; font-weight: 600; }
.zenbuji-reading  { font-size: 15px; color: @accent_color; }
.zenbuji-ocr-image { border-radius: 10px; }
.zenbuji-token-kanji { font-size: 15px; }
.zenbuji-lang-label { font-weight: 700; opacity: 0.55; font-size: 11px;
    letter-spacing: 0.04em; }
.zenbuji-translation { font-size: 15px; }
.zenbuji-note { font-size: 11px; opacity: 0.6; font-style: italic; }
.zenbuji-status { font-size: 12px; opacity: 0.7; }
.zenbuji-quota { font-size: 11px; opacity: 0.55; }

/* --- dictionary window --- */
.zenbuji-title { font-size: 17px; font-weight: 700; }
.zenbuji-dict-jp { font-size: 16px; font-weight: 600; }
.zenbuji-count { font-size: 11px; font-weight: 700; opacity: 0.6; }
.zenbuji-meta { font-size: 10px; opacity: 0.5; }
.zenbuji-dict-list { background: transparent; }
.zenbuji-dict-list > row { background: transparent; border-radius: 8px; }
.zenbuji-excluded { opacity: 0.45; }  /* word excluded from practice */

/* --- game helper --- */
/* Keyboard-shortcut chip. */
.zenbuji-kbd {
    font-size: 12px; font-weight: 700;
    padding: 2px 9px; border-radius: 7px;
    background-color: alpha(currentColor, 0.10);
    border: 1px solid alpha(currentColor, 0.12);
}
/* Smaller chip for the compact footer. */
.zenbuji-kbd-sm {
    font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 6px;
    background-color: alpha(currentColor, 0.10);
    border: 1px solid alpha(currentColor, 0.12);
}
.zenbuji-busy { font-size: 12px; color: @accent_color; }
/* Box around the newest entry in the game overlay (the latest translation):
   roomy padding + a larger, easier-to-read type scale. */
/* The newest entry wears a gold, LEVEL-UP-style champion box. */
.zenbuji-latest {
    border: 2px solid #f5c211;
    border-radius: 12px;
    background-image: linear-gradient(to bottom,
        alpha(#ffd84a, 0.20), alpha(#f5c211, 0.08));
    padding: 10px 14px;
    box-shadow: 0 0 18px alpha(#f5c211, 0.50);
}
.zenbuji-latest .zenbuji-dict-jp { font-size: 21px; }
.zenbuji-latest .zenbuji-reading { font-size: 17px; }
.zenbuji-latest .zenbuji-translation { font-size: 16px; }
/* Reusable window footer (hairline + breathing room above the content). */
.zenbuji-footer { margin-top: 8px; }

/* --- game helper: playful, JRPG-flavoured drama (overlay only) --- */
/* Energetic FFXIV-ish title, gold + italic serif, sitting on the bare glass. */
.zenbuji-game-title {
    font-family: serif;
    font-size: 25px; font-weight: 900; font-style: italic;
    letter-spacing: 0.04em;
    color: #ffc83d;
    /* soft dark-gold edge + warm glow (no heavy outline) */
    text-shadow: 0 1px 1px alpha(#5c3d00, 0.8), 0 0 10px alpha(#f5a800, 0.75);
}
/* Metallic gold "combo" coin: words banked this session. */
.zenbuji-combo {
    font-size: 16px; font-weight: 900; color: #4a2e00;
    background-image: linear-gradient(to bottom, #fff0b0, #ffd84a 45%, #e0a200);
    border: 1px solid #b07d00;
    border-radius: 9px; padding: 2px 12px;
    box-shadow: 0 1px 4px alpha(#000000, 0.40), inset 0 1px 0 alpha(#ffffff, 0.70);
    text-shadow: 0 1px 0 alpha(#ffffff, 0.40);
}
.zenbuji-quip { font-size: 13px; font-weight: 700; color: @accent_color; }

/* Hero spotlight for the freshly-captured word: a dark FF reward panel with a
   thick gold rim + glow, holding a huge chunky glowing-gold word. Deliberately
   breaks the calm glass look of the rest of the app. */
.zenbuji-hero {
    border: 2px solid #f5c211;
    border-radius: 6px;
    padding: 12px 16px 14px 16px;
    /* Layered: a faint diagonal weave for texture, a top sheen, then a warm
       neutral-dark base that harmonises with the gold rim. */
    background-image:
        repeating-linear-gradient(45deg,
            alpha(#ffffff, 0.028) 0px, alpha(#ffffff, 0.028) 1px,
            transparent 1px, transparent 7px),
        radial-gradient(circle at 50% 0%, alpha(#ffd84a, 0.10), transparent 65%),
        linear-gradient(to bottom, rgba(38, 30, 26, 0.82), rgba(18, 14, 16, 0.90));
    box-shadow: 0 0 22px alpha(#f5c211, 0.50),
                inset 0 0 0 1px alpha(#ffffff, 0.08);
}
.zenbuji-hero-word {
    font-size: 42px; font-weight: 900; color: #ffc83d;
    /* a light dark-gold edge (not a heavy black border) + warm glow + drop */
    text-shadow: 0 1px 1px alpha(#5c3d00, 0.85),
                 0 0 16px alpha(#f5a800, 0.75),
                 0 2px 4px alpha(#000000, 0.55);
}
.zenbuji-hero-reading { font-size: 17px; font-weight: 700; color: #f0b62a; }
.zenbuji-hero-trans { font-size: 14px; color: #f3eecf; }

/* A skewed, italic ribbon pinned to the hero's top-right, its colour bar fading
   transparent -> colour -> transparent at the edges, FF "LEVEL UP" style. */
.zenbuji-ribbon {
    font-size: 15px; font-weight: 800; font-style: italic;
    color: #ffffff; padding: 3px 22px;
    transform: skewX(-12deg);
    text-shadow: 0 1px 3px alpha(#000000, 0.7);
}
.zenbuji-ribbon-new {
    background-image: linear-gradient(to right,
        alpha(#ff2e88, 0), #ff4d97 28%, #c0186a 72%, alpha(#c0186a, 0));
}
.zenbuji-ribbon-levelup {
    color: #3a2600; text-shadow: 0 1px 1px alpha(#ffffff, 0.55);
    background-image: linear-gradient(to right,
        alpha(#f5c211, 0), #ffe27a 28%, #e0a200 72%, alpha(#e0a200, 0));
}
.zenbuji-dict-scroll { background: transparent; }

/* --- learning / quiz window --- */
.zenbuji-kanji { font-size: 54px; font-weight: 700; }
/* Slim, rounded, accent progress bar instead of the default hairline. */
.zenbuji-quiz-progress, .zenbuji-quiz-progress trough, .zenbuji-quiz-progress progress {
    min-height: 6px;
    border-radius: 3px;
}
.zenbuji-quiz-progress trough { background-color: alpha(currentColor, 0.12); border: none; }
.zenbuji-quiz-progress progress { background-color: @accent_color; }
/* Result verdict chip: a single bold status pill (colour carries right/wrong). */
.zenbuji-verdict {
    font-size: 14px; font-weight: 700; color: #ffffff;
    padding: 5px 16px; border-radius: 11px;
}
.zenbuji-verdict-ok { background-color: #21915c; }
.zenbuji-verdict-no { background-color: #c0182a; }
/* The revealed correct reading - the learning payload, large and in accent. */
.zenbuji-reveal-reading { font-size: 27px; font-weight: 700; color: @accent_color; }
/* Inline submit tile fused to the right of the field: squared seam side,
   no fixed height so it matches the field it's linked to. */
.zenbuji-quiz-go {
    padding: 0; min-width: 52px;
    border-top-left-radius: 0; border-bottom-left-radius: 0;
    border-top-right-radius: 14px; border-bottom-right-radius: 14px;
}
/* Verdicts sit on a solid colour chip so they stay legible over any blurred
   background (plain coloured text had poor contrast). */
.zenbuji-correct {
    color: #ffffff; font-weight: 700;
    background-color: #21915c; border-radius: 9px; padding: 3px 10px;
}
.zenbuji-wrong {
    color: #ffffff; font-weight: 700;
    background-color: #c0182a; border-radius: 9px; padding: 3px 10px;
}
.zenbuji-hint { font-size: 14px; opacity: 0.75; }
.zenbuji-score { font-size: 12px; opacity: 0.6; }
.zenbuji-celebrate {
    font-size: 88px; font-weight: 800; color: #2ec27e;
    text-shadow: 0 2px 14px rgba(0, 0, 0, 0.55);
}
/* Level-up flourish on a card that graduated to a higher SRS level. */
.zenbuji-levelup {
    font-size: 30px; font-weight: 800; color: #f5c211;
    text-shadow: 0 2px 14px rgba(0, 0, 0, 0.55);
}
.zenbuji-levelup-note { font-size: 14px; font-weight: 700; color: #f5c211; }

/* --- SRS level badges (shared: stats / dictionary / quiz) --- */
/* A small rounded chip; each level gets a distinct, legible colour. */
.zenbuji-level {
    font-size: 11px; font-weight: 700; color: #ffffff;
    border-radius: 8px; padding: 1px 8px; min-width: 56px;
}
.zenbuji-level-new      { background-color: #5b6066; }
.zenbuji-level-learning { background-color: #c08a1e; }
.zenbuji-level-young    { background-color: #1c71d8; }
.zenbuji-level-mature   { background-color: #21915c; }

/* --- statistics window --- */
/* Soft inset panel grouping the hero stats. */
.zenbuji-panel {
    background-color: alpha(currentColor, 0.05);
    border-radius: 16px;
    padding: 16px 12px;
    border: 1px solid alpha(currentColor, 0.06);
}
.zenbuji-stat-num { font-size: 29px; font-weight: 700; }
.zenbuji-stat-num-accent { color: @accent_color; }
.zenbuji-stat-label {
    font-size: 10px; font-weight: 600; opacity: 0.55; letter-spacing: 0.04em;
}
/* Thin vertical divider between the hero stats. */
.zenbuji-vrule { min-width: 1px; background-color: alpha(currentColor, 0.12); }
.zenbuji-legend { font-size: 12px; opacity: 0.85; }
.zenbuji-section-count { font-size: 11px; opacity: 0.5; }
"""

_CSS_INSTALLED = False


def install_css() -> None:
    """Add the glass stylesheet to the default display once, at USER priority."""
    global _CSS_INSTALLED
    if _CSS_INSTALLED:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(GLASS_CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER,
    )
    _CSS_INSTALLED = True


def accent_hex(dark: bool = False) -> str | None:
    """The system accent color as #rrggbb, for places CSS can't reach (Pango
    markup). Returns None if the accent API is unavailable."""
    try:
        accent = Adw.StyleManager.get_default().get_accent_color()
        rgba = accent.to_standalone_rgba(dark)
        return "#%02x%02x%02x" % (round(rgba.red * 255),
                                  round(rgba.green * 255),
                                  round(rgba.blue * 255))
    except Exception:  # noqa: BLE001  (older libadwaita without accent API)
        return None


def accent_rgba(dark: bool = False) -> Gdk.RGBA:
    """The system accent color as a Gdk.RGBA, for cairo drawing (charts).

    Falls back to the GNOME blue (#3584e4) on older libadwaita without the
    accent API."""
    rgba = Gdk.RGBA()
    try:
        accent = Adw.StyleManager.get_default().get_accent_color()
        return accent.to_standalone_rgba(dark)
    except Exception:  # noqa: BLE001
        rgba.parse("#3584e4")
        return rgba


def _install_focus_loss_close(win: Gtk.Window) -> None:
    """Dismiss the window when it loses focus, but not while being dragged.

    Dragging a headerless window starts a compositor move that briefly
    deactivates it; a press *inside* the window flags interaction so that the
    deactivation isn't mistaken for a focus switch (which would close it the
    instant you try to drag).
    """
    state = {"was_active": False, "interacting": False}

    def clear_interacting():
        state["interacting"] = False
        return GLib.SOURCE_REMOVE

    def on_active_changed(*_a):
        if win.is_active():
            state["was_active"] = True
            state["interacting"] = False
        elif state["was_active"] and not state["interacting"]:
            win.close()

    win.connect("notify::is-active", on_active_changed)

    watcher = Gtk.EventControllerLegacy()
    watcher.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_event(controller, *_a):
        event = controller.get_current_event()
        if event is None:
            return False
        et = event.get_event_type()
        if et == Gdk.EventType.BUTTON_PRESS:
            state["interacting"] = True
        elif et == Gdk.EventType.BUTTON_RELEASE:
            GLib.timeout_add(150, clear_interacting)
        return False

    watcher.connect("event", on_event)
    win.add_controller(watcher)


def make_glass_window(application, *, title, default_size=(460, -1),
                      resizable=False, draggable=True,
                      close_on_focus_loss=False):
    """Build a transparent, headerless glass window. Returns (window, card).

    Fill `card` (a vertical Gtk.Box with the `.zenbuji-card` style) with content.
    The window follows the system light/dark scheme live, closes on Escape, is
    draggable from empty areas, and optionally dismisses on focus loss.
    """
    install_css()
    win = Gtk.ApplicationWindow(application=application)
    win.set_title(title)
    width, height = default_size
    win.set_default_size(width, height)
    win.set_decorated(False)
    win.set_resizable(resizable)
    win.add_css_class("zenbuji-window")

    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    card.add_css_class("zenbuji-card")

    style_mgr = Adw.StyleManager.get_default()

    def apply_scheme(*_a):
        card.remove_css_class("dark")
        card.remove_css_class("light")
        card.add_css_class("dark" if style_mgr.get_dark() else "light")

    apply_scheme()
    style_mgr.connect("notify::dark", apply_scheme)

    if draggable:
        handle = Gtk.WindowHandle()
        handle.set_child(card)
        win.set_child(handle)
    else:
        win.set_child(card)

    # CAPTURE phase so Escape always closes, even when a focused child (e.g. a
    # SearchEntry, which otherwise eats Escape to clear itself) would consume it.
    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            win.close()
            return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)

    if close_on_focus_loss:
        _install_focus_loss_close(win)

    return win, card


def make_footer():
    """A reusable window footer: a top hairline + breathing room, then a
    horizontal content row. Returns ``(footer, content)``: append the footer to
    the card and put your widgets in ``content``."""
    footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    footer.add_css_class("zenbuji-footer")
    hair = Gtk.Box()
    hair.add_css_class("zenbuji-hairline")
    footer.append(hair)
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    footer.append(content)
    return footer, content
