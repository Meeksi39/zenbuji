"""Answer grading: reading is exact (kana-normalised), translation is fuzzy."""

import zenbuji


def card(reading="にほんご", translations=None):
    return {"reading": reading,
            "translations": translations or {"en": "Japanese", "de": "Japanisch"}}


def test_reading_exact_match():
    assert zenbuji.grade_answer(card(), "にほんご", "")["reading_ok"] is True


def test_reading_katakana_is_normalised():
    # Katakana input should match a hiragana reading.
    assert zenbuji.grade_answer(card(), "ニホンゴ", "")["reading_ok"] is True


def test_reading_spaces_ignored():
    assert zenbuji.grade_answer(card(), " に ほ ん ご ", "")["reading_ok"] is True


def test_reading_wrong():
    assert zenbuji.grade_answer(card(), "ちがう", "")["reading_ok"] is False


def test_translation_exact():
    assert zenbuji.grade_answer(card(), "にほんご", "Japanese")["translation_ok"] is True


def test_translation_fuzzy_typo():
    # Close enough (SequenceMatcher ratio >= 0.8).
    assert zenbuji.grade_answer(card(), "x", "japanes")["translation_ok"] is True


def test_translation_matches_either_language():
    assert zenbuji.grade_answer(card(), "x", "Japanisch")["translation_ok"] is True


def test_translation_blank_is_false():
    assert zenbuji.grade_answer(card(), "x", "")["translation_ok"] is False


def test_translation_skipped_when_disabled():
    res = zenbuji.grade_answer(card(), "にほんご", "anything", test_translation=False)
    assert res["translation_ok"] is None


def test_returns_correct_answers():
    res = zenbuji.grade_answer(card(), "", "")
    assert res["correct_reading"] == "にほんご"
    assert res["correct_translations"]["de"] == "Japanisch"


# --- reading_matches: the practice-drill retype check, same normalisation ---

def test_reading_matches_exact():
    assert zenbuji.reading_matches("にほんご", "にほんご") is True


def test_reading_matches_katakana():
    assert zenbuji.reading_matches("ニホンゴ", "にほんご") is True


def test_reading_matches_spaces_ignored():
    assert zenbuji.reading_matches("に ほ ん ご", "にほんご") is True


def test_reading_matches_wrong():
    assert zenbuji.reading_matches("ちがう", "にほんご") is False


def test_reading_matches_blank():
    assert zenbuji.reading_matches("", "にほんご") is False
