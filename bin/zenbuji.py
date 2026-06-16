#!/usr/bin/env python3
"""zenbuji — 全部字

Take Japanese text and return furigana (readings) plus English and German
translations. Designed to be omni-available for immersive learners: run it on
the command line, from a global hotkey on the current text selection, from the
GNOME Shell top-bar menu, or from a file-manager context menu.

Furigana is produced offline with fugashi + unidic-lite. Translation uses an
offline backend (Argos Translate) by default and an optional online backend
(DeepL free API) when a key is configured.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "zenbuji"
CONFIG_PATH = CONFIG_DIR / "config.json"

DATA_DIR = Path(
    os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
) / "zenbuji"
HISTORY_PATH = DATA_DIR / "history.json"

DEFAULT_CONFIG = {
    # "argos" (offline), "deepl" (online), or "auto" (deepl if a key is set,
    # otherwise argos).
    "backend": "auto",
    # Languages to show in the popup / printed output, in order.
    "languages": ["en", "de"],
    # DeepL API key (free tier works). Can also come from $DEEPL_API_KEY.
    "deepl_api_key": "",
    # Remember recent lookups (shown in the extension's "Recent" menu).
    "history": True,
    # Maximum number of recent lookups to keep.
    "history_size": 20,
    # OCR engine used to read text from a captured screen region.
    "ocr_backend": "mangaocr",
    # Interface language for the popup, top-bar menu, and settings window
    # ("en" or "ja"). Independent of the translation target languages above.
    "ui_language": "en",
    # Dismiss the popup when it loses focus (HUD-style). Turn off to keep it
    # open until Escape/closed.
    "popup_close_on_focus_loss": True,
}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if not cfg.get("deepl_api_key"):
        cfg["deepl_api_key"] = os.environ.get("DEEPL_API_KEY", "")
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def load_history() -> list:
    try:
        if HISTORY_PATH.exists():
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, ValueError):
        pass
    return []


def clear_history() -> None:
    try:
        HISTORY_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def append_history(result: "Result", limit: int = 20) -> None:
    """Record a lookup, newest-first, deduped by text and capped at `limit`."""
    if not result.text:
        return
    entry = {
        "text": result.text,
        "reading": result.reading,
        "translations": result.translations,
    }
    history = [e for e in load_history() if e.get("text") != result.text]
    history.insert(0, entry)
    del history[max(0, limit):]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Furigana
# --------------------------------------------------------------------------- #
KATAKANA_START = 0x30A1
KATAKANA_END = 0x30F6
HIRAGANA_OFFSET = 0x30A1 - 0x3041


def kata_to_hira(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if KATAKANA_START <= code <= KATAKANA_END:
            out.append(chr(code - HIRAGANA_OFFSET))
        else:
            out.append(ch)
    return "".join(out)


def has_kanji(text: str) -> bool:
    return any(0x4E00 <= ord(ch) <= 0x9FFF or ch == "々" for ch in text)


@dataclass
class Token:
    surface: str
    reading: str  # hiragana reading of the surface (may equal surface)
    has_kanji: bool


@dataclass
class Result:
    text: str
    reading: str  # full hiragana reading of the whole text
    tokens: list = field(default_factory=list)  # list[Token]
    translations: dict = field(default_factory=dict)  # lang -> str
    notes: list = field(default_factory=list)  # warnings shown to the user

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


_TAGGER = None


def _tagger():
    global _TAGGER
    if _TAGGER is None:
        import fugashi  # noqa: F401  (deferred: heavy import)

        _TAGGER = fugashi.Tagger()
    return _TAGGER


def analyze(text: str) -> tuple[str, list[Token]]:
    """Return (full hiragana reading, tokens) for the given text."""
    text = text.strip()
    tagger = _tagger()
    tokens: list[Token] = []
    reading_parts: list[str] = []
    for word in tagger(text):
        surface = word.surface
        kana = None
        feat = word.feature
        # unidic features expose several reading fields; prefer kana/pron.
        for attr in ("kana", "pron", "kanaBase", "pronBase"):
            val = getattr(feat, attr, None)
            if val and val != "*":
                kana = val
                break
        if kana:
            reading = kata_to_hira(kana)
        else:
            reading = surface
        reading_parts.append(reading)
        tokens.append(
            Token(surface=surface, reading=reading, has_kanji=has_kanji(surface))
        )
    return "".join(reading_parts), tokens


# --------------------------------------------------------------------------- #
# OCR (read Japanese text from an image / screen region)
# --------------------------------------------------------------------------- #
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
        with _quiet_stderr():
            text = _manga_ocr()(path)
    except ImportError:
        return "", [_note("ocr_not_installed", lang)]
    except Exception as exc:  # noqa: BLE001
        return "", [_note("ocr_failed", lang, error=exc)]
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


# --------------------------------------------------------------------------- #
# Translation backends
# --------------------------------------------------------------------------- #
LANG_NAMES = {"en": "English", "de": "German", "ja": "Japanese"}

# User-facing status notes (shown in the popup and CLI output), by UI language.
# `{...}` placeholders are filled via _note(..., **kw).
NOTES = {
    "deepl_no_key": {
        "en": "DeepL selected but no API key set; skipping translation.",
        "ja": "DeepL が選択されていますが API キーが未設定です。翻訳をスキップします。",
    },
    "fell_back_argos": {
        "en": "Fell back to offline Argos backend.",
        "ja": "オフラインの Argos バックエンドに切り替えました。",
    },
    "fell_back_deepl": {
        "en": "Fell back to DeepL backend.",
        "ja": "DeepL バックエンドに切り替えました。",
    },
    "argos_not_installed": {
        "en": "Argos Translate is not installed (run install.sh).",
        "ja": "Argos Translate がインストールされていません（install.sh を実行してください）。",
    },
    "argos_no_ja": {
        "en": "No Japanese language pack installed for Argos. "
              "Run: zenbuji models --install",
        "ja": "Argos の日本語パックがインストールされていません。"
              "実行: zenbuji models --install",
    },
    "argos_no_model": {
        "en": "Argos has no '{lang}' model installed. "
              "Run: zenbuji models --install",
        "ja": "Argos に '{lang}' モデルがインストールされていません。"
              "実行: zenbuji models --install",
    },
    "argos_failed": {
        "en": "Argos translation failed: {error}",
        "ja": "Argos の翻訳に失敗しました: {error}",
    },
    "deepl_failed": {
        "en": "DeepL request failed: {error}",
        "ja": "DeepL リクエストに失敗しました: {error}",
    },
    "ocr_not_found": {
        "en": "OCR: image not found.",
        "ja": "OCR: 画像が見つかりません。",
    },
    "ocr_unknown_backend": {
        "en": "Unknown ocr_backend '{backend}'; using manga-ocr.",
        "ja": "不明な ocr_backend '{backend}'。manga-ocr を使用します。",
    },
    "ocr_not_installed": {
        "en": "OCR backend not installed — re-run install.sh without --light.",
        "ja": "OCR バックエンドがインストールされていません — "
              "install.sh を --light なしで再実行してください。",
    },
    "ocr_failed": {
        "en": "OCR failed: {error}",
        "ja": "OCR に失敗しました: {error}",
    },
}


def _note(key: str, lang: str = "en", **fmt) -> str:
    """Return a localised status note; unknown keys/langs fall back to English."""
    entry = NOTES.get(key, {})
    template = entry.get(lang) or entry.get("en") or key
    try:
        return template.format(**fmt) if fmt else template
    except (KeyError, IndexError):
        return template


class TranslationError(Exception):
    pass


def translate_deepl(text: str, targets: list[str], api_key: str,
                    lang: str = "en") -> dict:
    import urllib.parse
    import urllib.request

    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    url = f"https://{host}/v2/translate"
    out = {}
    deepl_lang = {"en": "EN", "de": "DE"}
    for lang in targets:
        target = deepl_lang.get(lang)
        if not target:
            continue
        data = urllib.parse.urlencode(
            {"text": text, "source_lang": "JA", "target_lang": target}
        ).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"DeepL-Auth-Key {api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            out[lang] = payload["translations"][0]["text"]
        except Exception as exc:  # noqa: BLE001
            raise TranslationError(
                _note("deepl_failed", lang, error=exc)) from exc
    return out


def deepl_usage(api_key: str) -> dict:
    """Query the DeepL account usage endpoint to validate a key.

    Returns {"ok": bool, "used": int, "limit": int, "error": str}.
    """
    import urllib.request

    if not api_key:
        return {"ok": False, "used": 0, "limit": 0, "error": "no API key set"}
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    req = urllib.request.Request(
        f"https://{host}/v2/usage",
        headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return {
            "ok": True,
            "used": int(payload.get("character_count", 0)),
            "limit": int(payload.get("character_limit", 0)),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "used": 0, "limit": 0, "error": str(exc)}


_ARGOS_LANGS = None


import contextlib


@contextlib.contextmanager
def _quiet_stderr():
    """Silence stanza/argos chatter written straight to fd 2.

    Python exceptions still propagate, so genuine errors are not hidden.
    """
    try:
        saved = os.dup(2)
    except OSError:
        yield
        return
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


def _argos_langs():
    global _ARGOS_LANGS
    if _ARGOS_LANGS is None:
        with _quiet_stderr():
            from argostranslate import translate as argos_translate

            _ARGOS_LANGS = argos_translate.get_installed_languages()
    return _ARGOS_LANGS


def _argos_get(code: str):
    for lang in _argos_langs():
        if lang.code == code:
            return lang
    return None


def translate_argos(text: str, targets: list[str], lang: str = "en") -> dict:
    try:
        import argostranslate.translate  # noqa: F401
    except ImportError as exc:
        raise TranslationError(
            _note("argos_not_installed", lang)
        ) from exc

    src = _argos_get("ja")
    if src is None:
        raise TranslationError(_note("argos_no_ja", lang))
    out = {}
    for target in targets:
        dst = _argos_get(target)
        if dst is None:
            raise TranslationError(
                _note("argos_no_model", lang, lang=target))
        try:
            with _quiet_stderr():
                out[target] = src.get_translation(dst).translate(text)
        except Exception as exc:  # noqa: BLE001
            raise TranslationError(
                _note("argos_failed", lang, error=exc)) from exc
    return out


def translate(text: str, targets: list[str], cfg: dict) -> tuple[dict, list[str]]:
    """Translate text into each target language. Returns (translations, notes)."""
    backend = cfg.get("backend", "auto")
    key = cfg.get("deepl_api_key", "")
    lang = cfg.get("ui_language", "en")
    notes: list[str] = []

    if backend == "auto":
        backend = "deepl" if key else "argos"

    if backend == "deepl":
        if not key:
            notes.append(_note("deepl_no_key", lang))
            return {}, notes
        try:
            return translate_deepl(text, targets, key, lang), notes
        except TranslationError as exc:
            notes.append(str(exc))
            # Fall back to offline if available.
            try:
                return translate_argos(text, targets, lang), [
                    *notes,
                    _note("fell_back_argos", lang),
                ]
            except TranslationError:
                return {}, notes

    # argos
    try:
        return translate_argos(text, targets, lang), notes
    except TranslationError as exc:
        notes.append(str(exc))
        if key:
            try:
                return translate_deepl(text, targets, key, lang), [
                    *notes,
                    _note("fell_back_deepl", lang),
                ]
            except TranslationError as exc2:
                notes.append(str(exc2))
        return {}, notes


# --------------------------------------------------------------------------- #
# High-level
# --------------------------------------------------------------------------- #
def process(text: str, languages: list[str], cfg: dict, do_translate: bool = True) -> Result:
    text = text.strip()
    reading, tokens = analyze(text)
    translations: dict = {}
    notes: list[str] = []
    if do_translate and text:
        translations, notes = translate(text, languages, cfg)
    result = Result(
        text=text,
        reading=reading,
        tokens=tokens,
        translations=translations,
        notes=notes,
    )
    if cfg.get("history", True) and translations:
        append_history(result, limit=int(cfg.get("history_size", 20)))
    return result


# --------------------------------------------------------------------------- #
# Selection / input helpers
# --------------------------------------------------------------------------- #
def read_selection() -> str:
    """Read the current Wayland PRIMARY selection, falling back to clipboard."""
    for args in (["wl-paste", "-p", "-n"], ["wl-paste", "-n"]):
        if shutil.which(args[0]):
            try:
                out = subprocess.run(
                    args, capture_output=True, text=True, timeout=3
                )
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout
            except (OSError, subprocess.SubprocessError):
                continue
    return ""


def resolve_input(text_args: list[str], use_selection: bool) -> str:
    if text_args:
        return " ".join(text_args)
    if use_selection:
        return read_selection()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def render_text(result: Result, languages: list[str]) -> str:
    lines = [result.text]
    if result.reading and result.reading != result.text:
        lines.append(f"  {result.reading}")
    breakdown = [
        f"{t.surface}（{t.reading}）" if t.has_kanji and t.reading != t.surface
        else t.surface
        for t in result.tokens
    ]
    if any(t.has_kanji for t in result.tokens):
        lines.append("  " + " ".join(breakdown))
    lines.append("")
    for lang in languages:
        val = result.translations.get(lang)
        label = LANG_NAMES.get(lang, lang.upper())
        lines.append(f"{label}: {val if val else '—'}")
    for note in result.notes:
        lines.append(f"(note: {note})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
HELP = """zenbuji — furigana + EN/DE translation for Japanese text.

Usage:
  zenbuji <text>              Furigana + translations for <text>
  zenbuji read <text>         Same as above (explicit)
  zenbuji furigana <text>     Readings only (no translation)
  zenbuji tr <text>           Translation only
  zenbuji popup [text]        Show a GUI popup (reads selection if no text)
  zenbuji selection           Process the current text selection
  zenbuji ocr [image]         OCR a screen region (or image file) and look it up
  zenbuji config              Show or set configuration
  zenbuji usage               Check the DeepL key and show remaining quota
  zenbuji models --install    Download offline Argos models (ja->en, en->de)

Input: if no <text> is given, zenbuji reads the current selection (with
--selection) or standard input.

Options:
  --lang en,de        Target languages (comma separated; default from config)
  --backend argos|deepl|auto
  --json              Emit machine-readable JSON
  --selection         Read the current text selection as input
  --ocr               Capture a screen region and OCR it as input
  --ocr-image PATH    OCR an existing image file as input
"""


def cmd_models(args, cfg) -> int:
    from_codes = [("ja", "en"), ("en", "de"), ("en", "ja"), ("de", "en")]
    try:
        import argostranslate.package as pkg
    except ImportError:
        print("Argos Translate is not installed; run install.sh first.", file=sys.stderr)
        return 1
    if args.list:
        try:
            from argostranslate import translate as t
            for lang in t.get_installed_languages():
                print(f"installed: {lang.code} ({lang.name})")
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}", file=sys.stderr)
        return 0
    print("Updating Argos package index…")
    pkg.update_package_index()
    available = pkg.get_available_packages()
    installed = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}
    for fc, tc in from_codes:
        if (fc, tc) in installed:
            print(f"already installed: {fc}->{tc}")
            continue
        match = next(
            (p for p in available if p.from_code == fc and p.to_code == tc), None
        )
        if not match:
            print(f"no package for {fc}->{tc}")
            continue
        print(f"downloading {fc}->{tc} …")
        path = match.download()
        pkg.install_from_path(path)
        print(f"installed {fc}->{tc}")
    return 0


def cmd_config(args, cfg) -> int:
    changed = False
    if args.backend:
        cfg["backend"] = args.backend
        changed = True
    if args.lang:
        cfg["languages"] = [s.strip() for s in args.lang.split(",") if s.strip()]
        changed = True
    if args.deepl_key is not None:
        cfg["deepl_api_key"] = args.deepl_key
        changed = True
    if args.history:
        cfg["history"] = args.history == "on"
        changed = True
    if args.ui_language:
        cfg["ui_language"] = args.ui_language
        changed = True
    if args.popup_close:
        cfg["popup_close_on_focus_loss"] = args.popup_close == "on"
        changed = True
    if changed:
        save_config(cfg)
    if args.clear_history:
        clear_history()
    if args.json:
        # Machine-readable: the real, unredacted config (used by the prefs UI,
        # which reads the same local file anyway).
        print(json.dumps(cfg, ensure_ascii=False))
        return 0
    if changed:
        print(f"saved {CONFIG_PATH}")
    redacted = dict(cfg)
    if redacted.get("deepl_api_key"):
        redacted["deepl_api_key"] = "***set***"
    print(json.dumps(redacted, ensure_ascii=False, indent=2))
    return 0


def cmd_usage(args, cfg) -> int:
    key = args.key if args.key is not None else cfg.get("deepl_api_key", "")
    info = deepl_usage(key)
    if args.json:
        print(json.dumps(info, ensure_ascii=False))
    elif info["ok"]:
        print(f"DeepL key OK — {info['used']:,} / {info['limit']:,} characters used")
    else:
        print(f"DeepL key check failed: {info['error']}", file=sys.stderr)
    return 0 if info["ok"] else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = load_config()

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default="read")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    parser.add_argument("--help", "-h", action="store_true")

    # Explicit help, or no args with nothing piped in.
    if (argv and argv[0] in ("-h", "--help", "help")) or (
        not argv and sys.stdin.isatty()
    ):
        print(HELP)
        return 0

    known_commands = {
        "read", "furigana", "tr", "translate", "popup", "selection",
        "config", "models", "usage", "ocr",
    }

    # Determine command vs. free text. With no args (e.g. piped stdin), default
    # to the read command.
    if argv and argv[0] in known_commands:
        command = argv[0]
        rest = argv[1:]
    else:
        command = "read"
        rest = argv

    # Sub-parsers for the flag-bearing commands.
    if command == "config":
        p = argparse.ArgumentParser(prog="zenbuji config")
        p.add_argument("--backend", choices=["argos", "deepl", "auto"])
        p.add_argument("--lang")
        p.add_argument("--deepl-key", dest="deepl_key")
        p.add_argument("--history", choices=["on", "off"])
        p.add_argument("--ui-language", dest="ui_language", choices=["en", "ja"])
        p.add_argument("--popup-close-on-focus-loss", dest="popup_close",
                       choices=["on", "off"])
        p.add_argument("--clear-history", action="store_true")
        p.add_argument("--json", action="store_true")
        return cmd_config(p.parse_args(rest), cfg)

    if command == "usage":
        p = argparse.ArgumentParser(prog="zenbuji usage")
        p.add_argument("--key")
        p.add_argument("--json", action="store_true")
        return cmd_usage(p.parse_args(rest), cfg)

    if command == "models":
        p = argparse.ArgumentParser(prog="zenbuji models")
        p.add_argument("--install", action="store_true")
        p.add_argument("--list", action="store_true")
        return cmd_models(p.parse_args(rest), cfg)

    # Shared options for the text commands.
    p = argparse.ArgumentParser(prog=f"zenbuji {command}", add_help=False)
    p.add_argument("--lang")
    p.add_argument("--backend", choices=["argos", "deepl", "auto"])
    p.add_argument("--json", action="store_true")
    p.add_argument("--selection", action="store_true")
    p.add_argument("--ocr", action="store_true",
                   help="capture a screen region and OCR it")
    p.add_argument("--ocr-image", dest="ocr_image",
                   help="OCR an existing image file")
    p.add_argument("words", nargs="*")
    opts = p.parse_args(rest)

    # `zenbuji ocr <image>` — treat the positional as the image path.
    if command == "ocr" and opts.words and not opts.ocr_image:
        opts.ocr_image = opts.words[0]
        opts.words = []

    if opts.backend:
        cfg["backend"] = opts.backend
    languages = (
        [s.strip() for s in opts.lang.split(",") if s.strip()]
        if opts.lang
        else cfg.get("languages", ["en", "de"])
    )

    ocr_notes: list[str] = []
    want_ocr = opts.ocr or opts.ocr_image or command == "ocr"
    if want_ocr:
        image_path = opts.ocr_image
        if not image_path:
            image_path = capture_region()
            if not image_path:
                return 0  # user cancelled the region selection
        if command == "popup":
            return launch_popup(None, languages, cfg, ocr_image=image_path)
        text, ocr_notes = ocr_image_to_text(image_path, cfg)
        if not text.strip():
            for note in ocr_notes:
                print(note, file=sys.stderr)
            print("No text recognised in the image.", file=sys.stderr)
            return 1
    else:
        use_selection = opts.selection or command == "selection"
        text = resolve_input(opts.words, use_selection)
        if not text.strip():
            print("No input text (give text, use --selection, --ocr, or pipe stdin).",
                  file=sys.stderr)
            return 2

    if command == "popup":
        return launch_popup(text, languages, cfg)

    do_translate = command not in ("furigana",)
    result = process(text, languages, cfg, do_translate=do_translate)
    if ocr_notes:
        result.notes = [*ocr_notes, *result.notes]

    if command in ("tr", "translate"):
        # Translation only — drop the furigana fields from the output.
        result.tokens = []
        result.reading = ""

    if opts.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        # furigana-only: don't print the (empty) translation section.
        render_langs = [] if command == "furigana" else languages
        print(render_text(result, render_langs))
    return 0


def launch_popup(text, languages: list[str], cfg: dict, ocr_image=None) -> int:
    """Show the GTK popup, editable and able to (re-)run lookups itself.

    With `ocr_image`, the popup recognises the text asynchronously (showing a
    spinner); otherwise it renders the result for `text` immediately.
    """
    try:
        from zenbuji_popup import show_popup
    except ImportError:
        # Same-directory import when run from the repo/bin.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from zenbuji_popup import show_popup

    def process_fn(t):
        return process(t, languages, cfg, do_translate=True)

    def ocr_fn(img):
        return ocr_image_to_text(img, cfg)

    ui_language = cfg.get("ui_language", "en")
    close_on_focus_loss = bool(cfg.get("popup_close_on_focus_loss", True))
    if ocr_image:
        return show_popup(languages, ocr_image=ocr_image,
                          process_fn=process_fn, ocr_fn=ocr_fn,
                          ui_language=ui_language,
                          close_on_focus_loss=close_on_focus_loss)
    result = process_fn(text) if text else None
    return show_popup(languages, result=result,
                      process_fn=process_fn, ocr_fn=ocr_fn,
                      ui_language=ui_language,
                      close_on_focus_loss=close_on_focus_loss)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
