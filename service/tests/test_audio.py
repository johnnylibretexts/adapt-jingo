import struct, wave
import pytest
from app.audio import download_and_normalize, AudioFetchError


def _make_wav(path, sr=44100, channels=2, sample_fmt="s16"):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2 if sample_fmt == "s16" else 3)
        w.setframerate(sr)
        frames = b"".join(struct.pack("<h", 1000) for _ in range(sr // 10))
        w.writeframes(frames)


def test_normalize_produces_16k_mono_s16(monkeypatch, tmp_path):
    src = tmp_path / "stereo.wav"
    _make_wav(src, sr=44100, channels=2)

    # stub httpx so "download" = copy the local file
    import app.audio as A
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_raw(self):
            with open(src, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk: break
                    yield chunk
    monkeypatch.setattr(A.httpx, "stream", lambda method, url, **kw: _Resp())

    # http(s) URL -- the SSRF scheme guard only blocks non-http(s) schemes;
    # this is otherwise the same fake-download-via-httpx-stub as before.
    wav = download_and_normalize("http://minio:9000/bucket/x.bin", str(tmp_path / "out"))
    with wave.open(wav, "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2


def test_rejects_non_http_scheme_before_any_fetch(monkeypatch, tmp_path):
    import app.audio as A
    # if the guard didn't run first, this stub would raise AssertionError
    # instead of the expected AudioFetchError -- proving no fetch is attempted.
    def _boom(method, url, **kw):
        raise AssertionError("must not fetch for a rejected scheme")
    monkeypatch.setattr(A.httpx, "stream", _boom)

    with pytest.raises(AudioFetchError):
        download_and_normalize("file:///etc/passwd", str(tmp_path / "out"))


def test_host_allowlist_blocks_and_allows(monkeypatch, tmp_path):
    import app.audio as A
    monkeypatch.setenv("JINGO_AUDIO_HOST_ALLOWLIST", "minio")

    def _boom(method, url, **kw):
        raise AssertionError("must not fetch a host outside the allowlist")
    monkeypatch.setattr(A.httpx, "stream", _boom)

    with pytest.raises(AudioFetchError):
        download_and_normalize("http://evil.example.com/a.mp3", str(tmp_path / "out"))

    # allowed host: guard passes, so we reach (and stub) the actual fetch
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_raw(self): return iter([b"\x00\x00"])
    monkeypatch.setattr(A.httpx, "stream", lambda method, url, **kw: _Resp())
    monkeypatch.setattr(A, "subprocess", type("S", (), {"run": staticmethod(lambda *a, **kw: None)}))
    wav = download_and_normalize("http://minio:9000/bucket/x.bin", str(tmp_path / "out"))
    assert wav.endswith(".wav")


def test_no_allowlist_env_allows_any_host(monkeypatch, tmp_path):
    # default (unset/empty) behavior: any host is allowed -- this preserves
    # current production behavior against the internal minio host.
    import app.audio as A
    monkeypatch.delenv("JINGO_AUDIO_HOST_ALLOWLIST", raising=False)

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_raw(self): return iter([b"\x00\x00"])
    monkeypatch.setattr(A.httpx, "stream", lambda method, url, **kw: _Resp())
    monkeypatch.setattr(A, "subprocess", type("S", (), {"run": staticmethod(lambda *a, **kw: None)}))
    wav = download_and_normalize("http://10.0.0.5:9000/bucket/x.bin", str(tmp_path / "out"))
    assert wav.endswith(".wav")