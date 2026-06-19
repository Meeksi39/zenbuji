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
