"""End-to-end CLI smoke tests.

Each runs `zenbuji` as a subprocess in a fully isolated HOME/XDG environment (see
the `cli` fixture), so the real user data is never touched. Commands needing the
MeCab stack (`furigana`/`read`) skip when it isn't installed (e.g. in CI).
"""

import json

import pytest


def _seed(cli, name, obj):
    (cli.data / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_dict_json_empty(cli):
    r = cli("dict", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {}


def test_dict_json_reads_seeded_data(cli):
    _seed(cli, "dictionary.json", {
        "水": {"text": "水", "reading": "みず", "translations": {"en": "water"},
               "count": 3, "first_seen": "2026-01-01T00:00:00",
               "last_seen": "2026-01-02T00:00:00"},
    })
    r = cli("dict", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["水"]["translations"]["en"] == "water"


def test_stats_json_empty(cli):
    r = cli("stats", "--json")
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert s["total"] == 0 and len(s["recent"]) == 14


def test_stats_json_aggregates_seeded_data(cli):
    _seed(cli, "dictionary.json",
          {"a": {"text": "a", "reading": "あ", "translations": {"en": "a"}}})
    _seed(cli, "srs.json",
          {"a": {"interval": 3, "reps": 1, "last_reviewed": "2026-01-01T00:00:00",
                 "due": "2026-01-02T00:00:00", "correct": 2, "wrong": 1,
                 "lapses": 1, "ease": 2.3}})
    r = cli("stats", "--json")
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert s["total"] == 1
    assert s["reviews_total"] == 3
    assert s["by_level"]["learning"] == 1


def test_dict_clear_removes_file(cli):
    _seed(cli, "dictionary.json", {"x": {"text": "x"}})
    r = cli("dict", "--clear")
    assert r.returncode == 0, r.stderr
    assert not (cli.data / "dictionary.json").exists()


def test_export_tsv_skips_excluded(cli):
    _seed(cli, "dictionary.json", {
        "水": {"text": "水", "reading": "みず",
               "translations": {"en": "water", "de": "Wasser"},
               "first_seen": "2026-01-01T00:00:00"},
        "除外": {"text": "除外", "reading": "じょがい",
                 "translations": {"en": "excluded"}, "exclude": True,
                 "first_seen": "2026-01-02T00:00:00"},
    })
    r = cli("export")
    assert r.returncode == 0, r.stderr
    assert "#separator:tab" in r.stdout
    assert "水\tみず\twater\tWasser" in r.stdout
    assert "除外" not in r.stdout                       # excluded by default

    r_all = cli("export", "--all")
    assert r_all.returncode == 0, r_all.stderr
    assert "除外" in r_all.stdout                        # --all includes it


def test_export_writes_file_with_output_flag(cli):
    _seed(cli, "dictionary.json",
          {"水": {"text": "水", "reading": "みず",
                  "translations": {"en": "water"}}})
    out = cli.data / "deck.tsv"
    r = cli("export", "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert "exported 1 cards" in r.stdout
    assert "水\tみず\twater" in out.read_text(encoding="utf-8")


def test_add_manual_creates_entry_without_lookup(cli):
    r = cli("add", "--manual", "食べる", "--reading", "たべる",
            "--tr", "en=to eat", "--tr", "de=essen")
    assert r.returncode == 0, r.stderr
    d = json.loads(cli("dict", "--json").stdout)
    e = d["食べる"]
    assert e["reading"] == "たべる"
    assert e["translations"] == {"en": "to eat", "de": "essen"}
    assert e["count"] == 0                       # manual: no lookup happened


def test_add_manual_edits_existing(cli):
    cli("add", "--manual", "水", "--reading", "みづ", "--tr", "en=watr")
    r = cli("add", "--manual", "水", "--reading", "みず",
            "--tr", "en=water", "--tr", "de=Wasser")
    assert r.returncode == 0, r.stderr
    e = json.loads(cli("dict", "--json").stdout)["水"]
    assert e["reading"] == "みず"                  # corrected
    assert e["translations"] == {"en": "water", "de": "Wasser"}
    assert e["count"] == 0


def test_add_manual_needs_a_word(cli):
    r = cli("add", "--manual", "--tr", "en=x")
    assert r.returncode == 2                       # no surface given


def test_config_writes_only_to_isolated_path(cli):
    # SAFETY proof: a config write lands in the temp config dir, not the real one.
    r = cli("config", "--backend", "argos")
    assert r.returncode == 0, r.stderr
    written = json.loads((cli.config / "config.json").read_text(encoding="utf-8"))
    assert written["backend"] == "argos"


def test_furigana_json_offline(cli):
    pytest.importorskip("fugashi")
    pytest.importorskip("unidic_lite")
    r = cli("furigana", "--json", "日本語")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout).get("reading")


def test_read_json_offline_no_key(cli):
    # No DeepL key in the isolated config + explicit argos backend => no network.
    pytest.importorskip("fugashi")
    r = cli("read", "--json", "--backend", "argos", "日本語")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout).get("reading")
