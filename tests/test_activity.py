"""Daily activity log: streak + recent-activity helpers."""

import datetime as dt

import zenbuji


def _today():
    return dt.datetime.now().date()


def test_log_increments_today(store):
    zenbuji.log_activity(True)
    zenbuji.log_activity(False)
    day = zenbuji.load_activity()[_today().isoformat()]
    assert day["reviews"] == 2 and day["correct"] == 1


def test_streak_today_only(store):
    zenbuji.log_activity(True)
    assert zenbuji.activity_streak() == 1


def test_streak_counts_consecutive_days(store):
    today = _today()
    data = {(today - dt.timedelta(days=i)).isoformat(): {"reviews": 2, "correct": 1}
            for i in range(3)}
    zenbuji.save_activity(data)
    assert zenbuji.activity_streak() == 3


def test_streak_breaks_on_gap(store):
    today = _today()
    data = {
        today.isoformat(): {"reviews": 1, "correct": 1},
        (today - dt.timedelta(days=2)).isoformat(): {"reviews": 1, "correct": 1},
    }
    zenbuji.save_activity(data)
    assert zenbuji.activity_streak() == 1


def test_streak_starts_from_yesterday_when_today_empty(store):
    today = _today()
    data = {(today - dt.timedelta(days=1)).isoformat(): {"reviews": 2, "correct": 2},
            (today - dt.timedelta(days=2)).isoformat(): {"reviews": 1, "correct": 1}}
    zenbuji.save_activity(data)
    assert zenbuji.activity_streak() == 2


def test_recent_length_order_and_zero_fill(store):
    rec = zenbuji.activity_recent(14)
    assert len(rec) == 14
    assert rec[-1]["date"] == _today().isoformat()        # newest last
    assert rec[0]["date"] == (_today() - dt.timedelta(days=13)).isoformat()
    assert all(r["reviews"] == 0 for r in rec)            # empty store -> all zero


def test_add_study_time_accumulates_today(store):
    zenbuji.store.add_study_time(1500)
    zenbuji.store.add_study_time(1500)
    today = zenbuji.store.load_activity()[_today().isoformat()]
    assert today["time_ms"] == 3000


def test_add_study_time_zero_is_noop(store):
    zenbuji.store.add_study_time(0)
    assert zenbuji.store.load_activity() == {}
