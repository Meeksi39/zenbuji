"""Game-helper engine logic: the background-busy marker and shortcut info."""

import datetime as dt

import zenbuji


def test_busy_round_trip(store):
    assert zenbuji.read_busy() is None
    zenbuji.set_busy("translating")
    info = zenbuji.read_busy()
    assert info and info["stage"] == "translating"
    zenbuji.clear_busy()
    assert zenbuji.read_busy() is None


def test_busy_stale_reads_idle(store):
    old = (dt.datetime.now() - dt.timedelta(seconds=300)).isoformat(timespec="seconds")
    (store / "busy.json").write_text(f'{{"stage": "reading", "ts": "{old}"}}',
                                     encoding="utf-8")
    assert zenbuji.read_busy() is None              # older than max_age
    assert zenbuji.read_busy(max_age=10_000) is not None


def test_pretty_accel():
    assert zenbuji._pretty_accel("<Super><Shift>k") == "Super+Shift+K"
    assert zenbuji._pretty_accel("<Super>j") == "Super+J"


def test_shortcuts_info_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr(zenbuji, "_read_keybinding", lambda slug: None)
    info = zenbuji.shortcuts_info("en")
    keys = [s["keys"] for s in info]
    assert keys == ["Super+Shift+K", "Super+Shift+J", "Super+J", "Super+Shift+L"]
    assert all(s["label"] for s in info)


def test_shortcuts_info_uses_live_binding(monkeypatch):
    monkeypatch.setattr(zenbuji, "_read_keybinding",
                        lambda slug: "<Super>b" if slug == "zenbuji-ocr-add" else None)
    info = zenbuji.shortcuts_info("en")
    assert info[0]["keys"] == "Super+B"             # the rebound OCR-add
