"""High-level pipeline: analyse + translate, selection/stdin input, rendering."""

from __future__ import annotations

import shutil
import subprocess
import sys
import unicodedata

from . import lang, store, translation
from .lang import Result
from .util import LANG_NAMES


def clean_capture(text: str) -> str:
    """Trim capture noise from the edges of selected/OCR'd/typed text.

    Removes leading and trailing whitespace plus any Unicode punctuation (P*) or
    symbol (S*) characters, so quotes/brackets/dashes/dots/the degree sign/etc.
    picked up around a word don't reach DeepL or become a separate cache key
    (「水」。 and 水 should be one entry). Category-based, so it covers
    -?,.^° 。、！？「」（）・… and anything else without a hand-kept list.
    Punctuation *inside* a phrase is kept (水、お茶 stays whole), and the
    long-vowel mark ー and repetition mark 々 survive — they're letters (Lm),
    not punctuation. Letters and digits are never stripped.
    """
    text = text.strip()

    def strippable(ch: str) -> bool:
        return ch.isspace() or unicodedata.category(ch)[0] in ("P", "S")

    start, end = 0, len(text)
    while start < end and strippable(text[start]):
        start += 1
    while end > start and strippable(text[end - 1]):
        end -= 1
    return text[start:end]


def process(text: str, languages: list[str], cfg: dict, do_translate: bool = True) -> Result:
    text = clean_capture(text)
    reading, tokens = lang.analyze(text)
    translations: dict = {}
    notes: list[str] = []
    if do_translate and text:
        translations, notes = translation.translate_cached(text, languages, cfg, reading)
    result = Result(
        text=text,
        reading=reading,
        tokens=tokens,
        translations=translations,
        notes=notes,
    )
    if cfg.get("history", True) and translations:
        store.append_history(result, limit=int(cfg.get("history_size", 20)))
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
    for lang_code in languages:
        val = result.translations.get(lang_code)
        label = LANG_NAMES.get(lang_code, lang_code.upper())
        lines.append(f"{label}: {val if val else '—'}")
    for note in result.notes:
        lines.append(f"(note: {note})")
    return "\n".join(lines)
