"""State-file locations and configuration load/save.

These path constants are the seam the test suite redirects at a temp dir
(``monkeypatch.setattr(zenbuji.paths, "DATA_DIR", ...)``), so every other module
reads them **module-qualified** (``paths.DICT_PATH``) — never ``from .paths
import DICT_PATH`` — so a patch here is seen everywhere.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "zenbuji"
CONFIG_PATH = CONFIG_DIR / "config.json"

DATA_DIR = Path(
    os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
) / "zenbuji"
HISTORY_PATH = DATA_DIR / "history.json"
# Local dictionary of cached DeepL translations (see the Dictionary section).
DICT_PATH = DATA_DIR / "dictionary.json"
# Spaced-repetition learning state, keyed by text (see the SRS section).
SRS_PATH = DATA_DIR / "srs.json"
# Daily review tallies for the statistics window (streak + recent activity).
ACTIVITY_PATH = DATA_DIR / "activity.json"
# Transient marker so the game-helper can show when a translation/OCR is running.
BUSY_PATH = DATA_DIR / "busy.json"
# Date-stamp so the "open on login" autostart fires at most once per day.
LAST_LEARN_PATH = DATA_DIR / "last_learn.txt"
# Regenerable caches live under the XDG cache dir, not DATA_DIR. TTS_CACHE_DIR
# holds synthesized VOICEVOX WAVs keyed by text+voice+speed (see tts.py).
CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
) / "zenbuji"
TTS_CACHE_DIR = CACHE_DIR / "tts"
AUTOSTART_PATH = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "autostart" / "zenbuji-learn.desktop"

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
    # Cache DeepL translations locally and reuse them (builds a personal
    # dictionary, saves quota). Only affects the DeepL backend.
    "dictionary": True,
    # Max characters accepted in the popup's translation input.
    "translation_char_limit": 200,
    # Learning quiz: show the translation as a hint (test reading only) vs hide
    # it (test reading + translation); open once a day on login; cards per round.
    "learn_show_translation": True,
    "learn_on_login": False,
    "learn_count": 10,
    # When a reading is missed in the quiz, drill it in by making me retype the
    # correct reading this many times (each retype is read aloud). 0 disables the
    # drill and just shows the old Got it / Missed buttons.
    "learn_drill_repeats": 5,
    # Show (and, with TTS auto-read on, speak) a random casual greeting when a
    # practice round opens.
    "learn_greeting": True,
    # Text-to-speech (read words aloud). Engine: "auto" (a local VOICEVOX engine
    # if it is reachable, else the system voice), "voicevox", "system"
    # (spd-say/espeak-ng), "command" (run tts_command), or "off".
    "tts": False,
    # Automatically read the reading aloud after a popup lookup (Super+J etc.).
    "tts_on_lookup": False,
    # After a background OCR add (--speak), also read the English translation
    # aloud, prefixed with 「英語で」 ("in English"). VOICEVOX is Japanese-only,
    # so the English is approximated in katakana — fine as a vocab cue.
    "tts_add_translation": False,
    "tts_engine": "auto",
    # Local VOICEVOX engine — natural Japanese neural TTS, run via podman (see
    # install.sh --voicevox). host:port of its HTTP API, and the speaker id.
    "voicevox_host": "127.0.0.1:50021",
    "voicevox_speaker": 3,  # ずんだもん (Zundamon), normal style
    # Speaking rate, 1.0 = normal. Drives VOICEVOX speedScale (0.5–2.0) and the
    # system voice's rate; applies to every spoken phrase.
    "tts_speed": 1.0,
    # Custom TTS command template ({text} placeholder); when set it overrides
    # tts_engine. Left here mostly for power users / other engines.
    "tts_command": "",
}


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
