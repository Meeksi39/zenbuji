"""GUI smoke tests: launch each window and assert it *builds and renders*
without crashing.

A window app blocks in ``app.run`` until closed, so "still alive after a short
settle" == "rendered fine"; an early exit is only OK if it's clean and shows no
traceback. Runs under any display (locally, or ``xvfb-run`` in CI) and is skipped
when there's no display or GTK4/libadwaita isn't importable. Each launch uses an
isolated HOME/XDG so it never touches real user data.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parent.parent / "bin" / "zenbuji_main.py"


def _has_display():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _gtk_available():
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.skipif(not _has_display(),
                       reason="no display (set DISPLAY or use xvfb-run)"),
    pytest.mark.skipif(not _gtk_available(),
                       reason="GTK4 / libadwaita not importable"),
]


@pytest.fixture
def gui(tmp_path):
    home = tmp_path
    data = home / ".local" / "share"
    config = home / ".config"
    data.mkdir(parents=True)
    config.mkdir(parents=True)
    (data / "zenbuji").mkdir()
    (config / "zenbuji").mkdir()
    env = dict(os.environ)
    env.update(HOME=str(home), XDG_DATA_HOME=str(data), XDG_CONFIG_HOME=str(config))

    class _Gui:
        pass

    g = _Gui()
    g.env = env
    g.data = data / "zenbuji"
    return g


def _seed(gui, name, obj):
    (gui.data / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _launch_ok(env, args, settle=3.0):
    proc = subprocess.Popen(
        [sys.executable, str(CLI), *args], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        proc.wait(timeout=settle)
        _out, err = proc.communicate()
        # Exited on its own: only acceptable if it was a clean, crash-free exit.
        assert "Traceback" not in err, err
        assert proc.returncode == 0, err
    except subprocess.TimeoutExpired:
        # Still running => it rendered without crashing. Shut it down.
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            _out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            _out, err = proc.communicate()
        assert "Traceback" not in err, err


_CARD = {"a": {"text": "a", "reading": "あ", "translations": {"en": "a"}}}
_SRS = {"a": {"interval": 3, "reps": 1, "last_reviewed": "2026-01-01T00:00:00",
              "due": "2026-01-02T00:00:00", "correct": 2, "wrong": 1,
              "lapses": 1, "ease": 2.3}}


def test_stats_window_with_data(gui):
    _seed(gui, "dictionary.json", _CARD)
    _seed(gui, "srs.json", _SRS)
    _launch_ok(gui.env, ["stats"])


def test_stats_window_empty(gui):
    _launch_ok(gui.env, ["stats"])


def test_game_window(gui):
    _seed(gui, "dictionary.json", _CARD)
    _launch_ok(gui.env, ["game"])


def test_dict_window(gui):
    _seed(gui, "dictionary.json", {
        "水": {"text": "水", "reading": "みず",
               "translations": {"en": "water", "de": "Wasser"}, "count": 2,
               "first_seen": "2026-01-01T00:00:00", "last_seen": "2026-01-02T00:00:00"},
    })
    _launch_ok(gui.env, ["dict"])


def test_learn_window_with_cards(gui):
    _seed(gui, "dictionary.json", _CARD)
    _launch_ok(gui.env, ["learn"])


def test_learn_window_empty(gui):
    _launch_ok(gui.env, ["learn"])


def test_popup_window(gui):
    # Needs the MeCab stack for analysis; skipped where it's absent (e.g. CI).
    pytest.importorskip("fugashi")
    _launch_ok(gui.env, ["popup", "日本語"], settle=6.0)


def test_about_window(gui):
    _launch_ok(gui.env, ["about"])


_CAPTURED = {
    "走る": {"lemma": "走る", "reading": "はしる", "pos": "動詞", "count": 2,
             "first_seen": "2026-01-01T00:00:00", "last_seen": "2026-01-03T00:00:00",
             "sample": "犬が走る", "source_title": "vid", "source_url": ""},
    "猫": {"lemma": "猫", "reading": "ねこ", "pos": "名詞", "count": 1,
           "first_seen": "2026-01-01T00:00:00", "last_seen": "2026-01-02T00:00:00",
           "sample": "猫がいる", "source_title": "vid", "source_url": ""},
    "鍵": {"lemma": "鍵", "reading": "かぎ", "pos": "名詞", "count": 1, "ignored": True,
           "first_seen": "2026-01-01T00:00:00", "last_seen": "2026-01-01T00:00:00",
           "sample": "鍵をかける", "source_title": "vid", "source_url": ""},
}


def test_dict_window_with_captured_button(gui):
    # With staged caption words present, the dict header shows a "New words (N)"
    # button — it should still build without crashing.
    _seed(gui, "dictionary.json", _CARD)
    _seed(gui, "captured.json", _CAPTURED)
    _launch_ok(gui.env, ["dict"])


def test_review_window(gui):
    # The review window builds its New + Ignored tabs from the staging store.
    _seed(gui, "dictionary.json", _CARD)
    _seed(gui, "captured.json", _CAPTURED)
    _launch_ok(gui.env, ["review"])


def test_review_window_empty(gui):
    _launch_ok(gui.env, ["review"])
