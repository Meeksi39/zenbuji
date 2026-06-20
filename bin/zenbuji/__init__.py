"""zenbuji — 全部字

Take Japanese text and return furigana (readings) plus English and German
translations. Designed to be omni-available for immersive learners: run it on
the command line, from a global hotkey on the current text selection, from the
GNOME Shell top-bar menu, or from a file-manager context menu.

Furigana is produced offline with fugashi + unidic-lite. Translation uses an
offline backend (Argos Translate) by default and an optional online backend
(DeepL free API) when a key is configured.

This package was split out of a single ``bin/zenbuji.py`` module. The public
API is unchanged: ``import zenbuji; zenbuji.srs_review(...)`` etc. still work
because :func:`__getattr__` forwards every attribute access to the submodule
that owns it — so ``zenbuji.DICT_PATH`` always reflects the *current*
``zenbuji.paths.DICT_PATH`` (the test suite redirects it there), and a call like
``zenbuji.translate(...)`` resolves to the dispatch function in
:mod:`zenbuji.translation` without the submodule shadowing it.
"""

from __future__ import annotations

# Import the submodules eagerly so they're registered (and reachable as
# ``zenbuji.paths`` etc., which is where the tests patch their seams). The
# import order is the dependency order: each only imports ones above it.
from . import (  # noqa: F401
    paths,
    util,
    store,
    srs,
    grade,
    lang,
    ocr,
    translation,
    tts,
    pipeline,
    cli,
)

# Searched in order by __getattr__; later modules win only for names the
# earlier ones don't define (all public names are unique across submodules).
_SUBMODULES = (
    paths, util, store, srs, grade, lang, ocr, translation, tts, pipeline, cli,
)


def __getattr__(name: str):
    """Forward ``zenbuji.<name>`` to whichever submodule defines it.

    Keeps every legacy ``zenbuji.<public_name>`` call site working after the
    split, and — crucially — keeps reads dynamic, so a monkeypatch on a
    submodule attribute (e.g. ``zenbuji.paths.DICT_PATH``) is visible through
    the package namespace too.
    """
    for mod in _SUBMODULES:
        try:
            return getattr(mod, name)
        except AttributeError:
            continue
    raise AttributeError(f"module 'zenbuji' has no attribute {name!r}")
