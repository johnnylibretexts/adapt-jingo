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


def test_cleanup_deletes_temp_wav(monkeypatch, tmp_path):
    # Deliberately does NOT use the `client` fixture: that fixture globally
    # patches os.path.exists to False, which would make the cleanup path a
    # no-op and defeat the point of this test. Build a real engine/provider
    # stub here and let normalize_upload return a real file on disk so the
    # handler's `finally: os.remove(wav_path)` genuinely runs.
    monkeypatch.setenv("JINGO_ENGINE_MODEL_DIR", "/tmp/jingo-test-model")
    monkeypatch.setenv("WEBWORK_JWT_SECRET", "test-secret")

    from app import main
    importlib.reload(main)

    main._engine = types.SimpleNamespace()
    monkeypatch.setattr(main._provider, "get",
                        lambda lang, ex: {"phones": ["k"]} if ex == "known" else None)

    real_wav = tmp_path / "practice.wav"
    real_wav.write_bytes(b"RIFF....WAVEfmt ")
    monkeypatch.setattr(main, "normalize_upload",
                        lambda data, d, s: str(real_wav))
    monkeypatch.setattr(
        main._engine, "score_exercise",
        lambda *a, **k: {"overall": 82.0, "weak_tags": ["r"],
                         "phoneme_scores": [{"phoneme": "k", "score": 90}]},
        raising=False)

    test_client = TestClient(main.app)
    r = test_client.post("/practice-score",
                         files={"audio": ("a.mp3", io.BytesIO(b"x"), "audio/mpeg")},
                         data={"exercise_id": "known", "language": "es"})
    assert r.status_code == 200
    assert not real_wav.exists()


def test_engine_unavailable_503(client):
    from app import main
    main._engine = None
    r = _post(client)
    assert r.status_code == 503


def test_decode_failure_400(client, monkeypatch):
    from app import main, audio

    def _raise(data, d, s):
        raise audio.AudioFetchError("bad")

    monkeypatch.setattr(main, "normalize_upload", _raise)
    r = _post(client)
    assert r.status_code == 400
