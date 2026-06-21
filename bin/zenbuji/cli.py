"""Command-line interface and GUI launchers.

GUI imports (``zenbuji_popup``/``zenbuji_dict``/``zenbuji_learn``/``zenbuji_stats``)
stay deferred inside the ``launch_*`` functions so ``import zenbuji`` needs only
the stdlib. Cross-module engine calls are made **module-qualified** (``tts.speak``,
``pipeline.process``, ``lang.analyze``, ``translation.translate_deepl``,
``paths.DICT_PATH``, …) so the test suite's monkeypatches land.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from . import (exporting, grade, lang, ocr, paths, pipeline, srs, store,
               translation, tts)


HELP = """zenbuji — furigana + EN/DE translation for Japanese text.

Usage:
  zenbuji <text>              Furigana + translations for <text>
  zenbuji read <text>         Same as above (explicit)
  zenbuji furigana <text>     Readings only (no translation)
  zenbuji tr <text>           Translation only
  zenbuji popup [text]        Show a GUI popup (reads selection if no text)
  zenbuji selection           Process the current text selection
  zenbuji ocr [image]         OCR a screen region (or image file) and look it up
  zenbuji add <words…>        Translate & store words in the dictionary, no GUI
  zenbuji dict                Open the local dictionary (cached DeepL lookups)
  zenbuji export              Export the dictionary as Anki TSV/CSV (-o FILE)
  zenbuji learn               Practice cached words (spaced repetition quiz)
  zenbuji stats               Show learning statistics (--json for machines)
  zenbuji game                Game-helper overlay (shortcuts + live dictionary)
  zenbuji about               Show the About window (logo, version, links)
  zenbuji speak [text]        Read text aloud (reads the selection if no text)
  zenbuji voices              List local VOICEVOX speakers (--json for machines)
  zenbuji voicevox [start|stop|restart|status]   Control the VOICEVOX engine
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
            for lang_obj in t.get_installed_languages():
                print(f"installed: {lang_obj.code} ({lang_obj.name})")
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


def _learn_command(extra: str) -> str:
    """Resolve a command line that re-runs zenbuji (prefer the installed
    launcher, fall back to the venv python + the package entry point)."""
    launcher = shutil.which("zenbuji") or str(
        Path.home() / ".local" / "bin" / "zenbuji")
    if os.path.exists(launcher):
        return f"{launcher} {extra}"
    entry = Path(__file__).resolve().parent.parent / "zenbuji_main.py"
    return f"{sys.executable} {entry} {extra}"


def _write_learn_autostart(enable: bool) -> None:
    """Create/remove the autostart entry that opens the learning window on login."""
    try:
        if enable:
            paths.AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
            paths.AUTOSTART_PATH.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=zenbuji learn\n"
                f"Exec={_learn_command('learn --on-login')}\n"
                "X-GNOME-Autostart-enabled=true\n"
                "NoDisplay=true\n",
                encoding="utf-8",
            )
        else:
            paths.AUTOSTART_PATH.unlink(missing_ok=True)
    except OSError:
        pass


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
    if args.dictionary:
        cfg["dictionary"] = args.dictionary == "on"
        changed = True
    if args.cache_offline:
        cfg["cache_offline"] = args.cache_offline == "on"
        changed = True
    if args.tts:
        cfg["tts"] = args.tts == "on"
        changed = True
    if args.tts_on_lookup:
        cfg["tts_on_lookup"] = args.tts_on_lookup == "on"
        changed = True
    if args.tts_add_translation:
        cfg["tts_add_translation"] = args.tts_add_translation == "on"
        changed = True
    if args.tts_engine:
        cfg["tts_engine"] = args.tts_engine
        changed = True
    if args.voicevox_speaker is not None:
        cfg["voicevox_speaker"] = int(args.voicevox_speaker)
        changed = True
    if args.tts_speed is not None:
        cfg["tts_speed"] = max(0.5, min(2.0, float(args.tts_speed)))
        changed = True
    if args.voicevox_host:
        cfg["voicevox_host"] = args.voicevox_host
        changed = True
    if args.tts_command is not None:
        cfg["tts_command"] = args.tts_command
        changed = True
    if args.char_limit is not None:
        cfg["translation_char_limit"] = max(10, int(args.char_limit))
        changed = True
    if args.learn_show:
        cfg["learn_show_translation"] = args.learn_show == "on"
        changed = True
    if args.learn_on_login:
        cfg["learn_on_login"] = args.learn_on_login == "on"
        changed = True
        _write_learn_autostart(args.learn_on_login == "on")
    if args.learn_greeting:
        cfg["learn_greeting"] = args.learn_greeting == "on"
        changed = True
    if args.learn_drill_repeats is not None:
        cfg["learn_drill_repeats"] = max(0, min(20, int(args.learn_drill_repeats)))
        changed = True
    if changed:
        paths.save_config(cfg)
    if args.clear_history:
        store.clear_history()
    if args.json:
        # Machine-readable: the real, unredacted config (used by the prefs UI,
        # which reads the same local file anyway).
        print(json.dumps(cfg, ensure_ascii=False))
        return 0
    if changed:
        print(f"saved {paths.CONFIG_PATH}")
    redacted = dict(cfg)
    if redacted.get("deepl_api_key"):
        redacted["deepl_api_key"] = "***set***"
    print(json.dumps(redacted, ensure_ascii=False, indent=2))
    return 0


def cmd_usage(args, cfg) -> int:
    key = args.key if args.key is not None else cfg.get("deepl_api_key", "")
    info = translation.deepl_usage(key)
    if args.json:
        print(json.dumps(info, ensure_ascii=False))
    elif info["ok"]:
        print(f"DeepL key OK — {info['used']:,} / {info['limit']:,} characters used")
    else:
        print(f"DeepL key check failed: {info['error']}", file=sys.stderr)
    return 0 if info["ok"] else 1


# Spoken when a brand-new word is captured — the game-helper "新規ゲット" banner,
# energised, announced (in its own punchy voice when VOICEVOX is on) before the
# reading, which then follows in the normal voice.
_CAPTURE_NEW_INTRO = "新規ゲット！！！"
_CAPTURE_VOICE = 82      # 青山龍星 不機嫌 — deep, heavy, low voice for the fanfare
_CAPTURE_VOICE_ALT = 81  # 青山龍星 熱血 — fallback if 不機嫌 is the selected voice


def _capture_voice(selected) -> int:
    """An energetic VOICEVOX speaker for the fanfare, distinct from the selected
    one (only matters when VOICEVOX is the engine; ignored by system voices)."""
    try:
        selected = int(selected)
    except (TypeError, ValueError):
        selected = -1
    return _CAPTURE_VOICE_ALT if selected == _CAPTURE_VOICE else _CAPTURE_VOICE


def cmd_add(args, cfg) -> int:
    """Translate words and store them in the local dictionary with no popup.

    Built for bulk entry. Input may be:
      * an OCR screen-region capture (--ocr) or image file (--ocr-image),
      * positional words (one entry each: ``zenbuji add 日本語 勉強`` adds two),
      * the current selection (--selection), or piped stdin.
    Selection/stdin/OCR text is split on newlines, so a captured or pasted list
    becomes one entry per line. The interactive OCR overlay still appears, but
    once the screenshot is taken everything happens silently — no GUI window is
    opened, so nothing steals focus (handy while a fullscreen game is open).
    """
    if args.backend:
        cfg["backend"] = args.backend
    languages = (
        [s.strip() for s in args.lang.split(",") if s.strip()]
        if args.lang
        else cfg.get("languages", ["en", "de"])
    )

    ocr_notes: list[str] = []
    want_ocr = args.ocr or args.ocr_image
    if want_ocr:
        image_path = args.ocr_image or ocr.capture_region()
        if not image_path:
            return 0  # user cancelled the region selection
        text, ocr_notes = ocr.ocr_image_to_text(image_path, cfg)
        for note in ocr_notes:
            print(note, file=sys.stderr)
        raw_items = text.splitlines()
    elif args.words:
        raw_items = list(args.words)
    elif args.selection:
        raw_items = pipeline.read_selection().splitlines()
    elif not sys.stdin.isatty():
        raw_items = sys.stdin.read().splitlines()
    else:
        raw_items = []

    # Trim, drop blanks, and de-duplicate while preserving order.
    seen: set[str] = set()
    items: list[str] = []
    for item in raw_items:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            items.append(item)

    if not items:
        if want_ocr:
            print("No text recognised in the image.", file=sys.stderr)
            return 1
        print("No input (give words, use --selection, --ocr, or pipe stdin).",
              file=sys.stderr)
        return 2

    # TTS is opt-in: the --speak flag, or a `tts: true` config default that
    # --no-speak can override for a single run.
    speak_on = bool(args.speak or (cfg.get("tts", False) and not args.no_speak))

    # The dictionary stores DeepL output, and Argos output only when
    # `cache_offline` is on, so warn up front if the current settings would
    # store nothing — otherwise a bulk add looks like it silently did nothing.
    key = cfg.get("deepl_api_key", "")
    backend = cfg.get("backend", "auto")
    effective = ("deepl" if key else "argos") if backend == "auto" else backend
    will_store = bool(cfg.get("dictionary", True) and (
        (effective == "deepl" and key) or cfg.get("cache_offline", False)))
    if not will_store and not args.json:
        print("note: nothing will be stored with the current settings — use the "
              "DeepL backend, or enable 'cache offline translations' "
              "(zenbuji config --cache-offline on), with the dictionary on.",
              file=sys.stderr)

    results = []
    added = 0
    for text in items:
        result = pipeline.process(text, languages, cfg, do_translate=True)
        stored = will_store and bool(result.translations)
        added += int(stored)
        results.append(result)
        if not args.quiet and not args.json:
            tr = "; ".join(f"{lang_code}: {result.translations[lang_code]}"
                           for lang_code in languages if result.translations.get(lang_code))
            reading = f"（{result.reading}）" if result.reading else ""
            mark = "✓" if stored else "·"
            print(f"{mark} {text}{reading}" + (f" — {tr}" if tr else ""))

    if speak_on:
        speak_tr = bool(cfg.get("tts_add_translation", False))
        # Speak in the same order the game overlay reveals things: the reading,
        # then the translation, then (for a brand-new word) the energetic
        # "新規ゲット" fanfare last, in its own VOICEVOX voice. Each call blocks so
        # this short-lived process doesn't exit mid-audio.
        sequence = []
        any_new = False
        for r in results:
            jp = r.reading or r.text
            if jp:
                sequence.append((jp, cfg))
            en = r.translations.get("en") if speak_tr else None
            if en:
                sequence.append((f"英語で、{en}", cfg))
            entry = store.dict_get(r.text)
            if entry and entry.get("count") == 1:
                any_new = True
        if any_new:
            sel = cfg.get("voicevox_speaker", tts.VOICEVOX_DEFAULT_SPEAKER)
            intro_cfg = {**cfg, "voicevox_speaker": _capture_voice(sel)}
            sequence.append((_CAPTURE_NEW_INTRO, intro_cfg))
        for text, voice_cfg in sequence:
            tts.speak(text, voice_cfg, block=True)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], ensure_ascii=False))
    elif not args.quiet:
        noun = "entry" if len(items) == 1 else "entries"
        print(f"Added {added}/{len(items)} {noun} to the dictionary.")
    return 0


def cmd_voices(args, cfg) -> int:
    """List the speakers/styles the local VOICEVOX engine offers.

    Used by the prefs voice picker (via --json) and handy for finding a speaker
    id for `zenbuji config --voicevox-speaker`.
    """
    host = cfg.get("voicevox_host", tts.VOICEVOX_DEFAULT_HOST)
    try:
        with urllib.request.urlopen(f"http://{host}/speakers", timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 — engine simply not running
        if args.json:
            print("[]")
        else:
            print(f"VOICEVOX engine not reachable at {host} ({exc}).",
                  file=sys.stderr)
            print("Set it up with: ./install.sh --voicevox", file=sys.stderr)
        return 1
    voices = [{"id": style["id"], "name": s["name"], "style": style["name"]}
              for s in data for style in s.get("styles", [])]
    voices.sort(key=lambda v: v["id"])
    if args.json:
        print(json.dumps(voices, ensure_ascii=False))
    else:
        for v in voices:
            print(f"{v['id']:>4}  {v['name']} — {v['style']}")
    return 0


def cmd_voicevox(args, cfg) -> int:
    """Control the local VOICEVOX engine's systemd --user service.

    `zenbuji voicevox [start|stop|restart|status]` (default start). start is a
    no-op if it's already running, so it's safe to call anytime.
    """
    if not shutil.which("systemctl"):
        print("systemctl not found (not a systemd user session?).", file=sys.stderr)
        return 1
    action = args.action or "start"
    svc = "voicevox.service"
    if action == "status":
        r = subprocess.run(["systemctl", "--user", "is-active", svc],
                           capture_output=True, text=True)
        state = (r.stdout or "").strip() or "unknown"
        print(state)
        return 0 if state == "active" else 1
    r = subprocess.run(["systemctl", "--user", action, svc],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"could not {action} {svc}: {(r.stderr or '').strip()}", file=sys.stderr)
        print("Is it set up? Run: ./install.sh --voicevox", file=sys.stderr)
        return 1
    print(f"voicevox: {action} ok")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = paths.load_config()

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
        "config", "models", "usage", "ocr", "dict", "export", "learn", "stats",
        "game", "add", "speak", "voices", "voicevox", "about",
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
    if command == "add":
        p = argparse.ArgumentParser(prog="zenbuji add", add_help=False)
        p.add_argument("--lang")
        p.add_argument("--backend", choices=["argos", "deepl", "auto"])
        p.add_argument("--selection", action="store_true")
        p.add_argument("--ocr", action="store_true",
                       help="capture a screen region and OCR it")
        p.add_argument("--ocr-image", dest="ocr_image",
                       help="OCR an existing image file")
        p.add_argument("--speak", action="store_true",
                       help="read the word aloud after adding")
        p.add_argument("--no-speak", dest="no_speak", action="store_true",
                       help="don't read aloud even if tts is on in config")
        p.add_argument("--quiet", "-q", action="store_true",
                       help="suppress the per-word summary")
        p.add_argument("--json", action="store_true")
        p.add_argument("words", nargs="*")
        return cmd_add(p.parse_args(rest), cfg)

    if command == "config":
        p = argparse.ArgumentParser(prog="zenbuji config")
        p.add_argument("--backend", choices=["argos", "deepl", "auto"])
        p.add_argument("--lang")
        p.add_argument("--deepl-key", dest="deepl_key")
        p.add_argument("--history", choices=["on", "off"])
        p.add_argument("--ui-language", dest="ui_language", choices=["en", "ja"])
        p.add_argument("--popup-close-on-focus-loss", dest="popup_close",
                       choices=["on", "off"])
        p.add_argument("--dictionary", choices=["on", "off"])
        p.add_argument("--cache-offline", dest="cache_offline",
                       choices=["on", "off"],
                       help="also store Argos (offline) translations in the dictionary")
        p.add_argument("--tts", choices=["on", "off"],
                       help="read words aloud after an OCR/silent add by default")
        p.add_argument("--tts-on-lookup", dest="tts_on_lookup",
                       choices=["on", "off"],
                       help="read the reading aloud automatically after a popup lookup")
        p.add_argument("--tts-add-translation", dest="tts_add_translation",
                       choices=["on", "off"],
                       help="after an OCR add, also speak the English translation (英語で…)")
        p.add_argument("--tts-engine", dest="tts_engine",
                       choices=["auto", "voicevox", "system", "command", "off"],
                       help="text-to-speech engine (default auto)")
        p.add_argument("--voicevox-speaker", dest="voicevox_speaker", type=int,
                       help="VOICEVOX speaker/style id (list them: zenbuji voices)")
        p.add_argument("--tts-speed", dest="tts_speed", type=float,
                       help="speaking rate, 1.0 = normal (clamped to 0.5–2.0)")
        p.add_argument("--voicevox-host", dest="voicevox_host",
                       help="VOICEVOX engine host:port (default 127.0.0.1:50021)")
        p.add_argument("--tts-command", dest="tts_command",
                       help="custom text-to-speech command ('' to reset); "
                            "use {text} as the placeholder")
        p.add_argument("--translation-char-limit", dest="char_limit", type=int)
        p.add_argument("--learn-show-translation", dest="learn_show",
                       choices=["on", "off"])
        p.add_argument("--learn-on-login", dest="learn_on_login",
                       choices=["on", "off"])
        p.add_argument("--learn-greeting", dest="learn_greeting",
                       choices=["on", "off"],
                       help="show/speak a random greeting when practice opens")
        p.add_argument("--learn-drill-repeats", dest="learn_drill_repeats",
                       type=int,
                       help="retype a missed reading this many times (0 = off)")
        p.add_argument("--clear-history", action="store_true")
        p.add_argument("--json", action="store_true")
        return cmd_config(p.parse_args(rest), cfg)

    if command == "speak":
        p = argparse.ArgumentParser(prog="zenbuji speak", add_help=False)
        p.add_argument("--selection", action="store_true",
                       help="read the current text selection aloud")
        p.add_argument("words", nargs="*")
        a = p.parse_args(rest)
        text = " ".join(a.words).strip()
        if not text and (a.selection or not sys.stdin.isatty()):
            text = (pipeline.read_selection() if a.selection else sys.stdin.read()).strip()
        elif not text:
            text = pipeline.read_selection().strip()
        if not text:
            print("No text to speak (give words, --selection, or pipe stdin).",
                  file=sys.stderr)
            return 2
        tts.speak(text, cfg, block=True)
        return 0

    if command == "voices":
        p = argparse.ArgumentParser(prog="zenbuji voices")
        p.add_argument("--json", action="store_true")
        return cmd_voices(p.parse_args(rest), cfg)

    if command == "voicevox":
        p = argparse.ArgumentParser(prog="zenbuji voicevox")
        p.add_argument("action", nargs="?",
                       choices=["start", "stop", "restart", "status"],
                       default="start")
        return cmd_voicevox(p.parse_args(rest), cfg)

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

    if command == "dict":
        p = argparse.ArgumentParser(prog="zenbuji dict")
        p.add_argument("--json", action="store_true",
                       help="print the dictionary as JSON")
        p.add_argument("--clear", action="store_true",
                       help="erase the whole local dictionary")
        a = p.parse_args(rest)
        if a.clear:
            store.clear_dict()
            print("dictionary cleared")
            return 0
        if a.json:
            print(json.dumps(store.load_dict(), ensure_ascii=False))
            return 0
        return launch_dictionary(cfg)

    if command == "learn":
        p = argparse.ArgumentParser(prog="zenbuji learn")
        p.add_argument("--on-login", dest="on_login", action="store_true",
                       help="open at most once per day (for the autostart entry)")
        a = p.parse_args(rest)
        if a.on_login:
            today = datetime.now().date().isoformat()
            try:
                seen = paths.LAST_LEARN_PATH.read_text(encoding="utf-8").strip()
            except OSError:
                seen = ""
            if seen == today:
                return 0  # already practised today
            try:
                paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
                paths.LAST_LEARN_PATH.write_text(today, encoding="utf-8")
            except OSError:
                pass
        return launch_learning(cfg)

    if command == "stats":
        p = argparse.ArgumentParser(prog="zenbuji stats")
        p.add_argument("--json", action="store_true",
                       help="print the statistics as JSON")
        a = p.parse_args(rest)
        if a.json:
            print(json.dumps(srs.srs_stats(), ensure_ascii=False))
            return 0
        return launch_stats(cfg)

    if command == "export":
        p = argparse.ArgumentParser(prog="zenbuji export")
        p.add_argument("--format", choices=["tsv", "csv"], default="tsv",
                       help="output format (default tsv — Anki-native)")
        p.add_argument("--all", action="store_true",
                       help="include entries excluded from practice")
        p.add_argument("--no-header", dest="header", action="store_false",
                       help="omit the Anki #separator/#columns header lines")
        p.add_argument("--lang", help="languages to export (comma separated; "
                       "default from config)")
        p.add_argument("-o", "--output",
                       help="write to a file instead of standard output")
        a = p.parse_args(rest)
        languages = (
            [s.strip() for s in a.lang.split(",") if s.strip()]
            if a.lang else cfg.get("languages", ["en", "de"])
        )
        text, count = exporting.dict_to_anki(
            store.load_dict(), languages, fmt=a.format,
            include_excluded=a.all, header=a.header)
        if a.output:
            out = Path(a.output).expanduser()
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
            except OSError as e:
                print(f"could not write {out}: {e}", file=sys.stderr)
                return 1
            print(f"exported {count} cards to {out}")
        else:
            # No trailing blank line on top of csv.writer's own newlines.
            sys.stdout.write(text)
        return 0

    if command == "game":
        argparse.ArgumentParser(prog="zenbuji game").parse_args(rest)
        return launch_game(cfg)

    if command == "about":
        argparse.ArgumentParser(prog="zenbuji about").parse_args(rest)
        return launch_about(cfg)

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
            image_path = ocr.capture_region()
            if not image_path:
                return 0  # user cancelled the region selection
        if command == "popup":
            return launch_popup(None, languages, cfg, ocr_image=image_path)
        text, ocr_notes = ocr.ocr_image_to_text(image_path, cfg)
        if not text.strip():
            for note in ocr_notes:
                print(note, file=sys.stderr)
            print("No text recognised in the image.", file=sys.stderr)
            return 1
    else:
        use_selection = opts.selection or command == "selection"
        text = pipeline.resolve_input(opts.words, use_selection)
        if not text.strip():
            print("No input text (give text, use --selection, --ocr, or pipe stdin).",
                  file=sys.stderr)
            return 2

    if command == "popup":
        return launch_popup(text, languages, cfg)

    do_translate = command not in ("furigana",)
    result = pipeline.process(text, languages, cfg, do_translate=do_translate)
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
        print(pipeline.render_text(result, render_langs))
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
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from zenbuji_popup import show_popup

    def process_fn(t):
        return pipeline.process(t, languages, cfg, do_translate=True)

    def ocr_fn(img):
        return ocr.ocr_image_to_text(img, cfg)

    def speak_fn(t):
        tts.speak(t, cfg)

    ui_language = cfg.get("ui_language", "en")
    close_on_focus_loss = bool(cfg.get("popup_close_on_focus_loss", True))
    char_limit = int(cfg.get("translation_char_limit", 200) or 200)
    auto_speak = bool(cfg.get("tts_on_lookup", False))

    # OCR popups always persist until Escape/closed: you read and often correct
    # the recognised text, and the zenbuji extension hands focus back to a
    # fullscreen game underneath (which would otherwise dismiss the popup the
    # instant it appears). Close-on-focus-loss only makes sense for the quick
    # selection HUD.
    if ocr_image:
        close_on_focus_loss = False

    def quota_fn():
        # Background DeepL quota for the popup's small status node; None when no
        # key (the popup then hides the node).
        key = cfg.get("deepl_api_key", "")
        return translation.deepl_usage(key) if key else None

    if ocr_image:
        return show_popup(languages, ocr_image=ocr_image,
                          process_fn=process_fn, ocr_fn=ocr_fn,
                          ui_language=ui_language,
                          close_on_focus_loss=close_on_focus_loss,
                          quota_fn=quota_fn, char_limit=char_limit,
                          speak_fn=speak_fn, auto_speak=auto_speak)
    result = process_fn(text) if text else None
    return show_popup(languages, result=result,
                      process_fn=process_fn, ocr_fn=ocr_fn,
                      ui_language=ui_language,
                      close_on_focus_loss=close_on_focus_loss,
                      quota_fn=quota_fn, char_limit=char_limit,
                      speak_fn=speak_fn, auto_speak=auto_speak)


# Game-helper shortcut panel: only the silent background-add actions are useful
# while gaming (lookups/practice steal focus). (slug, default accel, label key.)
_SHORTCUT_SPEC = [
    ("zenbuji-ocr-add", "<Super><Shift>k", "ocr_add"),
    ("zenbuji-add",     "<Super>k",        "add_selection"),
]
_SHORTCUT_LABELS = {
    "ocr_add":       {"en": "Capture & add (OCR)", "ja": "画面領域を追加（OCR）"},
    "add_selection": {"en": "Add selection",       "ja": "選択を追加"},
}


def _read_keybinding(slug: str) -> str | None:
    """The live accelerator for a zenbuji custom keybinding, or None."""
    try:
        from gi.repository import Gio
        schema = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
        src = Gio.SettingsSchemaSource.get_default()
        if src is None or src.lookup(schema, True) is None:
            return None
        path = ("/org/gnome/settings-daemon/plugins/media-keys/"
                f"custom-keybindings/{slug}/")
        binding = Gio.Settings.new_with_path(schema, path).get_string("binding")
        return binding or None
    except Exception:  # noqa: BLE001
        return None


def _pretty_accel(accel: str) -> str:
    """'<Super><Shift>k' -> 'Super+Shift+K'."""
    parts = re.findall(r"<([^>]+)>", accel)
    rest = re.sub(r"<[^>]+>", "", accel).strip()
    if rest:
        parts.append(rest.upper() if len(rest) == 1 else rest.capitalize())
    return "+".join(parts) if parts else accel


def shortcuts_info(ui_language: str = "en") -> list:
    """Localized [{keys, label}] for the game-helper shortcut panel.

    Reads the user's live bindings when available, else the install defaults.
    """
    out = []
    for slug, default, key in _SHORTCUT_SPEC:
        accel = _read_keybinding(slug) or default
        label = _SHORTCUT_LABELS[key].get(ui_language) or _SHORTCUT_LABELS[key]["en"]
        out.append({"keys": _pretty_accel(accel), "label": label})
    return out


def launch_game(cfg: dict) -> int:
    """Show the trimmed game-helper overlay (live dictionary + shortcuts + status)."""
    try:
        from zenbuji_dict import show_dictionary
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from zenbuji_dict import show_dictionary

    return show_dictionary(
        ui_language=cfg.get("ui_language", "en"),
        languages=cfg.get("languages", ["en", "de"]),
        load_fn=srs.dict_with_srs,
        delete_fn=store.dict_delete,
        clear_fn=store.clear_dict,
        stats_fn=store.dict_stats,
        speak_fn=lambda t: tts.speak(t, cfg),
        game_mode=True,
        shortcuts=shortcuts_info(cfg.get("ui_language", "en")),
        busy_path=paths.BUSY_PATH,
        watch_path=paths.DICT_PATH,   # live-refresh the overlay as words are added
    )


def launch_dictionary(cfg: dict) -> int:
    """Show the GTK dictionary window (browse/manage cached DeepL lookups)."""
    try:
        from zenbuji_dict import show_dictionary
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from zenbuji_dict import show_dictionary

    def refresh_fn(text, targets):
        """Force a fresh DeepL translation for `text` and re-cache it."""
        key = cfg.get("deepl_api_key", "")
        lang_ui = cfg.get("ui_language", "en")
        if not key:
            return None
        reading, _tokens = lang.analyze(text)
        fresh = translation.translate_deepl(text, targets, key, lang_ui)
        return store.dict_record(text, reading, fresh)

    return show_dictionary(
        ui_language=cfg.get("ui_language", "en"),
        languages=cfg.get("languages", ["en", "de"]),
        load_fn=srs.dict_with_srs,
        delete_fn=store.dict_delete,
        clear_fn=store.clear_dict,
        stats_fn=store.dict_stats,
        refresh_fn=refresh_fn,
        update_fn=store.dict_update_translations,
        set_exclude_fn=store.dict_set_exclude,
        watch_path=paths.DICT_PATH,
        quota_fn=lambda: (translation.deepl_usage(cfg.get("deepl_api_key", ""))
                          if cfg.get("deepl_api_key") else None),
        speak_fn=lambda t: tts.speak(t, cfg),
    )


def _zenbuji_version() -> str | None:
    """The release version stamped into the extension metadata, or None.

    `version-name` is written by the packaging workflow at release time, so a
    plain source checkout has no version — the About window then shows
    "Development build".
    """
    meta = (Path(__file__).resolve().parent.parent.parent
            / "extension" / "zenbuji@meeksi39" / "metadata.json")
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        return data.get("version-name") or None
    except (OSError, ValueError):
        return None


def launch_about(cfg: dict) -> int:
    """Show the About window (logo, version, project link)."""
    try:
        from zenbuji_about import show_about
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from zenbuji_about import show_about

    return show_about(
        ui_language=cfg.get("ui_language", "en"),
        version=_zenbuji_version(),
    )


def launch_stats(cfg: dict) -> int:
    """Show the SRS statistics window."""
    try:
        from zenbuji_stats import show_statistics
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from zenbuji_stats import show_statistics

    return show_statistics(
        ui_language=cfg.get("ui_language", "en"),
        languages=cfg.get("languages", ["en", "de"]),
        stats_fn=srs.srs_stats,
    )


def launch_learning(cfg: dict) -> int:
    """Show the SRS learning/quiz window over the cached dictionary."""
    try:
        from zenbuji_learn import show_learning
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from zenbuji_learn import show_learning

    show_tr = bool(cfg.get("learn_show_translation", True))
    count = int(cfg.get("learn_count", 10) or 10)
    cards = srs.srs_select(count)
    # Keep 0 (drill off) distinct from "unset" — no `or` fallback here.
    drill = cfg.get("learn_drill_repeats", 5)
    drill = max(0, int(drill)) if drill is not None else 5

    def grade_fn(card, reading_in, translation_in):
        return grade.grade_answer(card, reading_in, translation_in,
                                  test_translation=not show_tr)

    def review_fn(text, correct):
        st = srs.srs_review(text, correct)
        return {"status": srs.srs_status(st), "interval": st.get("interval", 0),
                "due": st.get("due")}

    return show_learning(
        cards=cards,
        show_translation=show_tr,
        languages=cfg.get("languages", ["en", "de"]),
        ui_language=cfg.get("ui_language", "en"),
        grade_fn=grade_fn,
        review_fn=review_fn,
        speak_fn=lambda t: tts.speak(t, cfg),
        auto_speak=bool(cfg.get("tts_on_lookup", False)),
        greeting=bool(cfg.get("learn_greeting", True)),
        drill_repeats=drill,
        match_reading_fn=grade.reading_matches,
        speak_phrase_fn=lambda t: tts.phrase_speaker(t, cfg),
    )
