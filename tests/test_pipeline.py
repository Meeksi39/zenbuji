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


# --- optional normalize-to-dictionary-form mode (dict_form mocked, no MeCab) -- #
def _deepl_recording(monkeypatch, sink):
    monkeypatch.setattr(zenbuji.translation, "translate_deepl",
                        lambda text, tg, k, l: (sink.append(text),
                                                {t: "X" for t in tg})[1])
    monkeypatch.setattr(zenbuji.lang, "analyze", lambda t: (t, []))


def test_process_normalizes_when_enabled(store, monkeypatch):
    seen = []
    _deepl_recording(monkeypatch, seen)
    monkeypatch.setattr(zenbuji.lang, "dict_form",
                        lambda t: "食べる" if t == "食べた" else None)
    cfg = {"deepl_api_key": "k", "backend": "deepl", "dictionary": True,
           "history": False, "normalize": True, "ui_language": "en"}
    r = zenbuji.pipeline.process("食べた", ["en", "de"], cfg)
    assert r.text == "食べる"                         # folded to the dictionary form
    assert seen == ["食べる"]                          # DeepL got the dict form
    assert zenbuji.dict_get("食べる") is not None       # keyed on the dict form
    assert zenbuji.dict_get("食べた") is None
    assert any("食べる" in n for n in r.notes)          # the normalized note shows


def test_process_does_not_normalize_by_default(store, monkeypatch):
    _deepl_recording(monkeypatch, [])
    monkeypatch.setattr(zenbuji.lang, "dict_form", lambda t: "食べる")
    cfg = {"deepl_api_key": "k", "backend": "deepl", "dictionary": True,
           "history": False}                          # normalize absent -> off
    r = zenbuji.pipeline.process("食べた", ["en", "de"], cfg)
    assert r.text == "食べた"


def test_process_furigana_only_is_never_normalized(monkeypatch):
    called = []
    monkeypatch.setattr(zenbuji.lang, "analyze", lambda t: (t, []))
    monkeypatch.setattr(zenbuji.lang, "dict_form",
                        lambda t: (called.append(t), "食べる")[1])
    r = zenbuji.pipeline.process("食べた", ["en", "de"], {"normalize": True},
                                 do_translate=False)
    assert r.text == "食べた" and called == []         # gated on do_translate
