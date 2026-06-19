"""SM-2-lite scheduling: srs_review / srs_status / srs_select / srs_summary."""

import zenbuji


def test_status_of_unstudied_card():
    assert zenbuji.srs_status(None) == "new"
    assert zenbuji.srs_status({"last_reviewed": None}) == "new"


def test_status_thresholds():
    base = {"last_reviewed": "2026-01-01T00:00:00"}
    assert zenbuji.srs_status({**base, "interval": 1}) == "learning"
    assert zenbuji.srs_status({**base, "interval": 6}) == "learning"
    assert zenbuji.srs_status({**base, "interval": 7}) == "young"
    assert zenbuji.srs_status({**base, "interval": 20}) == "young"
    assert zenbuji.srs_status({**base, "interval": 21}) == "mature"


def test_correct_progression(store):
    s = zenbuji.srs_review("X", True)
    assert (s["reps"], s["interval"], s["correct"]) == (1, 1, 1)
    assert zenbuji.srs_status(s) == "learning"

    s = zenbuji.srs_review("X", True)
    assert s["interval"] == 6

    s = zenbuji.srs_review("X", True)
    assert s["interval"] == 15          # round(6 * 2.5)
    assert zenbuji.srs_status(s) == "young"

    s = zenbuji.srs_review("X", True)
    assert s["interval"] == 38          # round(15 * 2.5)
    assert zenbuji.srs_status(s) == "mature"


def test_wrong_resets_and_lowers_ease(store):
    zenbuji.srs_review("X", True)
    zenbuji.srs_review("X", True)       # interval 6
    s = zenbuji.srs_review("X", False)
    assert s["interval"] == 0 and s["reps"] == 0
    assert s["lapses"] == 1 and s["wrong"] == 1
    assert s["ease"] == 2.3             # 2.5 - 0.2


def test_ease_has_a_floor(store):
    for _ in range(12):
        zenbuji.srs_review("X", False)
    assert zenbuji.srs_get("X")["ease"] >= 1.3


def test_review_persists(store):
    zenbuji.srs_review("X", True)
    assert zenbuji.srs_get("X")["reps"] == 1


def test_select_filters_and_orders(store):
    zenbuji.dict_record("有", "ゆう", {"en": "have"})    # reading + translation -> eligible
    zenbuji.dict_record("無", "", {"en": "none"})        # no reading -> excluded
    data = zenbuji.load_dict()
    data["空"] = {"text": "空", "reading": "そら", "translations": {}}  # no translation
    zenbuji.save_dict(data)

    cards = zenbuji.srs_select(10)
    texts = [c["text"] for c in cards]
    assert "有" in texts
    assert "無" not in texts and "空" not in texts
    assert cards[0]["status"] == "new"  # never reviewed sorts first


def test_select_respects_limit(store):
    for i in range(5):
        zenbuji.dict_record(f"w{i}", f"r{i}", {"en": f"t{i}"})
    assert len(zenbuji.srs_select(3)) == 3


def test_summary_none_when_unstudied(store):
    zenbuji.dict_record("X", "えっくす", {"en": "x"})
    assert zenbuji.srs_summary("X") is None


def test_summary_after_review(store):
    zenbuji.srs_review("X", True)
    s = zenbuji.srs_summary("X")
    assert s["level"] == "learning"
    assert s["correct"] == 1 and s["wrong"] == 0
    assert s["due"]
