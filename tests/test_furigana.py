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


@pytest.mark.parametrize("inflected, base", [
    ("食べた", "食べる"),
    ("高かった", "高い"),
    ("来た", "来る"),
    ("きれいな", "きれい"),     # orthBase keeps kana (not the 奇麗 lemma)
    ("静かだった", "静か"),
])
def test_dict_form_normalizes_lone_inflected_word(inflected, base):
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    assert zenbuji.lang.dict_form(inflected) == base


@pytest.mark.parametrize("text", [
    "食べる",      # already the dictionary form → no-op
    "日本語",      # noun, doesn't inflect
    "走って",      # te-form (conjunctive 助詞) → leave it
    "読んでいる",   # progressive (two verbs) → leave it
    "勉強します",   # noun + する → leave it
    "本を読む",    # phrase with a case particle → leave it
    "",            # blank
])
def test_dict_form_leaves_non_lone_words(text):
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    assert zenbuji.lang.dict_form(text) is None


def test_content_words_keeps_noun_and_verb():
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    words = zenbuji.lang.content_words("猫が走る")
    lemmas = [w[0] for w in words]
    assert "猫" in lemmas and "走る" in lemmas
    assert "が" not in lemmas                 # particle dropped
    assert all(w[1] for w in words)           # every word has a reading


def test_content_words_lemmatizes_inflected():
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    lemmas = [w[0] for w in zenbuji.lang.content_words("ご飯を食べた")]
    assert "食べる" in lemmas                 # 食べた -> 食べる
    assert "食べた" not in lemmas


def test_content_words_drops_particles_and_punctuation():
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    lemmas = [w[0] for w in zenbuji.lang.content_words("本を、読む。")]
    assert "読む" in lemmas
    for junk in ("を", "、", "。"):
        assert junk not in lemmas


def test_content_words_dedups():
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    lemmas = [w[0] for w in zenbuji.lang.content_words("猫と猫と猫")]
    assert lemmas.count("猫") == 1


def test_content_words_drops_romaji_and_digits():
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    lemmas = [w[0] for w in zenbuji.lang.content_words("猫のtestと2024")]
    assert "猫" in lemmas
    assert "test" not in lemmas              # pure romaji dropped
    assert all(not lem.isascii() for lem in lemmas)   # nothing latin/numeric slips through
