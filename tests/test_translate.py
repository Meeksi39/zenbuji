"""Translation backends + dispatch + caching.

The HTTP layer is mocked (no network, ever); the dispatch/cache tests monkeypatch
the backend functions so they're fully offline and deterministic.
"""

import json
import urllib.request

import pytest

import zenbuji


# --- a fake urlopen so DeepL tests never touch the network ------------------ #
class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _fake_urlopen(payload, captured=None):
    def _open(req, timeout=None):
        if captured is not None:
            captured.append(req)
        return _FakeResp(payload)
    return _open


def card_cfg(**kw):
    base = {"backend": "deepl", "deepl_api_key": "", "ui_language": "en"}
    base.update(kw)
    return base


# --- translate_deepl (HTTP layer mocked) ------------------------------------ #
def test_deepl_success(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"translations": [{"text": "hello"}]}))
    out = zenbuji.translate_deepl("こんにちは", ["en", "de"], "k:fx", "en")
    assert out == {"en": "hello", "de": "hello"}


def test_deepl_free_host_for_fx_key(monkeypatch):
    reqs = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"translations": [{"text": "t"}]}, reqs))
    zenbuji.translate_deepl("x", ["en"], "abc:fx", "en")
    assert "api-free.deepl.com" in reqs[0].full_url


def test_deepl_pro_host_for_plain_key(monkeypatch):
    reqs = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"translations": [{"text": "t"}]}, reqs))
    zenbuji.translate_deepl("x", ["en"], "plainkey", "en")
    assert reqs[0].full_url.startswith("https://api.deepl.com")


def test_deepl_raises_on_network_error(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("network down")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(zenbuji.TranslationError):
        zenbuji.translate_deepl("x", ["en"], "k", "en")


# --- deepl_usage ------------------------------------------------------------ #
def test_usage_no_key_is_not_ok():
    assert zenbuji.deepl_usage("")["ok"] is False


def test_usage_success(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"character_count": 100, "character_limit": 500000}))
    u = zenbuji.deepl_usage("k:fx")
    assert u["ok"] and u["used"] == 100 and u["limit"] == 500000


def test_usage_error_is_captured(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("nope")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    u = zenbuji.deepl_usage("k")
    assert u["ok"] is False and u["error"]


# --- translate() dispatch (backends monkeypatched) -------------------------- #
def test_dispatch_deepl_no_key_notes_and_empty():
    out, notes = zenbuji.translate("こ", ["en"], card_cfg(backend="deepl"))
    assert out == {}
    assert any("key" in n.lower() for n in notes)


def test_dispatch_auto_uses_deepl_when_key(monkeypatch):
    monkeypatch.setattr(zenbuji.translation, "translate_deepl",
                        lambda t, tg, k, l: {x: "X" for x in tg})
    out, _ = zenbuji.translate("こ", ["en", "de"],
                               card_cfg(backend="auto", deepl_api_key="k:fx"))
    assert out == {"en": "X", "de": "X"}


def test_dispatch_deepl_falls_back_to_argos(monkeypatch):
    def boom(*_a):
        raise zenbuji.TranslationError("boom")
    monkeypatch.setattr(zenbuji.translation, "translate_deepl", boom)
    monkeypatch.setattr(zenbuji.translation, "translate_argos",
                        lambda t, tg, l: {x: "A" for x in tg})
    out, notes = zenbuji.translate("こ", ["en"], card_cfg(deepl_api_key="k"))
    assert out == {"en": "A"}
    assert any("argos" in n.lower() for n in notes)


def test_dispatch_both_fail_returns_empty(monkeypatch):
    def boom(*_a):
        raise zenbuji.TranslationError("x")
    monkeypatch.setattr(zenbuji.translation, "translate_deepl", boom)
    monkeypatch.setattr(zenbuji.translation, "translate_argos", boom)
    out, _ = zenbuji.translate("こ", ["en"], card_cfg(deepl_api_key="k"))
    assert out == {}


# --- translate_cached() caching contract (writes go to the temp store) ------ #
def test_cache_records_deepl_output(store, monkeypatch):
    monkeypatch.setattr(zenbuji.translation, "translate_deepl",
                        lambda t, tg, k, l: {x: "X" for x in tg})
    cfg = card_cfg(deepl_api_key="k", dictionary=True)
    out, _ = zenbuji.translate_cached("水", ["en", "de"], cfg, "みず")
    assert out == {"en": "X", "de": "X"}
    e = zenbuji.dict_get("水")
    assert e["translations"]["en"] == "X" and e["reading"] == "みず" and e["count"] == 1


def test_cache_serves_repeat_without_refetch(store, monkeypatch):
    calls = []

    def fake(t, tg, k, l):
        calls.append(list(tg))
        return {x: "X" for x in tg}

    monkeypatch.setattr(zenbuji.translation, "translate_deepl", fake)
    cfg = card_cfg(deepl_api_key="k", dictionary=True)
    zenbuji.translate_cached("水", ["en", "de"], cfg, "みず")       # fetches both
    out, _ = zenbuji.translate_cached("水", ["en", "de"], cfg, "みず")  # all cached
    assert out == {"en": "X", "de": "X"}
    assert zenbuji.dict_get("水")["count"] == 2     # repeat lookup still counts
    assert calls == [["en", "de"]]                  # DeepL hit only once


def test_cache_skips_argos_unless_opted_in(store, monkeypatch):
    monkeypatch.setattr(zenbuji.translation, "translate_argos",
                        lambda t, tg, l: {x: "A" for x in tg})
    cfg = card_cfg(backend="argos", dictionary=True, cache_offline=False)
    out, _ = zenbuji.translate_cached("空", ["en"], cfg, "そら")
    assert out == {"en": "A"}
    assert zenbuji.dict_get("空") is None            # offline output not stored


def test_cache_stores_argos_when_opted_in(store, monkeypatch):
    monkeypatch.setattr(zenbuji.translation, "translate_argos",
                        lambda t, tg, l: {x: "A" for x in tg})
    cfg = card_cfg(backend="argos", dictionary=True, cache_offline=True)
    zenbuji.translate_cached("空", ["en"], cfg, "そら")
    assert zenbuji.dict_get("空")["translations"]["en"] == "A"
