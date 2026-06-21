"""Anki export formatting: TSV/CSV columns, headers, filtering, ordering."""

import csv
import io

import zenbuji


def _entry(text, reading, translations, **extra):
    e = {"text": text, "reading": reading, "translations": translations,
         "first_seen": "2026-01-01T00:00:00"}
    e.update(extra)
    return e


def _rows(text):
    """The data rows (header #lines and blanks dropped)."""
    return [ln for ln in text.splitlines() if ln and not ln.startswith("#")]


def test_tsv_header_and_row():
    entries = {"食べる": _entry("食べる", "たべる",
                                 {"en": "to eat", "de": "essen"})}
    text, count = zenbuji.exporting.dict_to_anki(entries, ["en", "de"], fmt="tsv")
    assert count == 1
    assert "#separator:tab" in text
    assert "#columns:Expression\tReading\tEnglish\tGerman" in text
    assert "食べる\tたべる\tto eat\tessen" in _rows(text)


def test_column_count_matches_languages():
    entries = {"水": _entry("水", "みず", {"en": "water"})}
    text, _ = zenbuji.exporting.dict_to_anki(entries, ["en"], fmt="tsv")
    row = _rows(text)[0]
    assert len(row.split("\t")) == 3          # Expression, Reading, + 1 language


def test_csv_quotes_comma_in_translation():
    entries = {"水": _entry("水", "みず", {"en": "water, H2O", "de": "Wasser"})}
    text, _ = zenbuji.exporting.dict_to_anki(entries, ["en", "de"], fmt="csv")
    assert "#separator:comma" in text
    parsed = list(csv.reader(io.StringIO("\n".join(_rows(text)))))
    assert parsed[0] == ["水", "みず", "water, H2O", "Wasser"]   # comma intact


def test_excluded_entries_skipped_by_default():
    entries = {
        "水": _entry("水", "みず", {"en": "water"}),
        "除外": _entry("除外", "じょがい", {"en": "excluded"}, exclude=True),
    }
    text, count = zenbuji.exporting.dict_to_anki(entries, ["en"], fmt="tsv")
    assert count == 1 and "除外" not in text
    text_all, count_all = zenbuji.exporting.dict_to_anki(
        entries, ["en"], fmt="tsv", include_excluded=True)
    assert count_all == 2 and "除外" in text_all


def test_entries_without_translation_are_skipped():
    entries = {
        "水": _entry("水", "みず", {"en": "water"}),
        "無": _entry("無", "む", {}),                       # no translation
        "別": _entry("別", "べつ", {"fr": "autre"}),        # not in target langs
    }
    text, count = zenbuji.exporting.dict_to_anki(entries, ["en", "de"], fmt="tsv")
    assert count == 1 and "水" in text and "無" not in text and "別" not in text


def test_empty_dict_is_header_only():
    text, count = zenbuji.exporting.dict_to_anki({}, ["en", "de"], fmt="tsv")
    assert count == 0 and _rows(text) == []
    assert text.startswith("#separator:tab")


def test_no_header_omits_anki_lines():
    entries = {"水": _entry("水", "みず", {"en": "water"})}
    text, _ = zenbuji.exporting.dict_to_anki(entries, ["en"], fmt="tsv",
                                             header=False)
    assert not text.startswith("#")
    assert text.strip() == "水\tみず\twater"


def test_internal_tab_newline_flattened_to_one_row():
    entries = {"水": _entry("水", "みず", {"en": "a\tb\nc"})}
    text, _ = zenbuji.exporting.dict_to_anki(entries, ["en"], fmt="tsv",
                                             header=False)
    assert _rows(text) == ["水\tみず\ta b c"]   # one row, no stray tabs/newlines


def test_rows_ordered_by_first_seen():
    entries = {
        "b": _entry("b", "び", {"en": "b"}, first_seen="2026-03-01T00:00:00"),
        "a": _entry("a", "あ", {"en": "a"}, first_seen="2026-01-01T00:00:00"),
        "c": _entry("c", "し", {"en": "c"}, first_seen="2026-02-01T00:00:00"),
    }
    text, _ = zenbuji.exporting.dict_to_anki(entries, ["en"], fmt="tsv",
                                             header=False)
    assert [r.split("\t")[0] for r in _rows(text)] == ["a", "c", "b"]
