"""Export the local dictionary as Anki-importable TSV/CSV text.

Pure formatting — no disk, no GTK — so it's trivially testable. The CLI `export`
command reads ``store.load_dict()`` and hands the entries here.
"""

from __future__ import annotations

import csv
import io
import re

from .util import LANG_NAMES

_WS_RE = re.compile(r"[\t\n\r]+")

# Anki's text importer reads these header lines (Anki 2.1.55+): the field
# separator, that fields are plain text (not HTML), and the column/field names.
_SEPARATOR_NAME = {"tsv": "tab", "csv": "comma"}
_DELIMITER = {"tsv": "\t", "csv": ","}


def _field(value: str) -> str:
    """One row cell: collapse any internal tab/newline to a space so every entry
    stays a single line (what Anki's importer expects)."""
    return _WS_RE.sub(" ", (value or "").strip())


def dict_to_anki(entries: dict, languages, *, fmt: str = "tsv",
                 include_excluded: bool = False,
                 header: bool = True) -> tuple[str, int]:
    """Render dictionary entries as Anki-importable text.

    Columns: Expression (surface), Reading (kana), then one per language in
    `languages`. Skips entries flagged ``exclude`` (unless `include_excluded`)
    and entries with no translation in any chosen language. Rows are ordered by
    ``first_seen`` (the order the words were met). Returns ``(text, card_count)``.
    """
    fmt = fmt if fmt in _DELIMITER else "tsv"
    languages = list(languages) or ["en", "de"]
    delimiter = _DELIMITER[fmt]
    columns = ["Expression", "Reading"] + [
        LANG_NAMES.get(lang, lang.upper()) for lang in languages]

    rows = []
    for entry in sorted(entries.values(),
                        key=lambda e: (e.get("first_seen") or "")):
        if entry.get("exclude") and not include_excluded:
            continue
        translations = entry.get("translations", {}) or {}
        values = [_field(translations.get(lang, "")) for lang in languages]
        if not any(values):           # nothing to put on the back of the card
            continue
        rows.append([_field(entry.get("text", "")),
                     _field(entry.get("reading", ""))] + values)

    buf = io.StringIO()
    if header:
        buf.write(f"#separator:{_SEPARATOR_NAME[fmt]}\n")
        buf.write("#html:false\n")
        buf.write("#columns:" + delimiter.join(columns) + "\n")
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    writer.writerows(rows)
    return buf.getvalue(), len(rows)
