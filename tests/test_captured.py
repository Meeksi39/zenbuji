"""Captured-words staging store + the Firefox native-messaging framing.

These cover the pure engine logic, so they stay fugashi-free: the captured store
takes already-tokenised ``(lemma, reading, pos)`` tuples, and the native-host
test stubs ``lang.content_words``. The tokeniser itself is exercised in
``test_furigana.py`` (which skips when MeCab isn't installed).
"""

import io
import json
import struct

import zenbuji


def _frame(obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return struct.pack("<I", len(data)) + data


# --------------------------------------------------------------------------- #
# Captured store
# --------------------------------------------------------------------------- #
def test_capture_words_adds_new(store):
    n = zenbuji.store.capture_words([("走る", "はしる", "動詞")], sample="犬が走る")
    assert n == 1
    new = zenbuji.store.captured_new()
    assert [e["lemma"] for e in new] == ["走る"]
    assert new[0]["reading"] == "はしる"
    assert new[0]["sample"] == "犬が走る"


def test_capture_words_skips_dict_words(store):
    zenbuji.store.dict_record("走る", "はしる", {"en": "run"})
    assert zenbuji.store.capture_words([("走る", "はしる", "動詞")]) == 0
    assert zenbuji.store.captured_new() == []


def test_captured_new_filters_dict_added_later(store):
    zenbuji.store.capture_words([("走る", "はしる", "動詞")])
    zenbuji.store.dict_record("走る", "はしる", {"en": "run"})
    assert zenbuji.store.captured_new() == []      # filtered again at read time


def test_captured_ignore_excludes_but_keeps_row(store):
    zenbuji.store.capture_words([("走る", "はしる", "動詞")])
    zenbuji.store.captured_ignore("走る")
    assert zenbuji.store.captured_new() == []
    assert zenbuji.store.load_captured()["走る"]["ignored"] is True
    # a re-capture must not resurface an ignored word
    zenbuji.store.capture_words([("走る", "はしる", "動詞")])
    assert zenbuji.store.captured_new() == []


def test_captured_prune_drops_added(store):
    zenbuji.store.capture_words([("走る", "はしる", "動詞")])
    zenbuji.store.captured_prune(["走る"])
    assert "走る" not in zenbuji.store.load_captured()


def test_captured_resolve_added_and_ignored(store):
    zenbuji.store.capture_words([("走る", "はしる", "動詞"), ("猫", "ねこ", "名詞")])
    zenbuji.store.captured_resolve("走る", "added")
    zenbuji.store.captured_resolve("猫", "ignored")
    assert "走る" not in zenbuji.store.load_captured()
    assert zenbuji.store.load_captured()["猫"]["ignored"] is True
    assert zenbuji.store.captured_new() == []


def test_capture_words_bumps_count_keeps_first_sight(store):
    zenbuji.store.capture_words([("走る", "はしる", "動詞")], sample="犬が走る")
    zenbuji.store.capture_words([("走る", "はしる", "動詞")], sample="人が走った")
    entry = zenbuji.store.load_captured()["走る"]
    assert entry["count"] == 2
    assert entry["sample"] == "犬が走る"            # first-sight wins
    assert entry["first_seen"] <= entry["last_seen"]


def test_captured_new_newest_first(store):
    zenbuji.store.capture_words([("猫", "ねこ", "名詞")])
    zenbuji.store.capture_words([("犬", "いぬ", "名詞")])
    assert [e["lemma"] for e in zenbuji.store.captured_new()] == ["犬", "猫"]


def test_clear_captured_removes_file(store):
    zenbuji.store.capture_words([("走る", "はしる", "動詞")])
    assert (store / "captured.json").exists()
    zenbuji.store.clear_captured()
    assert not (store / "captured.json").exists()
    assert zenbuji.store.load_captured() == {}


def test_captured_ignored_lists_only_ignored(store):
    zenbuji.store.capture_words([("走る", "はしる", "動詞"), ("猫", "ねこ", "名詞")])
    zenbuji.store.captured_ignore("猫")
    assert [e["lemma"] for e in zenbuji.store.captured_new()] == ["走る"]
    assert [e["lemma"] for e in zenbuji.store.captured_ignored()] == ["猫"]


def test_captured_unignore_returns_to_new(store):
    zenbuji.store.capture_words([("猫", "ねこ", "名詞")])
    zenbuji.store.captured_ignore("猫")
    assert zenbuji.store.captured_new() == []
    zenbuji.store.captured_unignore("猫")
    assert [e["lemma"] for e in zenbuji.store.captured_new()] == ["猫"]
    assert zenbuji.store.captured_ignored() == []


def test_captured_new_ignore_katakana_filter(store):
    zenbuji.store.capture_words([("猫", "ねこ", "名詞"), ("コーヒー", "こーひー", "名詞")])
    assert "コーヒー" in [e["lemma"] for e in zenbuji.store.captured_new()]
    # katakana-only loanword dropped, kanji word kept
    assert [e["lemma"] for e in
            zenbuji.store.captured_new(ignore_katakana=True)] == ["猫"]


def test_is_katakana_only():
    f = zenbuji.lang.is_katakana_only
    assert f("コーヒー") and f("メール") and f("データー")
    assert not f("珈琲") and not f("猫") and not f("ねこ")
    assert not f("test") and not f("") and not f("コーヒー牛乳")


# --------------------------------------------------------------------------- #
# Native-messaging framing
# --------------------------------------------------------------------------- #
def test_nm_write_then_read_roundtrip():
    buf = io.BytesIO()
    zenbuji.cli._nm_write(buf, {"lines": ["猫"], "title": "t"})
    buf.seek(0)
    assert zenbuji.cli._nm_read(buf) == {"lines": ["猫"], "title": "t"}


def test_nm_read_clean_eof_returns_none():
    assert zenbuji.cli._nm_read(io.BytesIO()) is None


def test_nm_read_partial_length_returns_none():
    assert zenbuji.cli._nm_read(io.BytesIO(b"\x02\x00")) is None


def test_nm_read_truncated_body_returns_none():
    raw = struct.pack("<I", 10) + b"abc"            # claims 10 bytes, sends 3
    assert zenbuji.cli._nm_read(io.BytesIO(raw)) is None


def test_nm_read_malformed_json_returns_empty_dict():
    raw = struct.pack("<I", 3) + b"abc"             # 3 bytes, not JSON
    assert zenbuji.cli._nm_read(io.BytesIO(raw)) == {}


def test_native_host_ignores_browser_args(monkeypatch, tmp_path):
    # Firefox launches the host as `native-host <manifest-path> <ext-id>`; those
    # extra argv must NOT make the dispatcher's argparse kill the host before it
    # reads a message (regression: it used to call parse_args and SystemExit).
    monkeypatch.setattr(zenbuji.paths, "CONFIG_PATH", tmp_path / "none.json")
    called = {}

    def fake_native_host(cfg):
        called["ok"] = True
        return 0

    monkeypatch.setattr(zenbuji.cli, "cmd_native_host", fake_native_host)
    rc = zenbuji.cli.main(
        ["native-host", "/path/to/app.json", "zenbuji-capture@meeksi39"])
    assert rc == 0 and called.get("ok")


def test_cmd_native_host_stages_a_message(store, monkeypatch):
    monkeypatch.setattr(zenbuji.lang, "content_words",
                        lambda line: [("走る", "はしる", "動詞")])
    inp = io.BytesIO(_frame({"lines": ["犬が走る"], "title": "vid", "url": "u"}))
    out = io.BytesIO()
    assert zenbuji.cli.cmd_native_host({}, stdin=inp, stdout=out) == 0
    out.seek(0)
    assert zenbuji.cli._nm_read(out) == {"ok": True, "added": 1, "new": 1}
    new = zenbuji.store.captured_new()
    assert new[0]["lemma"] == "走る"
    assert new[0]["source_title"] == "vid"
    assert new[0]["sample"] == "犬が走る"
