import io
import importlib
import types
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # app.config reads JINGO_ENGINE_MODEL_DIR / WEBWORK_JWT_SECRET at import
    # time (fail-fast in production, see app/config.py). Set them before the
    # first import of app.main in this test session -- same per-fixture
    # pattern test_score_endpoint.py uses (no shared conftest in this suite).
    monkeypatch.setenv("JINGO_ENGINE_MODEL_DIR", "/tmp/jingo-test-model")
    monkeypatch.setenv("WEBWORK_JWT_SECRET", "test-secret")

    from app import main
    importlib.reload(main)

    # Stub engine + provider so no model/ffmpeg is needed.
    # NOTE: brief specified `main._engine = object()`, but a plain object()
    # instance has no __dict__ and cannot have attributes set (even with
    # monkeypatch's raising=False) -- SimpleNamespace() is the standard,
    # semantics-preserving fix: non-None, mockable, same intent.
    main._engine = types.SimpleNamespace()
    monkeypatch.setattr(main._provider, "get",
                        lambda lang, ex: {"phones": ["k"]} if ex == "known" else None)
    monkeypatch.setattr(main, "normalize_upload", lambda data, d, s: "/tmp/fake.wav")
    monkeypatch.setattr(
        main._engine, "score_exercise",
        lambda *a, **k: {"overall": 82.0, "weak_tags": ["r"],
                         "phoneme_scores": [{"phoneme": "k", "score": 90}]},
        raising=False)
    import os
    monkeypatch.setattr(os.path, "exists", lambda p: False)  # skip cleanup unlink
    return TestClient(main.app)


def _post(client, exercise="known"):
    return client.post("/practice-score",
                       files={"audio": ("a.mp3", io.BytesIO(b"x"), "audio/mpeg")},
                       data={"exercise_id": exercise, "language": "es"})


def test_scored_feedback_no_jwt(client):
    r = _post(client)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "scored" and body["overall"] == 82.0
    assert body["phoneme_scores"][0]["phoneme"] == "k"
    assert "answerJWT" not in body


def test_unknown_exercise_404(client):
    assert _post(client, exercise="nope").status_code == 404


def test_oversized_upload_413(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1)
    r = client.post("/practice-score",
                    files={"audio": ("a.mp3", io.BytesIO(b"toolong"), "audio/mpeg")},
                    data={"exercise_id": "known", "language": "es"})
    assert r.status_code == 413


def test_rate_limit_429(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "PRACTICE_RATE_MAX", 2)
    from app import main
    main._practice_hits.clear()
    assert _post(client).status_code == 200
    assert _post(client).status_code == 200
    assert _post(client).status_code == 429
