import struct, wave
from app.audio import download_and_normalize


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

    wav = download_and_normalize("file:///tmp/x", str(tmp_path / "out"))
    with wave.open(wav, "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2