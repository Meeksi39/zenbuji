"""_reading_markup: on a missed reading, the kana the learner got right are
accent-coloured and the ones they missed are muted (Pango alpha).

Pure-logic test, but it imports the GTK learn module (for GLib.markup_escape_text),
so it skips where GTK4/libadwaita isn't importable (e.g. the light CI image)."""

import pytest

gi = pytest.importorskip("gi")
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
except (ValueError, ImportError):
    pytest.skip("GTK4 / libadwaita not importable", allow_module_level=True)

import zenbuji_learn as L  # bin/ is on sys.path via conftest

ACC = "#abc123"


def test_all_correct_is_all_accent():
    assert L._reading_markup("たべる", "たべる", ACC) == (
        '<span foreground="#abc123">た</span>'
        '<span foreground="#abc123">べ</span>'
        '<span foreground="#abc123">る</span>')


def test_all_wrong_is_all_muted():
    assert L._reading_markup("たべる", "", ACC) == (
        '<span alpha="40%">た</span>'
        '<span alpha="40%">べ</span>'
        '<span alpha="40%">る</span>')


def test_partial_match_accents_right_mutes_wrong():
    m = L._reading_markup("にほんご", "にほんが", ACC)
    for kana in ("に", "ほ", "ん"):
        assert f'<span foreground="#abc123">{kana}</span>' in m
    assert '<span alpha="40%">ご</span>' in m
    assert m.count('alpha="40%"') == 1          # only ご is muted


def test_non_contiguous_match():
    # に and ん match, ほ doesn't — the gap is muted, the matches accented.
    m = L._reading_markup("にほん", "にん", ACC)
    assert '<span alpha="40%">ほ</span>' in m
    assert m.count("foreground=") == 2


def test_special_chars_are_escaped():
    # The reading shouldn't be able to inject markup (defensive).
    m = L._reading_markup("a<b", "", ACC)
    assert "&lt;" in m and "<b" not in m.replace("&lt;", "")
