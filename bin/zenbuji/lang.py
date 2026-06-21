"""Furigana: tokenise Japanese text and produce hiragana readings (fugashi)."""

from __future__ import annotations

import functools
from dataclasses import asdict, dataclass, field

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


@functools.lru_cache(maxsize=2048)
def _tokenize(text: str) -> tuple[str, tuple[tuple[str, str, bool], ...]]:
    """MeCab tokenisation, memoised. Returns an immutable (reading, tokens)
    tuple — the expensive part — so `analyze` can hand back fresh, mutable Token
    objects without ever sharing cached state. Pure function of `text`."""
    tagger = _tagger()
    parts: list[tuple[str, str, bool]] = []
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
        reading = kata_to_hira(kana) if kana else surface
        reading_parts.append(reading)
        parts.append((surface, reading, has_kanji(surface)))
    return "".join(reading_parts), tuple(parts)


def analyze(text: str) -> tuple[str, list[Token]]:
    """Return (full hiragana reading, tokens) for the given text."""
    reading, parts = _tokenize(text.strip())
    tokens = [Token(surface=s, reading=r, has_kanji=k) for s, r, k in parts]
    return reading, tokens
