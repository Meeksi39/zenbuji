"""Shared pytest fixtures.

The engine in the ``zenbuji`` package reads/writes JSON state files via the
path constants in ``zenbuji.paths``. We import it directly (its GTK/fugashi
imports are deferred into functions, so importing the package needs only the
stdlib) and redirect those paths at a per-test temp directory so tests never
touch real user data.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin"
CLI = BIN / "zenbuji_main.py"
sys.path.insert(0, str(BIN))

import zenbuji  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_caches(tmp_path, monkeypatch):
    """Keep the new in-memory/on-disk caches hermetic per test.

    Redirects the TTS WAV cache into a throwaway dir (so tests never read or
    write the real ~/.cache/zenbuji) and clears the dict/SRS/analyze memos before
    each test so state never leaks between them.
    """
    monkeypatch.setattr(zenbuji.paths, "TTS_CACHE_DIR", tmp_path / "tts-cache")
    zenbuji.store._clear_caches()
    zenbuji.srs._clear_caches()
    zenbuji.lang._tokenize.cache_clear()
    zenbuji.lang.dict_form.cache_clear()


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point all of zenbuji's state files at an isolated temp dir."""
    monkeypatch.setattr(zenbuji.paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(zenbuji.paths, "SRS_PATH", tmp_path / "srs.json")
    monkeypatch.setattr(zenbuji.paths, "DICT_PATH", tmp_path / "dictionary.json")
    monkeypatch.setattr(zenbuji.paths, "CAPTURED_PATH", tmp_path / "captured.json")
    monkeypatch.setattr(zenbuji.paths, "ACTIVITY_PATH", tmp_path / "activity.json")
    monkeypatch.setattr(zenbuji.paths, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(zenbuji.paths, "BUSY_PATH", tmp_path / "busy.json")
    return tmp_path


@pytest.fixture
def cli(tmp_path):
    """Run the CLI as a subprocess in a fully isolated environment.

    SAFETY: HOME, XDG_DATA_HOME and XDG_CONFIG_HOME are all redirected into a
    throwaway temp dir, so the subprocess can never read or write the real
    ~/.config/zenbuji or ~/.local/share/zenbuji — the user's production data is
    untouched no matter what the command does.
    """
    home = tmp_path
    data = home / ".local" / "share"
    config = home / ".config"
    data.mkdir(parents=True)
    config.mkdir(parents=True)
    zdata = data / "zenbuji"
    zconfig = config / "zenbuji"
    zdata.mkdir()
    zconfig.mkdir()

    env = dict(os.environ)
    env.update(HOME=str(home), XDG_DATA_HOME=str(data), XDG_CONFIG_HOME=str(config))

    def run(*args, stdin=None):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            capture_output=True, text=True, env=env, input=stdin, timeout=120,
        )

    run.data = zdata        # seed/inspect state files here
    run.config = zconfig
    return run
