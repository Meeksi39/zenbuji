"""Local dictionary cache: record / merge / stats / delete."""

import json
import os

import zenbuji


def _count_parses(monkeypatch):
    """Count how many times the dictionary file is parsed from disk."""
    calls = {"n": 0}
    real = json.loads

    def counting(s, *a, **k):
        calls["n"] += 1
        return real(s, *a, **k)

    monkeypatch.setattr(zenbuji.store.json, "loads", counting)
    return calls


def test_load_dict_caches_in_memory(store, monkeypatch):
    zenbuji.dict_record("水", "みず", {"en": "water"})   # writes + warms cache
    parses = _count_parses(monkeypatch)
    assert zenbuji.dict_get("水") is not None
    assert zenbuji.dict_get("水") is not None
    assert parses["n"] == 0      # both served from the in-memory cache


def test_load_dict_reparses_once_when_cold(store, monkeypatch):
    zenbuji.dict_record("水", "みず", {"en": "water"})
    zenbuji.store._clear_caches()                  # simulate a fresh process
    parses = _count_parses(monkeypatch)
    zenbuji.dict_get("水")                          # cold -> one parse
    zenbuji.dict_get("水")                          # warm -> cached
    assert parses["n"] == 1


def test_load_dict_sees_its_own_writes(store):
    zenbuji.dict_record("a", "あ", {"en": "a"})
    assert zenbuji.dict_get("a") is not None        # save refreshed the cache
    zenbuji.dict_record("b", "べ", {"en": "b"})
    assert zenbuji.dict_get("b") is not None        # not stuck on the old snapshot


def test_load_dict_reloads_on_external_write(store):
    zenbuji.dict_record("水", "みず", {"en": "water"})
    assert zenbuji.dict_get("水") is not None        # warm the cache
    # Another process rewrites the file; force a strictly newer mtime so the
    # cache key (path, st_mtime_ns) misses and we reload.
    p = zenbuji.paths.DICT_PATH
    p.write_text(json.dumps(
        {"火": {"text": "火", "reading": "ひ", "translations": {"en": "fire"}}}),
        encoding="utf-8")
    st = p.stat()
    os.utime(p, ns=(st.st_mtime_ns + 1_000_000_000, st.st_mtime_ns + 1_000_000_000))
    assert zenbuji.dict_get("火") is not None
    assert zenbuji.dict_get("水") is None


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


# --- dict_set: manual create / edit (no lookup, no count bump) -------------- #
def test_dict_set_creates_with_zero_count(store):
    e = zenbuji.dict_set("食べる", "たべる", {"en": "to eat", "de": "essen"})
    assert e["count"] == 0                       # no lookup happened
    assert e["reading"] == "たべる"
    assert e["translations"] == {"en": "to eat", "de": "essen"}
    assert e["first_seen"] and e["last_seen"]    # stamped so it sorts/export


def test_dict_set_blank_text_returns_none(store):
    assert zenbuji.dict_set("  ", "x", {"en": "y"}) is None


def test_dict_set_edits_reading_and_merges(store):
    zenbuji.dict_set("水", "みづ", {"en": "watr"})        # typo'd reading + meaning
    before = zenbuji.dict_get("水")
    e = zenbuji.dict_set("水", "みず", {"en": "water", "de": "Wasser"})
    assert e["reading"] == "みず"                          # reading corrected
    assert e["translations"] == {"en": "water", "de": "Wasser"}   # merged
    assert e["count"] == 0                                 # still no lookup
    assert e["first_seen"] == before["first_seen"]         # timestamps stable


def test_dict_set_blank_value_drops_language(store):
    zenbuji.dict_set("水", "みず", {"en": "water", "de": "Wasser"})
    e = zenbuji.dict_set("水", "みず", {"de": "   "})
    assert "de" not in e["translations"] and e["translations"]["en"] == "water"


def test_dict_set_then_record_bumps_from_zero(store):
    # A manual entry that's later looked up starts counting from its real first
    # lookup, not pre-inflated.
    zenbuji.dict_set("水", "みず", {"en": "water"})
    e = zenbuji.dict_record("水", "みず", {"en": "water"})
    assert e["count"] == 1


def test_dict_set_monotonic_last_seen(store):
    for w in ["a", "b", "c"]:
        zenbuji.dict_set(w, w, {"en": w})
    stamps = [zenbuji.dict_get(w)["last_seen"] for w in ["a", "b", "c"]]
    assert stamps == sorted(stamps) and len(set(stamps)) == 3


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
