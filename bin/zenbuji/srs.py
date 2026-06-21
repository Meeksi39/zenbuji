"""Spaced repetition (SRS) — a learning schedule layered over the dictionary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import paths, store

SRS_DEFAULT_EASE = 2.5


# In-memory cache of the parsed SRS state, keyed on (path, st_mtime_ns) — same
# scheme as the dictionary cache in store.py (see the note there). A practice
# session and srs_select/srs_stats re-read this growing file repeatedly; this
# serves the parsed data until the file's mtime changes (our own save, or
# another process) or the path is redirected (tests).
_SRS_CACHE = None


def _clear_caches() -> None:
    """Drop the in-memory SRS cache (used by tests to stay hermetic)."""
    global _SRS_CACHE
    _SRS_CACHE = None


def load_srs() -> dict:
    global _SRS_CACHE
    path = paths.SRS_PATH
    key = str(path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = None
    if (mtime is not None and _SRS_CACHE is not None
            and _SRS_CACHE[0] == key and _SRS_CACHE[1] == mtime):
        return _SRS_CACHE[2]
    try:
        if mtime is not None:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _SRS_CACHE = (key, mtime, data)
                return data
    except (OSError, ValueError):
        pass
    return {}


def save_srs(data: dict) -> None:
    global _SRS_CACHE
    try:
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        paths.SRS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            _SRS_CACHE = (str(paths.SRS_PATH),
                          paths.SRS_PATH.stat().st_mtime_ns, data)
        except OSError:
            _SRS_CACHE = None
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
    store.log_activity(correct)
    return s


def srs_select(limit: int = 10) -> list:
    """Pick cards to review from the dictionary, most-due first.

    Never-reviewed entries sort first (treated as maximally due), then by due
    date ascending. Only entries with a reading and at least one translation
    qualify.
    """
    d = store.load_dict()
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
    data = store.load_dict()
    for text, entry in data.items():
        entry["srs"] = srs_summary(text, srs)
    return data


def srs_stats() -> dict:
    """Aggregate the whole learning state for the statistics window."""
    d = store.load_dict()
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
        due = store._due_date((st or {}).get("due"))
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

    activity = store.load_activity()
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
        "streak": store.activity_streak(activity),
        "today_reviews": int(today_day.get("reviews", 0)),
        "today_correct": int(today_day.get("correct", 0)),
        "recent": store.activity_recent(14, activity),
    }
