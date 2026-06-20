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
import difflib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
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
# Dictionary (persistent cache of DeepL translations + usage stats)
# --------------------------------------------------------------------------- #
def load_dict() -> dict:
    """Load the local dictionary: {text: {reading, translations, count, …}}."""
    try:
        if DICT_PATH.exists():
            data = json.loads(DICT_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def save_dict(data: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DICT_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def dict_get(text: str) -> dict | None:
    return load_dict().get(text.strip())


def dict_delete(text: str) -> None:
    data = load_dict()
    if data.pop(text.strip(), None) is not None:
        save_dict(data)


def clear_dict() -> None:
    try:
        DICT_PATH.unlink()
    except (FileNotFoundError, OSError):
        pass


def dict_stats() -> dict:
    """Totals for the dictionary window header."""
    data = load_dict()
    total_lookups = sum(int(e.get("count", 0)) for e in data.values())
    return {
        "entries": len(data),
        "lookups": total_lookups,
        # Every lookup beyond the first of each entry was served from cache.
        "saved": max(0, total_lookups - len(data)),
    }


def dict_record(text: str, reading: str, deepl_translations: dict) -> dict:
    """Create or update a dictionary entry from DeepL output.

    Merges new target languages into the stored translations, bumps the lookup
    count, and stamps first/last seen. Only DeepL-sourced translations are ever
    passed here. Returns the updated entry.
    """
    text = text.strip()
    if not text:
        return {}
    data = load_dict()
    # Monotonic, microsecond-precision last_seen so the most-recently-recorded
    # entry always sorts to the top — even when several are recorded within the
    # same clock second (seconds precision used to tie and scramble the order).
    now_dt = datetime.now()
    latest = max((d for e in data.values()
                  if (d := _due_date_dt(e.get("last_seen"))) is not None),
                 default=None)
    if latest is not None and now_dt <= latest:
        now_dt = latest + timedelta(microseconds=1)
    now = now_dt.isoformat()
    entry = data.get(text) or {
        "text": text,
        "reading": reading,
        "translations": {},
        "count": 0,
        "first_seen": now,
        "last_seen": now,
    }
    entry["reading"] = reading or entry.get("reading", "")
    merged = dict(entry.get("translations", {}))
    merged.update({k: v for k, v in deepl_translations.items() if v})
    entry["translations"] = merged
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last_seen"] = now
    entry.setdefault("first_seen", now)
    data[text] = entry
    save_dict(data)
    return entry


def dict_update_translations(text: str, translations: dict) -> dict | None:
    """Manually correct an entry's translations (no lookup-count bump).

    Replaces the given languages' values; a blank value drops that language.
    Other languages, the reading, count and timestamps are left untouched.
    Returns the updated entry, or None if there's no such entry.
    """
    text = text.strip()
    data = load_dict()
    entry = data.get(text)
    if entry is None:
        return None
    merged = dict(entry.get("translations", {}))
    for lang, val in translations.items():
        val = (val or "").strip()
        if val:
            merged[lang] = val
        else:
            merged.pop(lang, None)
    entry["translations"] = merged
    data[text] = entry
    save_dict(data)
    return entry


def dict_set_exclude(text: str, excluded: bool) -> None:
    """Flag (or unflag) an entry as excluded from the practice quiz/SRS."""
    text = text.strip()
    data = load_dict()
    entry = data.get(text)
    if entry is None:
        return
    if excluded:
        entry["exclude"] = True
    else:
        entry.pop("exclude", None)
    data[text] = entry
    save_dict(data)


# --------------------------------------------------------------------------- #
# Spaced repetition (SRS) — a learning schedule layered over the dictionary
# --------------------------------------------------------------------------- #
SRS_DEFAULT_EASE = 2.5


def load_srs() -> dict:
    try:
        if SRS_PATH.exists():
            data = json.loads(SRS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def save_srs(data: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SRS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def srs_get(text: str) -> dict | None:
    return load_srs().get(text.strip())


def _new_srs() -> dict:
    return {"ease": SRS_DEFAULT_EASE, "interval": 0, "reps": 0, "lapses": 0,
            "due": None, "last_reviewed": None, "correct": 0, "wrong": 0}


def srs_status(state: dict | None) -> str:
    """Coarse learning stage for display: new / learning / young / mature."""
    if not state or not state.get("last_reviewed"):
        return "new"
    interval = state.get("interval", 0)
    if interval < 7:
        return "learning"
    if interval < 21:
        return "young"
    return "mature"


def srs_review(text: str, correct: bool) -> dict:
    """Apply one SM-2-lite review and persist. Returns the updated state."""
    text = text.strip()
    data = load_srs()
    s = data.get(text) or _new_srs()
    ease = float(s.get("ease", SRS_DEFAULT_EASE))
    interval = float(s.get("interval", 0))
    reps = int(s.get("reps", 0))
    if correct:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = round(interval * ease)
        s["correct"] = int(s.get("correct", 0)) + 1
    else:
        reps = 0
        interval = 0  # due again right away
        ease = max(1.3, ease - 0.2)
        s["lapses"] = int(s.get("lapses", 0)) + 1
        s["wrong"] = int(s.get("wrong", 0)) + 1
    now = datetime.now()
    s["ease"] = round(ease, 2)
    s["interval"] = interval
    s["reps"] = reps
    s["last_reviewed"] = now.isoformat(timespec="seconds")
    s["due"] = (now + timedelta(days=interval)).isoformat(timespec="seconds")
    data[text] = s
    save_srs(data)
    log_activity(correct)
    return s


def srs_select(limit: int = 10) -> list:
    """Pick cards to review from the dictionary, most-due first.

    Never-reviewed entries sort first (treated as maximally due), then by due
    date ascending. Only entries with a reading and at least one translation
    qualify.
    """
    d = load_dict()
    srs = load_srs()
    candidates = []
    for text, e in d.items():
        if e.get("exclude"):
            continue
        if not e.get("reading"):
            continue
        if not any((e.get("translations") or {}).values()):
            continue
        st = srs.get(text)
        due = (st or {}).get("due") or ""  # "" (never reviewed) sorts first
        candidates.append((due, text, e, st))
    candidates.sort(key=lambda c: c[0])
    cards = []
    for _due, text, e, st in candidates[:limit]:
        cards.append({
            "text": text,
            "reading": e.get("reading", ""),
            "translations": e.get("translations", {}),
            "status": srs_status(st),
        })
    return cards


# --- Daily activity log (powers the statistics streak + recent graph) ------ #
def load_activity() -> dict:
    """Per-day review tallies: {"YYYY-MM-DD": {"reviews": int, "correct": int}}."""
    try:
        if ACTIVITY_PATH.exists():
            data = json.loads(ACTIVITY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def save_activity(data: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVITY_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def log_activity(correct: bool) -> None:
    """Record one review against today's tally (called from srs_review)."""
    data = load_activity()
    today = datetime.now().date().isoformat()
    day = data.get(today) or {"reviews": 0, "correct": 0}
    day["reviews"] = int(day.get("reviews", 0)) + 1
    if correct:
        day["correct"] = int(day.get("correct", 0)) + 1
    data[today] = day
    save_activity(data)


def activity_streak(data: dict | None = None) -> int:
    """Consecutive days with at least one review, counting back from today.

    Today not yet practised doesn't break the streak — we start from yesterday
    in that case so an unfinished day still shows the run you're on.
    """
    if data is None:
        data = load_activity()
    today = datetime.now().date()
    cur = today
    if data.get(today.isoformat(), {}).get("reviews", 0) <= 0:
        cur = today - timedelta(days=1)
    streak = 0
    while data.get(cur.isoformat(), {}).get("reviews", 0) > 0:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def activity_recent(days: int = 14, data: dict | None = None) -> list:
    """The last `days` days (oldest→newest) as {date, reviews, correct}."""
    if data is None:
        data = load_activity()
    today = datetime.now().date()
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        day = data.get(d, {})
        out.append({"date": d,
                    "reviews": int(day.get("reviews", 0)),
                    "correct": int(day.get("correct", 0))})
    return out


# --- Background-busy marker (read by the game-helper window) ---------------- #
def set_busy(stage: str) -> None:
    """Mark that a translation/OCR is running (stage: 'reading' | 'translating')."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BUSY_PATH.write_text(
            json.dumps({"stage": stage,
                        "ts": datetime.now().isoformat(timespec="seconds")}),
            encoding="utf-8")
    except OSError:
        pass


def clear_busy() -> None:
    try:
        BUSY_PATH.unlink()
    except (FileNotFoundError, OSError):
        pass


def read_busy(max_age: float = 120.0) -> dict | None:
    """Current busy state, or None when idle/stale (a crashed run can't stick)."""
    try:
        data = json.loads(BUSY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ts = _due_date_dt(data.get("ts"))
    try:
        if ts is not None and (datetime.now() - ts).total_seconds() > max_age:
            return None
    except TypeError:  # mismatched naive/aware timestamp — treat as fresh
        pass
    return data if isinstance(data, dict) else None


def _due_date_dt(iso: str):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _due_date(iso: str):
    """Parse an SRS due/last-reviewed ISO stamp to a date, or None."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        return None


def srs_summary(text: str, srs: dict | None = None) -> dict | None:
    """Compact per-card SRS info for the dictionary rows, or None if unstudied."""
    st = (srs if srs is not None else load_srs()).get(text.strip())
    if not st:
        return None
    return {
        "level": srs_status(st),
        "due": st.get("due"),
        "correct": int(st.get("correct", 0)),
        "wrong": int(st.get("wrong", 0)),
    }


def dict_with_srs() -> dict:
    """Dictionary entries annotated with their SRS summary (level/due/…).

    Used by the dictionary + game-helper windows so each row can show its
    learning level; `load_dict` itself stays SRS-free for every other caller.
    """
    srs = load_srs()
    data = load_dict()
    for text, entry in data.items():
        entry["srs"] = srs_summary(text, srs)
    return data


def srs_stats() -> dict:
    """Aggregate the whole learning state for the statistics window."""
    d = load_dict()
    srs = load_srs()
    today = datetime.now().date()
    # Words excluded from practice don't count toward the learning stats.
    excluded = {text for text, e in d.items() if e.get("exclude")}

    by_level = {"new": 0, "learning": 0, "young": 0, "mature": 0}
    total = reviewed = due_now = due_today = 0
    for text, e in d.items():
        if text in excluded:
            continue
        if not e.get("reading"):
            continue
        if not any((e.get("translations") or {}).values()):
            continue
        total += 1
        st = srs.get(text)
        by_level[srs_status(st)] += 1
        if st and st.get("last_reviewed"):
            reviewed += 1
        due = _due_date((st or {}).get("due"))
        if due is not None and due <= today:
            due_today += 1
            if (st or {}).get("interval", 0) == 0 or due < today:
                due_now += 1

    reviews_total = correct_total = wrong_total = lapses_total = 0
    hardest = []
    for text, st in srs.items():
        if text in excluded:
            continue
        c, w = int(st.get("correct", 0)), int(st.get("wrong", 0))
        correct_total += c
        wrong_total += w
        reviews_total += c + w
        lapses_total += int(st.get("lapses", 0))
        if w or int(st.get("lapses", 0)):
            e = d.get(text, {})
            hardest.append({"text": text, "reading": e.get("reading", ""),
                            "lapses": int(st.get("lapses", 0)),
                            "wrong": w, "correct": c})
    hardest.sort(key=lambda h: (h["lapses"], h["wrong"]), reverse=True)

    activity = load_activity()
    today_day = activity.get(today.isoformat(), {})
    accuracy = (correct_total / reviews_total) if reviews_total else None
    return {
        "total": total,
        "reviewed": reviewed,
        "by_level": by_level,
        "due_now": due_now,
        "due_today": due_today,
        "reviews_total": reviews_total,
        "correct_total": correct_total,
        "wrong_total": wrong_total,
        "accuracy": accuracy,
        "lapses_total": lapses_total,
        "hardest": hardest[:5],
        "streak": activity_streak(activity),
        "today_reviews": int(today_day.get("reviews", 0)),
        "today_correct": int(today_day.get("correct", 0)),
        "recent": activity_recent(14, activity),
    }


# --- Answer grading ------------------------------------------------------- #
_PUNCT_RE = re.compile(r"[.,!?;:\"'()\[\]{}。、！？・…]+")


def _norm_reading(s: str) -> str:
    s = kata_to_hira((s or "").strip())
    for ch in (" ", "　", "・"):
        s = s.replace(ch, "")
    return s


def _norm_text(s: str) -> str:
    s = (s or "").strip().casefold()
    s = _PUNCT_RE.sub("", s)
    s = re.sub(r"[\s　]+", " ", s)
    return s.strip()


def grade_answer(card: dict, reading_in: str, translation_in: str,
                 *, test_translation: bool = True) -> dict:
    """Grade a quiz answer. Reading is exact (kana-normalised); translation is
    fuzzy (exact or SequenceMatcher ratio >= 0.8 against EN or DE)."""
    reading_ok = _norm_reading(reading_in) == _norm_reading(card.get("reading", ""))
    translations = card.get("translations", {})
    translation_ok = None
    if test_translation:
        ans = _norm_text(translation_in)
        translation_ok = False
        if ans:
            for val in translations.values():
                t = _norm_text(val)
                if t and (ans == t
                          or difflib.SequenceMatcher(None, ans, t).ratio() >= 0.8):
                    translation_ok = True
                    break
    return {
        "reading_ok": reading_ok,
        "translation_ok": translation_ok,
        "correct_reading": card.get("reading", ""),
        "correct_translations": translations,
    }


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
        set_busy("reading")
        with _quiet_stderr():
            text = _manga_ocr()(path)
    except ImportError:
        return "", [_note("ocr_not_installed", lang)]
    except Exception as exc:  # noqa: BLE001
        return "", [_note("ocr_failed", lang, error=exc)]
    finally:
        clear_busy()
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
    set_busy("translating")
    try:
        return _translate_impl(text, targets, cfg)
    finally:
        clear_busy()


def _translate_impl(text: str, targets: list[str], cfg: dict) -> tuple[dict, list[str]]:
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


def translate_cached(text: str, targets: list[str], cfg: dict,
                     reading: str) -> tuple[dict, list[str]]:
    """Like translate(), but reuse/record a local dictionary cache.

    Strings already translated are served from the dictionary instead of being
    re-requested (faster, and saves DeepL quota); only the missing target
    languages are fetched. Each lookup bumps the entry's count. DeepL output is
    always cacheable. Argos (offline) output is cached only when `cache_offline`
    is enabled — handy for building a practice deck without a DeepL key. With
    the dictionary off, falls straight through to translate().
    """
    backend = cfg.get("backend", "auto")
    key = cfg.get("deepl_api_key", "")
    lang = cfg.get("ui_language", "en")
    effective = ("deepl" if key else "argos") if backend == "auto" else backend
    cache_offline = bool(cfg.get("cache_offline", False))

    if not cfg.get("dictionary", True):
        return translate(text, targets, cfg)

    entry = dict_get(text)
    cached = dict(entry.get("translations", {})) if entry else {}
    missing = [t for t in targets if not cached.get(t)]
    notes: list[str] = []
    fresh: dict = {}          # newly fetched and cacheable
    uncacheable: dict = {}    # newly fetched but must NOT be stored
    if missing:
        set_busy("translating")  # real fetch ahead (cache hits stay instant)
        try:
            if effective == "deepl" and key:
                try:
                    fresh = translate_deepl(text, missing, key, lang)
                except TranslationError as exc:
                    notes.append(str(exc))
                    # Offline fallback for the missing langs; cache if opted in.
                    try:
                        argos = translate_argos(text, missing, lang)
                        notes.append(_note("fell_back_argos", lang))
                        (fresh if cache_offline else uncacheable).update(argos)
                    except TranslationError:
                        pass
            else:
                # Argos (offline) backend, or DeepL requested with no key set.
                try:
                    argos = translate_argos(text, missing, lang)
                    (fresh if cache_offline else uncacheable).update(argos)
                except TranslationError as exc:
                    notes.append(str(exc))
        finally:
            clear_busy()

    # Record/refresh the entry (count++ even on a pure cache hit) whenever we
    # have a cacheable result — a reused entry or freshly fetched cacheable
    # translations. Argos-only output with cache_offline off never lands here.
    to_store = {**cached, **fresh}
    if to_store:
        dict_record(text, reading, to_store)

    merged = {**to_store, **uncacheable}
    return {t: merged.get(t) for t in targets if merged.get(t)}, notes


# --------------------------------------------------------------------------- #
# High-level
# --------------------------------------------------------------------------- #
def process(text: str, languages: list[str], cfg: dict, do_translate: bool = True) -> Result:
    text = text.strip()
    reading, tokens = analyze(text)
    translations: dict = {}
    notes: list[str] = []
    if do_translate and text:
        translations, notes = translate_cached(text, languages, cfg, reading)
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


VOICEVOX_DEFAULT_HOST = "127.0.0.1:50021"
VOICEVOX_DEFAULT_SPEAKER = 3  # ずんだもん (Zundamon), normal style
_AUDIO_PLAYERS = ("pw-play", "paplay", "aplay", "ffplay")


def voicevox_synthesize(text: str, host: str, speaker: int,
                        speed: float = 1.0) -> bytes:
    """Return WAV audio for `text` from a local VOICEVOX engine.

    Two-step HTTP API: POST /audio_query builds the synthesis parameters, POST
    /synthesis renders them to a WAV. `speed` overrides the query's speedScale
    (1.0 = normal; VOICEVOX accepts ~0.5–2.0). Raises (URLError/timeout) if the
    engine isn't reachable — callers treat that as "no VOICEVOX".
    """
    base = f"http://{host}"
    params = urllib.parse.urlencode({"text": text, "speaker": speaker})
    req = urllib.request.Request(f"{base}/audio_query?{params}", method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        audio_query = resp.read()
    if speed and speed != 1.0:
        data = json.loads(audio_query)
        data["speedScale"] = speed
        audio_query = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/synthesis?speaker={speaker}", data=audio_query,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _play_wav(wav: bytes) -> None:
    """Play in-memory WAV bytes through the first available audio player."""
    player = next((p for p in _AUDIO_PLAYERS if shutil.which(p)), None)
    if not player or not wav:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav)
        path = f.name
    try:
        if player == "ffplay":
            argv = ["ffplay", "-autoexit", "-nodisp", "-loglevel", "quiet", path]
        elif player == "aplay":
            argv = ["aplay", "-q", path]
        else:  # pw-play / paplay
            argv = [player, path]
        subprocess.run(argv, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def speak(text: str, cfg: dict, block: bool = False) -> None:
    """Read Japanese text aloud (best-effort, non-blocking by default).

    Feed the hiragana reading for the clearest pronunciation. The engine is
    chosen by cfg["tts_engine"]:
      * "voicevox" — synthesize via the local VOICEVOX engine (natural neural)
      * "system"   — spd-say (speech-dispatcher) then espeak-ng (robotic)
      * "auto"     — VOICEVOX if its engine answers, otherwise the system voice
      * "command"  — run cfg["tts_command"] (kept for power users)
      * "off"      — silent
    A non-empty tts_command always wins, whatever the engine, for backwards
    compatibility. With block=True the call waits for playback to finish —
    needed by short-lived CLI runs (e.g. `add --speak`) that would otherwise
    exit and cut the audio off. Never raises: audio is a nicety on top.
    """
    text = (text or "").strip()
    if not text:
        return
    engine = cfg.get("tts_engine", "auto")
    if engine == "off":
        return

    speed = float(cfg.get("tts_speed", 1.0) or 1.0)

    def run():
        try:
            command = cfg.get("tts_command")
            if command or engine == "command":
                if not command:
                    return
                parts = shlex.split(command)
                argv = ([p.replace("{text}", text) for p in parts]
                        if any("{text}" in p for p in parts) else [*parts, text])
                subprocess.run(argv, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return

            if engine in ("voicevox", "auto"):
                try:
                    wav = voicevox_synthesize(
                        text, cfg.get("voicevox_host", VOICEVOX_DEFAULT_HOST),
                        cfg.get("voicevox_speaker", VOICEVOX_DEFAULT_SPEAKER),
                        speed)
                    _play_wav(wav)
                    return
                except Exception:  # engine unreachable / synthesis failed
                    if engine == "voicevox":
                        return  # explicit choice — don't surprise with a robot
                    # "auto" falls through to the system voice below.

            if shutil.which("spd-say"):
                # spd-say rate is -100..100 (0 = normal); map the speed factor.
                rate = max(-100, min(100, round((speed - 1.0) * 100)))
                subprocess.run(["spd-say", "-w", "-r", str(rate), "-l", "ja",
                                "--", text], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which("espeak-ng"):
                # espeak-ng default is ~175 wpm; scale it by the speed factor.
                wpm = max(80, min(450, round(175 * speed)))
                subprocess.run(["espeak-ng", "-s", str(wpm), "-v", "ja",
                                "--", text], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001 — audio must never break a lookup
            pass

    if block:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()


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
  zenbuji add <words…>        Translate & store words in the dictionary, no GUI
  zenbuji dict                Open the local dictionary (cached DeepL lookups)
  zenbuji learn               Practice cached words (spaced repetition quiz)
  zenbuji stats               Show learning statistics (--json for machines)
  zenbuji game                Game-helper overlay (shortcuts + live dictionary)
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


def _learn_command(extra: str) -> str:
    """Resolve a command line that re-runs zenbuji (prefer the installed
    launcher, fall back to the venv python + this script)."""
    launcher = shutil.which("zenbuji") or str(
        Path.home() / ".local" / "bin" / "zenbuji")
    if os.path.exists(launcher):
        return f"{launcher} {extra}"
    return f"{sys.executable} {Path(__file__).resolve()} {extra}"


def _write_learn_autostart(enable: bool) -> None:
    """Create/remove the autostart entry that opens the learning window on login."""
    try:
        if enable:
            AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART_PATH.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=zenbuji learn\n"
                f"Exec={_learn_command('learn --on-login')}\n"
                "X-GNOME-Autostart-enabled=true\n"
                "NoDisplay=true\n",
                encoding="utf-8",
            )
        else:
            AUTOSTART_PATH.unlink(missing_ok=True)
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
        image_path = args.ocr_image or capture_region()
        if not image_path:
            return 0  # user cancelled the region selection
        text, ocr_notes = ocr_image_to_text(image_path, cfg)
        for note in ocr_notes:
            print(note, file=sys.stderr)
        raw_items = text.splitlines()
    elif args.words:
        raw_items = list(args.words)
    elif args.selection:
        raw_items = read_selection().splitlines()
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
        result = process(text, languages, cfg, do_translate=True)
        stored = will_store and bool(result.translations)
        added += int(stored)
        results.append(result)
        if not args.quiet and not args.json:
            tr = "; ".join(f"{lang}: {result.translations[lang]}"
                           for lang in languages if result.translations.get(lang))
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
            entry = dict_get(r.text)
            if entry and entry.get("count") == 1:
                any_new = True
        if any_new:
            sel = cfg.get("voicevox_speaker", VOICEVOX_DEFAULT_SPEAKER)
            intro_cfg = {**cfg, "voicevox_speaker": _capture_voice(sel)}
            sequence.append((_CAPTURE_NEW_INTRO, intro_cfg))
        for text, voice_cfg in sequence:
            speak(text, voice_cfg, block=True)

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
    host = cfg.get("voicevox_host", VOICEVOX_DEFAULT_HOST)
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
        "config", "models", "usage", "ocr", "dict", "learn", "stats", "game",
        "add", "speak", "voices", "voicevox",
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
            text = (read_selection() if a.selection else sys.stdin.read()).strip()
        elif not text:
            text = read_selection().strip()
        if not text:
            print("No text to speak (give words, --selection, or pipe stdin).",
                  file=sys.stderr)
            return 2
        speak(text, cfg, block=True)
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
            clear_dict()
            print("dictionary cleared")
            return 0
        if a.json:
            print(json.dumps(load_dict(), ensure_ascii=False))
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
                seen = LAST_LEARN_PATH.read_text(encoding="utf-8").strip()
            except OSError:
                seen = ""
            if seen == today:
                return 0  # already practised today
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                LAST_LEARN_PATH.write_text(today, encoding="utf-8")
            except OSError:
                pass
        return launch_learning(cfg)

    if command == "stats":
        p = argparse.ArgumentParser(prog="zenbuji stats")
        p.add_argument("--json", action="store_true",
                       help="print the statistics as JSON")
        a = p.parse_args(rest)
        if a.json:
            print(json.dumps(srs_stats(), ensure_ascii=False))
            return 0
        return launch_stats(cfg)

    if command == "game":
        argparse.ArgumentParser(prog="zenbuji game").parse_args(rest)
        return launch_game(cfg)

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

    def speak_fn(t):
        speak(t, cfg)

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
        return deepl_usage(key) if key else None

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
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from zenbuji_dict import show_dictionary

    return show_dictionary(
        ui_language=cfg.get("ui_language", "en"),
        languages=cfg.get("languages", ["en", "de"]),
        load_fn=dict_with_srs,
        delete_fn=dict_delete,
        clear_fn=clear_dict,
        stats_fn=dict_stats,
        speak_fn=lambda t: speak(t, cfg),
        game_mode=True,
        shortcuts=shortcuts_info(cfg.get("ui_language", "en")),
        busy_path=BUSY_PATH,
        watch_path=DICT_PATH,   # live-refresh the overlay as words are added
    )


def launch_dictionary(cfg: dict) -> int:
    """Show the GTK dictionary window (browse/manage cached DeepL lookups)."""
    try:
        from zenbuji_dict import show_dictionary
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from zenbuji_dict import show_dictionary

    def refresh_fn(text, targets):
        """Force a fresh DeepL translation for `text` and re-cache it."""
        key = cfg.get("deepl_api_key", "")
        lang = cfg.get("ui_language", "en")
        if not key:
            return None
        reading, _tokens = analyze(text)
        fresh = translate_deepl(text, targets, key, lang)
        return dict_record(text, reading, fresh)

    return show_dictionary(
        ui_language=cfg.get("ui_language", "en"),
        languages=cfg.get("languages", ["en", "de"]),
        load_fn=dict_with_srs,
        delete_fn=dict_delete,
        clear_fn=clear_dict,
        stats_fn=dict_stats,
        refresh_fn=refresh_fn,
        update_fn=dict_update_translations,
        set_exclude_fn=dict_set_exclude,
        watch_path=DICT_PATH,
        quota_fn=lambda: (deepl_usage(cfg.get("deepl_api_key", ""))
                          if cfg.get("deepl_api_key") else None),
        speak_fn=lambda t: speak(t, cfg),
    )


def launch_stats(cfg: dict) -> int:
    """Show the SRS statistics window."""
    try:
        from zenbuji_stats import show_statistics
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from zenbuji_stats import show_statistics

    return show_statistics(
        ui_language=cfg.get("ui_language", "en"),
        languages=cfg.get("languages", ["en", "de"]),
        stats_fn=srs_stats,
    )


def launch_learning(cfg: dict) -> int:
    """Show the SRS learning/quiz window over the cached dictionary."""
    try:
        from zenbuji_learn import show_learning
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from zenbuji_learn import show_learning

    show_tr = bool(cfg.get("learn_show_translation", True))
    count = int(cfg.get("learn_count", 10) or 10)
    cards = srs_select(count)

    def grade_fn(card, reading_in, translation_in):
        return grade_answer(card, reading_in, translation_in,
                            test_translation=not show_tr)

    def review_fn(text, correct):
        st = srs_review(text, correct)
        return {"status": srs_status(st), "interval": st.get("interval", 0),
                "due": st.get("due")}

    return show_learning(
        cards=cards,
        show_translation=show_tr,
        languages=cfg.get("languages", ["en", "de"]),
        ui_language=cfg.get("ui_language", "en"),
        grade_fn=grade_fn,
        review_fn=review_fn,
        speak_fn=lambda t: speak(t, cfg),
        auto_speak=bool(cfg.get("tts_on_lookup", False)),
        greeting=bool(cfg.get("learn_greeting", True)),
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
