"""Tests for the jingo-tts /say endpoint.

The real TTS provider + ffmpeg are stubbed so the suite runs with no model
download and no audio backend — we exercise validation, caching, and the
lang->voice fallback, not the synthesis engine itself."""
import importlib
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient


class FakeProvider:
    """Stand-in for KokoroProvider/PiperProvider."""

    def __init__(self):
        self.available = True
        self.languages = ["es", "fr"]
        self.voices = {"es": "ef_dora", "fr": "ff_siwis"}
        self.calls = 0

    def voice_id(self, lang, voice=None):
        return voice or self.voices.get(lang) or self.voices["es"]

    def synthesize(self, text, lang, voice=None):
        self.calls += 1
        return np.zeros(100, dtype=np.float32), 24000


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "cache"))
    from app import config, main
    importlib.reload(config)
    importlib.reload(main)

    fake = FakeProvider()
    main._provider = fake
    monkeypatch.setattr(main, "_f32_to_mp3", lambda s, sr: b"ID3-fake-mp3")

    c = TestClient(main.app)
    c._provider = fake
    c._main = main
    return c


def test_health_reports_engine_and_langs(client):
    body = client.get("/health").json()
    assert body["engine_available"] is True
    assert body["languages"] == ["es", "fr"]


def test_say_returns_mp3(client):
    r = client.get("/say", params={"text": "mesa", "lang": "es"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3-fake-mp3"


def test_say_caches_second_call(client):
    client.get("/say", params={"text": "mesa", "lang": "es"})
    client.get("/say", params={"text": "mesa", "lang": "es"})
    assert client._provider.calls == 1  # second served from disk cache


def test_cache_key_differs_by_lang(client):
    # Same text, different lang/voice -> synthesized separately.
    client.get("/say", params={"text": "salut", "lang": "es"})
    client.get("/say", params={"text": "salut", "lang": "fr"})
    assert client._provider.calls == 2


def test_say_rejects_empty_text(client):
    assert client.get("/say", params={"text": "   ", "lang": "es"}).status_code == 400


def test_say_rejects_overlong_text(client):
    assert client.get("/say", params={"text": "a" * 5000, "lang": "es"}).status_code == 413


def test_say_503_when_engine_unavailable(client):
    client._provider.available = False
    assert client.get("/say", params={"text": "mesa", "lang": "es"}).status_code == 503


def test_polly_provider_inert_without_creds(monkeypatch):
    """TTS_ENGINE=polly builds the Polly engine; with no AWS creds it is inert
    (available False, cache-only) rather than crashing the service."""
    monkeypatch.setenv("TTS_ENGINE", "polly")
    monkeypatch.delenv("POLLY_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("POLLY_SECRET_ACCESS_KEY", raising=False)
    import app.config as config
    import app.provider as provider
    importlib.reload(config)
    importlib.reload(provider)
    p = provider.build_provider()
    assert type(p).__name__ == "PollyProvider"
    assert p.available is False
    assert p.voice_id("es") == "Mia"
    assert config.POLLY_LANG_CODES["es"] == "es-MX"


def test_polly_cache_key_distinct_from_gemini(tmp_path, monkeypatch):
    """A Polly clip must not collide with a Gemini clip for the same word, and
    switching engine tier (generative<->neural) must invalidate the key."""
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "cache"))
    from app import config, main
    importlib.reload(config)
    importlib.reload(main)
    monkeypatch.setattr(config, "TTS_ENGINE", "polly")
    monkeypatch.setattr(config, "POLLY_ENGINE", "generative")
    gen = main._clip_path("Mia", "es", "hola")
    monkeypatch.setattr(config, "POLLY_ENGINE", "neural")
    neu = main._clip_path("Mia", "es", "hola")
    monkeypatch.setattr(config, "TTS_ENGINE", "gemini")
    gemini = main._clip_path("Mia", "es", "hola")
    assert gen != neu != gemini and gen != gemini


def test_rate_changes_cache_key(tmp_path, monkeypatch):
    """A tempo change (TTS_RATE) is post-processing that alters the audio, so it
    must invalidate the clip's cache key; 1.0 is the un-suffixed baseline."""
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "cache"))
    from app import config, main
    importlib.reload(config)
    importlib.reload(main)
    monkeypatch.setattr(config, "RATE", 1.0)
    base = main._clip_path("Mia", "es", "hola")
    monkeypatch.setattr(config, "RATE", 0.9)
    slow = main._clip_path("Mia", "es", "hola")
    monkeypatch.setattr(config, "RATE", 0.8)
    slower = main._clip_path("Mia", "es", "hola")
    assert base != slow != slower and base != slower


def test_shaping_changes_cache_key(tmp_path, monkeypatch):
    """config.py documents SPEED/PAD as part of the key: they change the audio
    bytes, so altering them must invalidate old clips. Default values stay
    un-suffixed so already-cached clips keep their key."""
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "cache"))
    from app import config, main
    importlib.reload(config)
    importlib.reload(main)

    base = main._clip_path("Mia", "es", "hola")

    monkeypatch.setattr(config, "SPEED", config.DEFAULT_SPEED + 0.1)
    assert main._clip_path("Mia", "es", "hola") != base
    monkeypatch.setattr(config, "SPEED", config.DEFAULT_SPEED)
    assert main._clip_path("Mia", "es", "hola") == base

    monkeypatch.setattr(config, "PAD_LEAD_S", config.DEFAULT_PAD_LEAD_S + 0.05)
    assert main._clip_path("Mia", "es", "hola") != base
    monkeypatch.setattr(config, "PAD_LEAD_S", config.DEFAULT_PAD_LEAD_S)

    monkeypatch.setattr(config, "PAD_TRAIL_S", config.DEFAULT_PAD_TRAIL_S + 0.05)
    assert main._clip_path("Mia", "es", "hola") != base


def test_cache_place_script_key_matches_service(tmp_path, monkeypatch):
    """The build-time placement script and the service must derive identical
    keys — they previously each had their own copy and drifted, so every clip
    the script placed on a Polly + TTS_RATE box was unreachable."""
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "cache"))
    from app import config, main
    from app.clip_key import clip_key
    importlib.reload(config)
    importlib.reload(main)
    monkeypatch.setattr(config, "TTS_ENGINE", "polly")
    monkeypatch.setattr(config, "POLLY_ENGINE", "generative")
    monkeypatch.setattr(config, "RATE", 0.9)

    service_path = main._clip_path("Mia", "es", "hola")
    script_key = clip_key("Mia", "es", "hola")
    assert os.path.basename(service_path) == script_key + ".mp3"
