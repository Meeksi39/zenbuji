"""OCR (read Japanese text from an image / screen region)."""

from __future__ import annotations

import os

from . import store
from .util import _note, _quiet_stderr

_MOCR = None


def _manga_ocr():
    """Lazily construct the manga-ocr reader (downloads the model on first use)."""
    global _MOCR
    if _MOCR is None:
        with _quiet_stderr():
            from manga_ocr import MangaOcr

            _MOCR = MangaOcr()
    return _MOCR


def ocr_image_to_text(path: str, cfg: dict) -> tuple[str, list[str]]:
    """Recognise Japanese text in an image file. Returns (text, notes)."""
    notes: list[str] = []
    lang = cfg.get("ui_language", "en")
    if not path or not os.path.exists(path):
        return "", [_note("ocr_not_found", lang)]
    backend = cfg.get("ocr_backend", "mangaocr")
    if backend != "mangaocr":
        notes.append(_note("ocr_unknown_backend", lang, backend=backend))
    try:
        store.set_busy("reading")
        with _quiet_stderr():
            text = _manga_ocr()(path)
    except ImportError:
        return "", [_note("ocr_not_installed", lang)]
    except Exception as exc:  # noqa: BLE001
        return "", [_note("ocr_failed", lang, error=exc)]
    finally:
        store.clear_busy()
    return (text or "").strip(), notes


def capture_region() -> str | None:
    """Interactively select a screen region and return the captured PNG path.

    Uses the XDG desktop Screenshot portal in interactive mode. Recent GNOME
    versions forbid external callers from using org.gnome.Shell.Screenshot
    directly ("ScreenshotArea is not allowed"), so the portal is the supported
    Wayland path: GNOME shows its own screenshot UI (Area / Window / Screen)
    and hands back a URI to the captured image. Returns a local path, or None
    if the user cancelled or capture failed.
    """
    try:
        import gi  # noqa: F401
        from gi.repository import Gio, GLib
    except Exception:  # noqa: BLE001  (PyGObject missing)
        return None

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception:  # noqa: BLE001
        return None

    # The portal answers asynchronously via a Request object whose path follows
    # a documented convention, so we can subscribe before calling and avoid a
    # signal/reply race. Sender unique name: ":1.23" -> "1_23".
    token = f"zenbuji_{os.getpid()}"
    sender = bus.get_unique_name().lstrip(":").replace(".", "_")
    request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    captured: dict[str, str] = {}
    loop = GLib.MainLoop()

    def on_response(_conn, _sender, _path, _iface, _signal, params):
        response, results = params.unpack()
        if response == 0 and results.get("uri"):
            captured["uri"] = results["uri"]
        loop.quit()

    sub_id = bus.signal_subscribe(
        "org.freedesktop.portal.Desktop",
        "org.freedesktop.portal.Request",
        "Response",
        request_path,
        None,
        Gio.DBusSignalFlags.NONE,
        on_response,
    )

    options = {
        "handle_token": GLib.Variant("s", token),
        "interactive": GLib.Variant("b", True),
    }
    try:
        bus.call_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot",
            "Screenshot",
            GLib.Variant("(sa{sv})", ("", options)),
            GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
    except Exception:  # noqa: BLE001
        bus.signal_unsubscribe(sub_id)
        return None

    # Don't hang forever if the portal never answers.
    GLib.timeout_add_seconds(180, lambda: (loop.quit(), False)[1])
    loop.run()
    bus.signal_unsubscribe(sub_id)

    uri = captured.get("uri")
    if not uri:
        return None  # cancelled or failed
    try:
        path, _ = GLib.filename_from_uri(uri)
    except Exception:  # noqa: BLE001
        from urllib.parse import unquote, urlparse

        path = unquote(urlparse(uri).path)
    return path if path and os.path.exists(path) else None
