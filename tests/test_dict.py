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


def test_update_translations_replaces_value(store):
    zenbuji.dict_record("水", "みず", {"en": "watr", "de": "Wasser"})
    e = zenbuji.dict_update_translations("水", {"en": "water"})
    assert e["translations"] == {"en": "water", "de": "Wasser"}
    assert e["reading"] == "みず" and e["count"] == 1   # untouched


def test_update_translations_blank_drops_language(store):
    zenbuji.dict_record("水", "みず", {"en": "water", "de": "Wasser"})
    e = zenbuji.dict_update_translations("水", {"de": "  "})
    assert "de" not in e["translations"] and e["translations"]["en"] == "water"


def test_update_translations_unknown_entry_returns_none(store):
    assert zenbuji.dict_update_translations("nope", {"en": "x"}) is None


def test_record_last_seen_is_strictly_monotonic(store):
    # Several records in the same clock second must still get distinct, increasing
    # last_seen, so the most recent always sorts to the top (regression).
    for w in ["a", "b", "c", "d", "e"]:
        zenbuji.dict_record(w, w, {"en": w})
    data = zenbuji.load_dict()
    stamps = [data[w]["last_seen"] for w in ["a", "b", "c", "d", "e"]]
    assert stamps == sorted(stamps)          # increasing in record order
    assert len(set(stamps)) == 5             # all distinct (no ties)


def test_latest_recorded_sorts_to_top(store):
    zenbuji.dict_record("a", "あ", {"en": "a"})
    zenbuji.dict_record("b", "べ", {"en": "b"})
    zenbuji.dict_record("a", "あ", {"en": "a"})   # re-add the known word -> newest
    data = zenbuji.load_dict()
    order = sorted(data.values(), key=lambda e: e["last_seen"], reverse=True)
    assert order[0]["text"] == "a"            # latest on top, even though known


def test_set_exclude_toggles_flag(store):
    zenbuji.dict_record("水", "みず", {"en": "water"})
    zenbuji.dict_set_exclude("水", True)
    assert zenbuji.dict_get("水")["exclude"] is True
    zenbuji.dict_set_exclude("水", False)
    assert "exclude" not in zenbuji.dict_get("水")
