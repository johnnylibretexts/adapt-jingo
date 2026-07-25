import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JINGO_ENGINE_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("WEBWORK_JWT_SECRET", "test-secret")
    monkeypatch.setenv("JINGO_RECORDS_DIR", str(tmp_path / "records"))
    monkeypatch.setenv("JINGO_ALLOWED_ORIGIN", "https://adapt.test")
    # import after env is set
    from app.main import app, _engine, _provider
    # Fix 2 (controller-resolved): rebind main._provider to a fresh provider
    # pointing at THIS test's tmp_path/records. Python caches app.main in
    # sys.modules after the first import, so the module-level _provider is
    # otherwise bound once to the first test's tmp_path and reused by all
    # later tests — causing tests 3-4 that plant records in their own
    # tmp_path to miss and return provider_miss instead of scored/audio_unreachable.
    from app import main as _main
    from app.provider import JsonPhoneticsProvider
    monkeypatch.setattr(_main, "_provider", JsonPhoneticsProvider(records_dir=str(tmp_path / "records")))
    yield TestClient(app)


def test_health_reports_contract_1_1(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["contract"] == "1.1"
    assert "engine_available" in body


def test_provider_miss_returns_completion_answerjwt(client, monkeypatch):
    # provider miss → status provider_miss, overall None, valid answerJWT
    # Fix 1 (user-approved): the client fixture leaves main._engine = None
    # (no wheel/model), so score() would return "engine_unavailable" before
    # the provider check. Monkeypatch _engine to a FakeEngine so the
    # engine-availability check passes and the provider_miss path is reachable.
    from app import main
    monkeypatch.setattr(main, "_engine", _FakeEngine(available=True, payload=None))
    r = client.post("/score", json={
        "problemJWT": "opaque", "exercise_id": "nope", "language": "es",
        "audio_url": "https://example.com/a.mp3",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"]["status"] == "provider_miss"
    assert body["feedback"]["overall"] is None
    assert body["feedback"]["provisional"] is True
    import jwt
    payload = jwt.decode(body["answerJWT"], "test-secret", algorithms=["HS256"])
    assert payload["problemJWT"] == "opaque"
    assert payload["score"]["status"] == "provider_miss"


def test_scored_round_trip(client, monkeypatch, tmp_path):
    # plant a record so provider.get hits, then monkeypatch the engine + audio
    import json, pathlib
    rec_dir = pathlib.Path(os.environ["JINGO_RECORDS_DIR"]) / "es"
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / "es-u1-l1-e1.json").write_text(json.dumps({
        "lang": "es", "phones": ["a", "l", "a"], "ids": [5, 31, 5],
        "words": [{"start": 0, "len": 3, "phones": ["a", "l", "a"]}],
        "coverage": 1.0, "unknown": [],
    }))

    from app import main
    monkeypatch.setattr(main, "_engine", _FakeEngine(available=True, payload={
        "overall": 86.4, "weak_tags": [], "provisional": True, "duration_s": 1.2,
        "contract_version": "1.1",
    }))
    monkeypatch.setattr(main, "download_and_normalize", lambda url, d: "/tmp/fake.wav")

    r = client.post("/score", json={
        "problemJWT": "opaque", "exercise_id": "es-u1-l1-e1", "language": "es",
        "audio_url": "https://example.com/a.mp3",
    })
    body = r.json()
    assert body["feedback"]["status"] == "scored"
    assert body["feedback"]["overall"] == 86.4
    assert body["feedback"]["exercise_id"] == "es-u1-l1-e1"


def test_audio_unreachable(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_engine", _FakeEngine(available=True, payload=None))
    def _raise(url, d):
        raise RuntimeError("404")
    monkeypatch.setattr(main, "download_and_normalize", _raise)
    # plant record so we get past provider miss
    import json, pathlib
    rec_dir = pathlib.Path(os.environ["JINGO_RECORDS_DIR"]) / "es"
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / "x.json").write_text(json.dumps({"phones": ["a"], "ids": [5], "words": [], "coverage": 1.0, "unknown": []}))
    r = client.post("/score", json={
        "problemJWT": "p", "exercise_id": "x", "language": "es",
        "audio_url": "https://example.com/missing.mp3",
    })
    assert r.json()["feedback"]["status"] == "audio_unreachable"


class _FakeEngine:
    def __init__(self, available, payload): self._available = available; self._payload = payload
    @property
    def available(self): return self._available
    def score_exercise(self, wav, lang, eid, provider): return self._payload