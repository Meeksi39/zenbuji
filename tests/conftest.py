"""Shared pytest fixtures.

The engine in ``bin/zenbuji.py`` reads/writes JSON state files via module-level
path constants. We import it directly (its GTK/fugashi imports are deferred into
functions, so importing the module needs only the stdlib) and redirect those
paths at a per-test temp directory so tests never touch real user data.
"""

import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import zenbuji  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point all of zenbuji's state files at an isolated temp dir."""
    monkeypatch.setattr(zenbuji, "DATA_DIR", tmp_path)
    monkeypatch.setattr(zenbuji, "SRS_PATH", tmp_path / "srs.json")
    monkeypatch.setattr(zenbuji, "DICT_PATH", tmp_path / "dictionary.json")
    monkeypatch.setattr(zenbuji, "ACTIVITY_PATH", tmp_path / "activity.json")
    monkeypatch.setattr(zenbuji, "HISTORY_PATH", tmp_path / "history.json")
    return tmp_path
