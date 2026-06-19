"""Local dictionary cache: record / merge / stats / delete."""

import zenbuji


def test_record_creates_and_counts(store):
    e = zenbuji.dict_record("水", "みず", {"en": "water", "de": "Wasser"})
    assert e["count"] == 1 and e["reading"] == "みず"
    assert e["translations"]["en"] == "water"

    e2 = zenbuji.dict_record("水", "みず", {"en": "water"})
    assert e2["count"] == 2
    assert e2["first_seen"] == e["first_seen"]   # first_seen is stable


def test_record_merges_target_languages(store):
    zenbuji.dict_record("水", "みず", {"en": "water"})
    e = zenbuji.dict_record("水", "みず", {"de": "Wasser"})
    assert e["translations"] == {"en": "water", "de": "Wasser"}


def test_record_skips_empty_values(store):
    e = zenbuji.dict_record("水", "みず", {"en": "water", "de": ""})
    assert "de" not in e["translations"]


def test_stats_totals(store):
    zenbuji.dict_record("a", "あ", {"en": "a"})
    zenbuji.dict_record("a", "あ", {"en": "a"})   # repeat lookup
    zenbuji.dict_record("b", "べ", {"en": "b"})
    st = zenbuji.dict_stats()
    assert st["entries"] == 2
    assert st["lookups"] == 3
    assert st["saved"] == 1                       # lookups - entries


def test_delete_and_clear(store):
    zenbuji.dict_record("a", "あ", {"en": "a"})
    zenbuji.dict_delete("a")
    assert zenbuji.dict_get("a") is None

    zenbuji.dict_record("b", "べ", {"en": "b"})
    zenbuji.clear_dict()
    assert zenbuji.load_dict() == {}
