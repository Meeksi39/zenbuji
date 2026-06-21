"""Answer grading for the practice quiz."""

from __future__ import annotations

import difflib
import re

from .lang import kata_to_hira

_PUNCT_RE = re.compile(r"[.,!?;:\"'()\[\]{}。、！？・…]+")


def _norm_reading(s: str) -> str:
    s = kata_to_hira((s or "").strip())
    for ch in (" ", "　", "・"):
        s = s.replace(ch, "")
    return s


def reading_matches(typed: str, correct: str) -> bool:
    """True if a typed reading matches the canonical one (kana-normalised).

    Same comparison the quiz verdict uses, so the practice drill and the grade
    agree exactly on what counts as the right reading."""
    return _norm_reading(typed) == _norm_reading(correct)


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
