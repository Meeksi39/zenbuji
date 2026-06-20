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


def test_capture_voice_is_energetic_and_distinct():
    # The new-word fanfare uses a fixed energetic VOICEVOX speaker...
    assert zenbuji._capture_voice(3) == zenbuji._CAPTURE_VOICE
    # ...but a different one when that speaker is already selected.
    assert zenbuji._capture_voice(zenbuji._CAPTURE_VOICE) == zenbuji._CAPTURE_VOICE_ALT
    assert zenbuji._CAPTURE_VOICE != zenbuji._CAPTURE_VOICE_ALT
    # Robust to a non-int / unset speaker.
    assert zenbuji._capture_voice(None) == zenbuji._CAPTURE_VOICE


def test_new_word_fanfare_spoken_before_reading(store, monkeypatch):
    # `add --speak` announces the energised intro (in a different voice) before
    # the reading for a brand-new word; a known re-capture skips the intro.
    spoken = []
    monkeypatch.setattr(zenbuji, "speak",
                        lambda text, cfg, block=False: spoken.append((text, cfg.get("voicevox_speaker"))))
    monkeypatch.setattr(zenbuji, "analyze", lambda t: ("ひ", []))
    # Mock the network layer so the real translate_cached/dict_record run and the
    # word is recorded (count == 1 => "new").
    monkeypatch.setattr(zenbuji, "translate_deepl",
                        lambda t, tg, k, l: {x: "fire" for x in tg})
    cfg = {"backend": "deepl", "deepl_api_key": "k", "dictionary": True,
           "languages": ["en"], "voicevox_speaker": 3}

    class A:  # argparse-like namespace
        ocr = ocr_image = selection = no_speak = quiet = json = False
        speak = True
        backend = lang = None
        words = ["火"]

    zenbuji.cmd_add(A(), cfg)
    assert spoken[0][0] == zenbuji._CAPTURE_NEW_INTRO          # intro first
    assert spoken[0][1] == zenbuji._capture_voice(3)          # in the punchy voice
    assert spoken[1][0] == "ひ"                                # then the reading (no intro)
    assert spoken[1][1] == 3                                   # normal voice


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
