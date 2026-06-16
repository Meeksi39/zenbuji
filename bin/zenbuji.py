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

DEFAULT_CONFIG = {
    # "argos" (offline), "deepl" (online), or "auto" (deepl if a key is set,
    # otherwise argos).
    "backend": "auto",
    # Languages to show in the popup / printed output, in order.
    "languages": ["en", "de"],
    # DeepL API key (free tier works). Can also come from $DEEPL_API_KEY.
    "deepl_api_key": "",
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
# Translation backends
# --------------------------------------------------------------------------- #
LANG_NAMES = {"en": "English", "de": "German", "ja": "Japanese"}


class TranslationError(Exception):
    pass


def translate_deepl(text: str, targets: list[str], api_key: str) -> dict:
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
            raise TranslationError(f"DeepL request failed: {exc}") from exc
    return out


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


def translate_argos(text: str, targets: list[str]) -> dict:
    try:
        import argostranslate.translate  # noqa: F401
    except ImportError as exc:
        raise TranslationError(
            "Argos Translate is not installed (run install.sh)."
        ) from exc

    src = _argos_get("ja")
    if src is None:
        raise TranslationError(
            "No Japanese language pack installed for Argos. "
            "Run: zenbuji models --install"
        )
    out = {}
    for lang in targets:
        dst = _argos_get(lang)
        if dst is None:
            raise TranslationError(
                f"Argos has no '{lang}' model installed. "
                "Run: zenbuji models --install"
            )
        try:
            with _quiet_stderr():
                out[lang] = src.get_translation(dst).translate(text)
        except Exception as exc:  # noqa: BLE001
            raise TranslationError(f"Argos translation failed: {exc}") from exc
    return out


def translate(text: str, targets: list[str], cfg: dict) -> tuple[dict, list[str]]:
    """Translate text into each target language. Returns (translations, notes)."""
    backend = cfg.get("backend", "auto")
    key = cfg.get("deepl_api_key", "")
    notes: list[str] = []

    if backend == "auto":
        backend = "deepl" if key else "argos"

    if backend == "deepl":
        if not key:
            notes.append("DeepL selected but no API key set; skipping translation.")
            return {}, notes
        try:
            return translate_deepl(text, targets, key), notes
        except TranslationError as exc:
            notes.append(str(exc))
            # Fall back to offline if available.
            try:
                return translate_argos(text, targets), [
                    *notes,
                    "Fell back to offline Argos backend.",
                ]
            except TranslationError:
                return {}, notes

    # argos
    try:
        return translate_argos(text, targets), notes
    except TranslationError as exc:
        notes.append(str(exc))
        if key:
            try:
                return translate_deepl(text, targets, key), [
                    *notes,
                    "Fell back to DeepL backend.",
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
    return Result(
        text=text,
        reading=reading,
        tokens=tokens,
        translations=translations,
        notes=notes,
    )


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
  zenbuji config              Show or set configuration
  zenbuji models --install    Download offline Argos models (ja->en, en->de)

Input: if no <text> is given, zenbuji reads the current selection (with
--selection) or standard input.

Options:
  --lang en,de        Target languages (comma separated; default from config)
  --backend argos|deepl|auto
  --json              Emit machine-readable JSON
  --selection         Read the current text selection as input
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
    if changed:
        save_config(cfg)
        print(f"saved {CONFIG_PATH}")
    redacted = dict(cfg)
    if redacted.get("deepl_api_key"):
        redacted["deepl_api_key"] = "***set***"
    print(json.dumps(redacted, ensure_ascii=False, indent=2))
    return 0


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
        "config", "models",
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
        return cmd_config(p.parse_args(rest), cfg)

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
    p.add_argument("words", nargs="*")
    opts = p.parse_args(rest)

    if opts.backend:
        cfg["backend"] = opts.backend
    languages = (
        [s.strip() for s in opts.lang.split(",") if s.strip()]
        if opts.lang
        else cfg.get("languages", ["en", "de"])
    )

    use_selection = opts.selection or command == "selection"
    text = resolve_input(opts.words, use_selection)
    if not text.strip():
        print("No input text (give text, use --selection, or pipe stdin).",
              file=sys.stderr)
        return 2

    if command == "popup":
        return launch_popup(text, languages, cfg)

    do_translate = command not in ("furigana",)
    result = process(text, languages, cfg, do_translate=do_translate)

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


def launch_popup(text: str, languages: list[str], cfg: dict) -> int:
    """Render the result, then show it in the GTK popup."""
    result = process(text, languages, cfg, do_translate=True)
    try:
        from zenbuji_popup import show_popup
    except ImportError:
        # Same-directory import when run from the repo/bin.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from zenbuji_popup import show_popup
    return show_popup(result, languages)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
