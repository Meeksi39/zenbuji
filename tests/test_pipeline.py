"""Capture cleaning: edge punctuation/symbols are trimmed before the text is
analysed, translated, or stored — internal punctuation and word characters
(incl. ー / 々) are kept."""

import pytest

import zenbuji


@pytest.mark.parametrize("raw, expected", [
    ("「水」。", "水"),
    ("  ?水?  ", "水"),
    ("—そうだ—", "そうだ"),
    ("水^", "水"),
    ("20°", "20"),
    ("（水）", "水"),
    ("〜水〜", "水"),
    ("…水…", "水"),
])
def test_clean_capture_trims_edges(raw, expected):
    assert zenbuji.clean_capture(raw) == expected


@pytest.mark.parametrize("text", [
    "コーヒー",      # trailing long-vowel mark ー (Lm) is part of the word
    "水、お茶",       # internal Japanese comma is part of the phrase
    "人々",          # repetition mark 々 (Lm)
    "日本語",         # plain text, no-op
    "Aさん",          # leading latin letter is kept (not punctuation/symbol)
])
def test_clean_capture_keeps_content(text):
    assert zenbuji.clean_capture(text) == text


def test_clean_capture_all_punctuation_is_empty():
    assert zenbuji.clean_capture("？？！") == ""
    assert zenbuji.clean_capture("   ") == ""


def test_process_cleans_before_translate_and_store(store, monkeypatch):
    # DeepL is mocked; two differently-noisy captures of the same word must clean
    # to one key, so DeepL is hit once and the second is served from the cache.
    calls = []

    def fake_deepl(text, targets, key, lang):
        calls.append(text)
        return {t: "X" for t in targets}

    monkeypatch.setattr(zenbuji.translation, "translate_deepl", fake_deepl)
    monkeypatch.setattr(zenbuji.lang, "analyze", lambda t: (t, []))  # skip MeCab

    cfg = {"deepl_api_key": "k", "backend": "deepl", "dictionary": True,
           "history": False}
    r1 = zenbuji.pipeline.process("「水」。", ["en", "de"], cfg)
    r2 = zenbuji.pipeline.process("  ?水?  ", ["en", "de"], cfg)   # same word, new noise

    assert r1.text == "水" and r2.text == "水"     # cleaned on the Result
    assert calls == ["水"]                          # DeepL saw 水 once; 2nd cached
    assert zenbuji.dict_get("水")["translations"]["en"] == "X"  # keyed on clean form
