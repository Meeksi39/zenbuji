"""Pure sort/filter predicates for the dictionary grid.

Importing zenbuji_dict pulls in GTK4/libadwaita, so these skip in the
dependency-light CI job (the predicates themselves touch no GTK).
"""

import sys
from pathlib import Path

import pytest

gi = pytest.importorskip("gi")
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
except (ValueError, ImportError):
    pytest.skip("GTK4 / libadwaita not available", allow_module_level=True)

BIN = Path(__file__).resolve().parent.parent / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))
import zenbuji_dict as zd  # noqa: E402


def test_dict_matches_filters():
    plain = {"text": "犬", "translations": {"en": "dog"}}
    excl = {"text": "猫", "exclude": True, "translations": {"en": "cat"}}
    untr = {"text": "鳥", "translations": {"en": ""}}
    assert zd.dict_matches(plain, "", "all")
    assert not zd.dict_matches(plain, "", "excluded")
    assert zd.dict_matches(excl, "", "excluded")
    assert zd.dict_matches(untr, "", "untranslated")
    assert not zd.dict_matches(plain, "", "untranslated")


def test_dict_matches_search_needle():
    e = {"text": "犬", "reading": "いぬ", "translations": {"en": "dog"}}
    assert zd.dict_matches(e, "dog", "all")
    assert zd.dict_matches(e, "いぬ", "all")
    assert not zd.dict_matches(e, "zzz", "all")


def test_dict_matches_due():
    due = {"text": "a", "srs": {"due": "2000-01-01T00:00:00"}}
    notdue = {"text": "b", "srs": {"due": "2999-01-01T00:00:00"}}
    none = {"text": "c"}
    assert zd.dict_matches(due, "", "due")
    assert not zd.dict_matches(notdue, "", "due")
    assert not zd.dict_matches(none, "", "due")


def test_dict_sort_key_orders():
    a = {"text": "あ", "reading": "あ", "count": 5, "last_seen": "2026-01-02",
         "srs": {"due": "2026-01-05"}}
    b = {"text": "い", "reading": "い", "count": 1, "last_seen": "2026-01-01",
         "srs": {}}
    assert zd.dict_sort_key(a, "alpha") < zd.dict_sort_key(b, "alpha")
    assert zd.dict_sort_key(a, "count") < zd.dict_sort_key(b, "count")   # most-seen first
    assert zd.dict_sort_key(a, "due") < zd.dict_sort_key(b, "due")       # has-due first
    assert zd.dict_sort_key(b, "oldest") < zd.dict_sort_key(a, "oldest")
