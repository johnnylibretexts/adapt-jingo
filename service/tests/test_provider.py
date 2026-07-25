import json
from pathlib import Path

from app.provider import JsonPhoneticsProvider


def _write(tmp_path, rel, obj):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))
    return p


def test_get_returns_record_when_present(tmp_path):
    _write(tmp_path, "es/es-u1-l1-e1.json", {
        "lang": "es", "phones": ["a", "l", "a"], "ids": [5, 31, 5],
        "words": [{"start": 0, "len": 3, "phones": ["a", "l", "a"]}],
        "coverage": 1.0, "unknown": [], "espeak_voice": "es-419",
    })
    prov = JsonPhoneticsProvider(records_dir=str(tmp_path))
    rec = prov.get("es", "es-u1-l1-e1")
    assert rec is not None
    assert rec["ids"] == [5, 31, 5]


def test_get_returns_none_on_miss(tmp_path):
    prov = JsonPhoneticsProvider(records_dir=str(tmp_path))
    assert prov.get("es", "missing") is None


def test_tag_map_returns_map_dict(tmp_path):
    _write(tmp_path, "tag_map/es.json", {"language": "es", "map": {"a": "open-a", "ɲ": None}, "unmapped_neutral": []})
    prov = JsonPhoneticsProvider(records_dir=str(tmp_path))
    assert prov.tag_map("es") == {"a": "open-a", "ɲ": None}


def test_tag_map_empty_when_missing(tmp_path):
    prov = JsonPhoneticsProvider(records_dir=str(tmp_path))
    assert prov.tag_map("xx") == {}


def test_get_rejects_path_traversal_in_exercise_id(tmp_path):
    # records_dir/es must exist so the traversal path is actually reachable
    # at the OS level -- proving the guard (not a missing intermediate dir)
    # is what blocks the read.
    (tmp_path / "es").mkdir(parents=True)
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"leaked": True}))
    prov = JsonPhoneticsProvider(records_dir=str(tmp_path))
    assert prov.get("es", "../secret") is None
    assert prov.get("es", "..") is None
    assert prov.get("es", ".") is None
    assert prov.get("es", "a/b") is None
    assert prov.get("es", "a\\b") is None


def test_get_rejects_path_traversal_in_language(tmp_path):
    # records_dir must exist for the ".." to be reachable at the OS level;
    # plant a sibling dir "foo" with the target file to prove escape works
    # absent the guard.
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    _write(tmp_path, "foo/x.json", {"leaked": True})
    prov = JsonPhoneticsProvider(records_dir=str(records_dir))
    assert prov.get("../foo", "x") is None
    assert prov.get("..", "x") is None
    assert prov.get(".", "x") is None
    assert prov.get("a/b", "x") is None


def test_get_still_resolves_normal_id(tmp_path):
    _write(tmp_path, "es/es-u1-l1-e1.json", {
        "lang": "es", "phones": ["a"], "ids": [5],
        "words": [], "coverage": 1.0, "unknown": [], "espeak_voice": "es-419",
    })
    prov = JsonPhoneticsProvider(records_dir=str(tmp_path))
    rec = prov.get("es", "es-u1-l1-e1")
    assert rec is not None
    assert rec["ids"] == [5]