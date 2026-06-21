"""Furigana analysis — only runs where the offline MeCab stack is installed
(skipped in the lightweight CI environment)."""

import pytest

import zenbuji


def test_analyze_produces_reading():
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    reading, tokens = zenbuji.analyze("日本語")
    assert isinstance(reading, str) and reading
    assert isinstance(tokens, list) and tokens


def test_kata_to_hira():
    assert zenbuji.kata_to_hira("ニホンゴ") == "にほんご"


def test_analyze_memoizes_tokenization(monkeypatch):
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    real = zenbuji.lang._tagger()      # build the real tagger once
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return real

    monkeypatch.setattr(zenbuji.lang, "_tagger", counting)
    zenbuji.lang._tokenize.cache_clear()

    r1, t1 = zenbuji.analyze("日本語")
    r2, t2 = zenbuji.analyze("日本語")
    assert calls["n"] == 1             # tokenised once, then served from the memo
    assert r1 == r2
    assert [(x.surface, x.reading) for x in t1] == \
           [(x.surface, x.reading) for x in t2]


def test_analyze_returns_fresh_tokens():
    # Each call rebuilds Token objects, so a caller mutating one result can never
    # corrupt the cached tokenisation shared with another caller.
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    _, t1 = zenbuji.analyze("日本語")
    _, t2 = zenbuji.analyze("日本語")
    assert t1 is not t2 and t1[0] is not t2[0]
    t1[0].surface = "X"
    assert t2[0].surface != "X"
