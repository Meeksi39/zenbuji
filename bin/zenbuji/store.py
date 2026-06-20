"""JSON state store: history, the dictionary cache, the daily activity log, and
the transient background-busy marker.

All file locations come from :mod:`zenbuji.paths`, read **module-qualified**
(``paths.DICT_PATH``) so the test suite's path redirection is honoured.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import paths


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def load_history() -> list:
    try:
        if paths.HISTORY_PATH.exists():
            data = json.loads(paths.HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, ValueError):
        pass
    return []


def clear_history() -> None:
    try:
        paths.HISTORY_PATH.unlink()
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
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        paths.HISTORY_PATH.write_text(
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
        if paths.DICT_PATH.exists():
            data = json.loads(paths.DICT_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def save_dict(data: dict) -> None:
    try:
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        paths.DICT_PATH.write_text(
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
        paths.DICT_PATH.unlink()
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


# --- Daily activity log (powers the statistics streak + recent graph) ------ #
def load_activity() -> dict:
    """Per-day review tallies: {"YYYY-MM-DD": {"reviews": int, "correct": int}}."""
    try:
        if paths.ACTIVITY_PATH.exists():
            data = json.loads(paths.ACTIVITY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def save_activity(data: dict) -> None:
    try:
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        paths.ACTIVITY_PATH.write_text(
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
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        paths.BUSY_PATH.write_text(
            json.dumps({"stage": stage,
                        "ts": datetime.now().isoformat(timespec="seconds")}),
            encoding="utf-8")
    except OSError:
        pass


def clear_busy() -> None:
    try:
        paths.BUSY_PATH.unlink()
    except (FileNotFoundError, OSError):
        pass


def read_busy(max_age: float = 120.0) -> dict | None:
    """Current busy state, or None when idle/stale (a crashed run can't stick)."""
    try:
        data = json.loads(paths.BUSY_PATH.read_text(encoding="utf-8"))
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
