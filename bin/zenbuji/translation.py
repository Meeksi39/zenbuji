"""Translation backends (DeepL + Argos), dispatch, and the cached path.

The module name is ``translation`` (not ``translate``) so the public dispatch
function :func:`translate` stays reachable as ``zenbuji.translate`` without being
shadowed by the submodule. ``translate_deepl``/``translate_argos`` are called as
bare names within this module, so the test suite patches them here
(``zenbuji.translation.translate_deepl``) and the in-module calls pick the patch up.
"""

from __future__ import annotations

import json

from . import store
from .util import _note, _quiet_stderr

_ARGOS_LANGS = None


class TranslationError(Exception):
    pass


def translate_deepl(text: str, targets: list[str], api_key: str,
                    lang: str = "en") -> dict:
    import urllib.parse
    import urllib.request

    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    url = f"https://{host}/v2/translate"
    out = {}
    deepl_lang = {"en": "EN", "de": "DE"}
    for lang in targets:
        target = deepl_lang.get(lang)
        if not target:
            continue
        data = urllib.parse.urlencode(
            {"text": text, "source_lang": "JA", "target_lang": target}
        ).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"DeepL-Auth-Key {api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            out[lang] = payload["translations"][0]["text"]
        except Exception as exc:  # noqa: BLE001
            raise TranslationError(
                _note("deepl_failed", lang, error=exc)) from exc
    return out


def deepl_usage(api_key: str) -> dict:
    """Query the DeepL account usage endpoint to validate a key.

    Returns {"ok": bool, "used": int, "limit": int, "error": str}.
    """
    import urllib.request

    if not api_key:
        return {"ok": False, "used": 0, "limit": 0, "error": "no API key set"}
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    req = urllib.request.Request(
        f"https://{host}/v2/usage",
        headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return {
            "ok": True,
            "used": int(payload.get("character_count", 0)),
            "limit": int(payload.get("character_limit", 0)),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "used": 0, "limit": 0, "error": str(exc)}


def _argos_langs():
    global _ARGOS_LANGS
    if _ARGOS_LANGS is None:
        with _quiet_stderr():
            from argostranslate import translate as argos_translate

            _ARGOS_LANGS = argos_translate.get_installed_languages()
    return _ARGOS_LANGS


def _argos_get(code: str):
    for lang in _argos_langs():
        if lang.code == code:
            return lang
    return None


def translate_argos(text: str, targets: list[str], lang: str = "en") -> dict:
    try:
        import argostranslate.translate  # noqa: F401
    except ImportError as exc:
        raise TranslationError(
            _note("argos_not_installed", lang)
        ) from exc

    src = _argos_get("ja")
    if src is None:
        raise TranslationError(_note("argos_no_ja", lang))
    out = {}
    for target in targets:
        dst = _argos_get(target)
        if dst is None:
            raise TranslationError(
                _note("argos_no_model", lang, lang=target))
        try:
            with _quiet_stderr():
                out[target] = src.get_translation(dst).translate(text)
        except Exception as exc:  # noqa: BLE001
            raise TranslationError(
                _note("argos_failed", lang, error=exc)) from exc
    return out


def translate(text: str, targets: list[str], cfg: dict) -> tuple[dict, list[str]]:
    """Translate text into each target language. Returns (translations, notes)."""
    store.set_busy("translating")
    try:
        return _translate_impl(text, targets, cfg)
    finally:
        store.clear_busy()


def _translate_impl(text: str, targets: list[str], cfg: dict) -> tuple[dict, list[str]]:
    backend = cfg.get("backend", "auto")
    key = cfg.get("deepl_api_key", "")
    lang = cfg.get("ui_language", "en")
    notes: list[str] = []

    if backend == "auto":
        backend = "deepl" if key else "argos"

    if backend == "deepl":
        if not key:
            notes.append(_note("deepl_no_key", lang))
            return {}, notes
        try:
            return translate_deepl(text, targets, key, lang), notes
        except TranslationError as exc:
            notes.append(str(exc))
            # Fall back to offline if available.
            try:
                return translate_argos(text, targets, lang), [
                    *notes,
                    _note("fell_back_argos", lang),
                ]
            except TranslationError:
                return {}, notes

    # argos
    try:
        return translate_argos(text, targets, lang), notes
    except TranslationError as exc:
        notes.append(str(exc))
        if key:
            try:
                return translate_deepl(text, targets, key, lang), [
                    *notes,
                    _note("fell_back_deepl", lang),
                ]
            except TranslationError as exc2:
                notes.append(str(exc2))
        return {}, notes


def translate_cached(text: str, targets: list[str], cfg: dict,
                     reading: str) -> tuple[dict, list[str]]:
    """Like translate(), but reuse/record a local dictionary cache.

    Strings already translated are served from the dictionary instead of being
    re-requested (faster, and saves DeepL quota); only the missing target
    languages are fetched. Each lookup bumps the entry's count. DeepL output is
    always cacheable. Argos (offline) output is cached only when `cache_offline`
    is enabled — handy for building a practice deck without a DeepL key. With
    the dictionary off, falls straight through to translate().
    """
    backend = cfg.get("backend", "auto")
    key = cfg.get("deepl_api_key", "")
    lang = cfg.get("ui_language", "en")
    effective = ("deepl" if key else "argos") if backend == "auto" else backend
    cache_offline = bool(cfg.get("cache_offline", False))

    if not cfg.get("dictionary", True):
        return translate(text, targets, cfg)

    entry = store.dict_get(text)
    cached = dict(entry.get("translations", {})) if entry else {}
    missing = [t for t in targets if not cached.get(t)]
    notes: list[str] = []
    fresh: dict = {}          # newly fetched and cacheable
    uncacheable: dict = {}    # newly fetched but must NOT be stored
    if missing:
        store.set_busy("translating")  # real fetch ahead (cache hits stay instant)
        try:
            if effective == "deepl" and key:
                try:
                    fresh = translate_deepl(text, missing, key, lang)
                except TranslationError as exc:
                    notes.append(str(exc))
                    # Offline fallback for the missing langs; cache if opted in.
                    try:
                        argos = translate_argos(text, missing, lang)
                        notes.append(_note("fell_back_argos", lang))
                        (fresh if cache_offline else uncacheable).update(argos)
                    except TranslationError:
                        pass
            else:
                # Argos (offline) backend, or DeepL requested with no key set.
                try:
                    argos = translate_argos(text, missing, lang)
                    (fresh if cache_offline else uncacheable).update(argos)
                except TranslationError as exc:
                    notes.append(str(exc))
        finally:
            store.clear_busy()

    # Record/refresh the entry (count++ even on a pure cache hit) whenever we
    # have a cacheable result — a reused entry or freshly fetched cacheable
    # translations. Argos-only output with cache_offline off never lands here.
    to_store = {**cached, **fresh}
    if to_store:
        store.dict_record(text, reading, to_store)

    merged = {**to_store, **uncacheable}
    return {t: merged.get(t) for t in targets if merged.get(t)}, notes
