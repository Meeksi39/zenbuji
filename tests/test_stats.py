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


def test_streak_and_today_from_activity(store):
    today = dt.datetime.now().date()
    activity = {(today - dt.timedelta(days=i)).isoformat(): {"reviews": 3, "correct": 2}
                for i in range(2)}
    _seed(store, {}, {}, activity)
    s = zenbuji.srs_stats()
    assert s["streak"] == 2
    assert s["today_reviews"] == 3 and s["today_correct"] == 2
    assert s["recent"][-1]["reviews"] == 3
