"""Atomic writes + rolling .bak recovery for the JSON state files.

These guard against a kill mid-write truncating a file (atomic temp + replace)
and let a corrupt file self-heal from its last-good `.bak` on the next read.
All hermetic — the `store` fixture redirects `zenbuji.paths.*` into a tmp dir, so
the `.bak` siblings land there too.
"""

import json

import zenbuji
from zenbuji import paths


def test_atomic_write_json_roundtrip_and_bak(tmp_path):
    p = tmp_path / "x.json"
    paths.atomic_write_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert not (tmp_path / "x.json.bak").exists()      # nothing prior to back up
    paths.atomic_write_json(p, {"a": 1, "b": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "b": 2}
    # the .bak holds the version from before the second write
    assert json.loads((tmp_path / "x.json.bak").read_text(encoding="utf-8")) == {"a": 1}


def test_load_json_recovers_and_self_heals(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("garbage{", encoding="utf-8")
    (tmp_path / "x.json.bak").write_text(json.dumps({"ok": True}), encoding="utf-8")
    assert paths.load_json(p, None) == {"ok": True}
    # the corrupt main file is restored from the backup
    assert json.loads(p.read_text(encoding="utf-8")) == {"ok": True}


def test_load_json_default_when_nothing_usable(tmp_path):
    assert paths.load_json(tmp_path / "missing.json", {"d": 1}) == {"d": 1}


def test_dict_recovers_from_bak_after_corruption(store):
    zenbuji.store.save_dict({"猫": {"text": "猫"}})
    zenbuji.store.save_dict({"猫": {"text": "猫"}, "犬": {"text": "犬"}})  # .bak = {猫}
    (store / "dictionary.json").write_text("{corrupt", encoding="utf-8")
    zenbuji.store._clear_caches()
    assert zenbuji.store.load_dict() == {"猫": {"text": "猫"}}


def test_srs_recovers_from_bak_after_corruption(store):
    zenbuji.srs.save_srs({"a": {"reps": 1}})
    zenbuji.srs.save_srs({"a": {"reps": 2}})                # .bak = {"a":{"reps":1}}
    (store / "srs.json").write_text("nope", encoding="utf-8")
    zenbuji.srs._clear_caches()
    assert zenbuji.srs.load_srs() == {"a": {"reps": 1}}


def test_clear_dict_removes_file_and_bak(store):
    zenbuji.store.save_dict({"a": {"text": "a"}})
    zenbuji.store.save_dict({"a": {"text": "a"}, "b": {"text": "b"}})
    assert (store / "dictionary.json.bak").exists()
    zenbuji.store.clear_dict()
    assert not (store / "dictionary.json").exists()
    assert not (store / "dictionary.json.bak").exists()
