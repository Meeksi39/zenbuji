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


def test_shortcuts_info_shows_only_background_add_actions(monkeypatch):
    monkeypatch.setattr(zenbuji, "_read_keybinding", lambda slug: None)
    info = zenbuji.shortcuts_info("en")
    assert [s["keys"] for s in info] == ["Super+Shift+K", "Super+K"]
    assert all(s["label"] for s in info)


def test_shortcuts_info_uses_live_binding(monkeypatch):
    monkeypatch.setattr(zenbuji, "_read_keybinding",
                        lambda slug: "<Super>b" if slug == "zenbuji-ocr-add" else None)
    info = zenbuji.shortcuts_info("en")
    assert info[0]["keys"] == "Super+B"             # the rebound OCR-add


def test_launch_game_wires_live_refresh(store, monkeypatch):
    # Regression: the game overlay must pass watch_path so it live-refreshes
    # (it previously didn't, so added words never showed up).
    import pytest
    pytest.importorskip("gi")  # importing zenbuji_dict needs GTK
    import zenbuji_dict

    captured = {}
    monkeypatch.setattr(zenbuji_dict, "show_dictionary",
                        lambda **kw: captured.update(kw) or 0)
    zenbuji.launch_game({})
    assert captured.get("game_mode") is True
    assert captured.get("watch_path") == zenbuji.DICT_PATH
    assert captured.get("busy_path") == zenbuji.BUSY_PATH
    assert captured.get("shortcuts")
