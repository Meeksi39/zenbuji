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
/* Primary action: filled with the system accent. */
.zenbuji-action {
    border-radius: 10px;
    font-weight: 600;
    border: none;
    background-image: none;
    background-color: @accent_bg_color;
    color: @accent_fg_color;
}
.zenbuji-action:hover { background-color: shade(@accent_bg_color, 1.08); }
.zenbuji-action:active { background-color: shade(@accent_bg_color, 0.94); }
/* Secondary: translucent glass. */
.zenbuji-secondary {
    border-radius: 10px;
    font-weight: 500;
    background-image: none;
    background-color: alpha(currentColor, 0.10);
    border: 1px solid alpha(currentColor, 0.14);
}
.zenbuji-secondary:hover { background-color: alpha(currentColor, 0.16); }
/* Flat icon buttons tinted with the accent (or red for destructive). */
.zenbuji-icon { color: @accent_color; }
.zenbuji-icon-danger { color: #e01b24; }

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
.zenbuji-dict-scroll { background: transparent; }

/* --- learning / quiz window --- */
.zenbuji-kanji { font-size: 54px; font-weight: 700; }
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
.zenbuji-stat-num { font-size: 22px; font-weight: 700; }
.zenbuji-stat-label { font-size: 10px; opacity: 0.6; }
.zenbuji-level-bar trough, .zenbuji-level-bar block {
    border-radius: 5px; min-height: 8px;
}
.zenbuji-level-bar block.filled { background-color: @accent_bg_color; }
.zenbuji-activity-bar {
    background-color: @accent_bg_color; border-radius: 3px; min-width: 6px;
}
.zenbuji-activity-empty { background-color: alpha(currentColor, 0.12); }
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
