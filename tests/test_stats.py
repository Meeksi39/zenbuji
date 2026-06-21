"""srs_stats(): aggregation over the dictionary + SRS schedule + activity log."""

import datetime as dt
import json

import zenbuji


def _seed(store, dict_data, srs_data, activity_data=None):
    (store / "dictionary.json").write_text(json.dumps(dict_data, ensure_ascii=False))
    (store / "srs.json").write_text(json.dumps(srs_data, ensure_ascii=False))
    if activity_data is not None:
        (store / "activity.json").write_text(json.dumps(activity_data, ensure_ascii=False))


def test_empty(store):
    s = zenbuji.srs_stats()
    assert s["total"] == 0
    assert s["accuracy"] is None
    assert s["streak"] == 0
    assert len(s["recent"]) == 14


def test_aggregation(store):
    today = dt.datetime.now().date()
    past = (today - dt.timedelta(days=1)).isoformat() + "T10:00:00"
    future = (today + dt.timedelta(days=5)).isoformat() + "T10:00:00"

    dict_data = {
        "a": {"text": "a", "reading": "あ", "translations": {"en": "a"}},
        "b": {"text": "b", "reading": "べ", "translations": {"en": "b"}},
        "c": {"text": "c", "reading": "", "translations": {"en": "c"}},  # ineligible: no reading
    }
    srs_data = {
        "a": {"interval": 0, "reps": 0, "due": past, "last_reviewed": past,
              "correct": 2, "wrong": 3, "lapses": 3, "ease": 1.9},
        "b": {"interval": 15, "reps": 3, "due": future, "last_reviewed": past,
              "correct": 5, "wrong": 1, "lapses": 1, "ease": 2.5},
    }
    _seed(store, dict_data, srs_data)

    s = zenbuji.srs_stats()
    assert s["total"] == 2                       # a, b eligible; c excluded
    assert s["reviewed"] == 2
    assert s["by_level"] == {"new": 0, "learning": 1, "young": 1, "mature": 0}
    assert s["due_today"] == 1                   # a is due (past), b is future
    assert s["due_now"] == 1                     # a has interval 0
    assert s["reviews_total"] == 11              # (2+3) + (5+1)
    assert s["correct_total"] == 7 and s["wrong_total"] == 4
    assert s["accuracy"] == 7 / 11
    assert s["lapses_total"] == 4
    assert s["hardest"][0]["text"] == "a"        # most lapses/misses first
    assert s["hardest"][0]["reading"] == "あ"


def test_excluded_words_drop_from_stats(store):
    dict_data = {
        "a": {"text": "a", "reading": "あ", "translations": {"en": "a"}},
        "b": {"text": "b", "reading": "べ", "translations": {"en": "b"},
              "exclude": True},
    }
    srs_data = {
        "a": {"interval": 1, "last_reviewed": "2026-01-01T00:00:00",
              "correct": 1, "wrong": 0, "lapses": 0},
        "b": {"interval": 1, "last_reviewed": "2026-01-01T00:00:00",
              "correct": 0, "wrong": 5, "lapses": 5},
    }
    _seed(store, dict_data, srs_data)
    s = zenbuji.srs_stats()
    assert s["total"] == 1                       # only a counts
    assert s["reviews_total"] == 1               # b's reviews excluded
    assert s["wrong_total"] == 0
    assert all(h["text"] != "b" for h in s["hardest"])  # b not in hardest


def test_orphaned_srs_card_ignored_in_stats(store):
    # A card whose word is no longer in the dictionary must not show up in the
    # totals or the "hardest" list (defends the delete-leaves-orphan bug).
    dict_data = {"a": {"text": "a", "reading": "あ", "translations": {"en": "a"}}}
    srs_data = {
        "a": {"interval": 1, "last_reviewed": "2026-01-01T00:00:00",
              "correct": 1, "wrong": 0, "lapses": 0},
        "雪": {"interval": 1, "last_reviewed": "2026-01-01T00:00:00",
               "correct": 0, "wrong": 9, "lapses": 9},   # orphan: not in dict
    }
    _seed(store, dict_data, srs_data)
    s = zenbuji.srs_stats()
    assert s["total"] == 1
    assert s["reviews_total"] == 1 and s["wrong_total"] == 0
    assert all(h["text"] != "雪" for h in s["hardest"])


def test_answer_time_average_slowest_and_total(store):
    today = dt.datetime.now().date().isoformat()
    dict_data = {
        "fast": {"text": "fast", "reading": "は", "translations": {"en": "f"}},
        "slow": {"text": "slow", "reading": "の", "translations": {"en": "s"}},
    }
    srs_data = {
        "fast": {"last_reviewed": "2026-01-01T00:00:00", "correct": 2, "wrong": 0,
                 "time_ms": 4000, "time_n": 2},      # avg 2000
        "slow": {"last_reviewed": "2026-01-01T00:00:00", "correct": 1, "wrong": 0,
                 "time_ms": 8000, "time_n": 1},      # avg 8000
    }
    activity_data = {today: {"reviews": 3, "correct": 3, "time_ms": 30000},
                     "2026-01-01": {"reviews": 0, "correct": 0, "time_ms": 5000}}
    _seed(store, dict_data, srs_data, activity_data)
    s = zenbuji.srs_stats()
    assert s["avg_answer_ms"] == 4000               # (4000+8000)/(2+1)
    assert s["slowest"][0]["text"] == "slow"        # highest per-card avg first
    assert s["total_study_ms"] == 35000             # 30000 + 5000
    assert s["today_study_ms"] == 30000


def test_streak_and_today_from_activity(store):
    today = dt.datetime.now().date()
    activity = {(today - dt.timedelta(days=i)).isoformat(): {"reviews": 3, "correct": 2}
                for i in range(2)}
    _seed(store, {}, {}, activity)
    s = zenbuji.srs_stats()
    assert s["streak"] == 2
    assert s["today_reviews"] == 3 and s["today_correct"] == 2
    assert s["recent"][-1]["reviews"] == 3
