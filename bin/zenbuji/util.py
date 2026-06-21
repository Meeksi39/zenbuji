"""Shared helpers: stderr quieting, localized status notes, language names."""

from __future__ import annotations

import contextlib
import os

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
    "normalized": {
        "en": "Normalized {src} → {dst} (dictionary form).",
        "ja": "{src} を {dst} に正規化しました（辞書形）。",
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
