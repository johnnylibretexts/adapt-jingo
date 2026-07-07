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