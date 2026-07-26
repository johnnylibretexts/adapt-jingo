import struct, subprocess, wave
import pytest
from app.audio import download_and_normalize, AudioFetchError


class _StubResp:
    """Minimal httpx.stream stand-in yielding fixed chunks."""

    headers = {}

    def __init__(self, chunks):
        self._chunks = chunks

    def __enter__(self): return self
    def __exit__(self, *a): pass
    def raise_for_status(self): pass
    def iter_raw(self): return iter(self._chunks)


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
        headers = {}  # real httpx responses always carry headers
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
        headers = {}  # real httpx responses always carry headers
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_raw(self): return iter([b"\x00\x00"])
    monkeypatch.setattr(A.httpx, "stream", lambda method, url, **kw: _Resp())
    # the stub must actually produce the output file: download_and_normalize
    # now verifies ffmpeg wrote something rather than trusting exit status.
    monkeypatch.setattr(A, "subprocess", type("S", (), {
        "run": staticmethod(lambda cmd, **kw: open(cmd[-1], "wb").close()),
        "TimeoutExpired": subprocess.TimeoutExpired,
    }))
    wav = download_and_normalize("http://minio:9000/bucket/x.bin", str(tmp_path / "out"))
    assert wav.endswith(".wav")


def test_download_rejects_oversized_body(monkeypatch, tmp_path):
    # The remote body is only partially trusted: an oversized/endless response
    # must be cut off mid-stream rather than being allowed to fill /tmp.
    import app.audio as A
    monkeypatch.setattr(A, "_MAX_DOWNLOAD_BYTES", 10)
    monkeypatch.setattr(A.httpx, "stream",
                        lambda m, u, **kw: _StubResp([b"x" * 8, b"x" * 8]))

    def _boom(*a, **kw):
        raise AssertionError("must not transcode an over-cap download")
    monkeypatch.setattr(A.subprocess, "run", _boom)

    with pytest.raises(AudioFetchError):
        download_and_normalize("http://minio:9000/bucket/x.bin", str(tmp_path / "out"))


def test_download_ffmpeg_timeout_maps_to_audiofetcherror(monkeypatch, tmp_path):
    # A hung ffmpeg must surface as AudioFetchError so main.py's handler maps it
    # to 'audio_unreachable' (completion credit) rather than wedging the worker.
    import app.audio as A
    monkeypatch.setattr(A.httpx, "stream",
                        lambda m, u, **kw: _StubResp([b"\x00\x00"]))

    def _timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)
    monkeypatch.setattr(A.subprocess, "run", _timeout)

    with pytest.raises(AudioFetchError):
        download_and_normalize("http://minio:9000/bucket/x.bin", str(tmp_path / "out"))


def test_download_ffmpeg_invocation_is_hardened(monkeypatch, tmp_path):
    # Same hardening normalize_upload already had: restricted protocols, a
    # capped output duration, and a finite subprocess timeout.
    import app.audio as A
    captured = {}
    monkeypatch.setattr(A.httpx, "stream",
                        lambda m, u, **kw: _StubResp([b"\x00\x00"]))

    def _run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        open(cmd[-1], "wb").close()  # ffmpeg would have written the wav
        return None
    monkeypatch.setattr(A.subprocess, "run", _run)

    download_and_normalize("http://minio:9000/bucket/x.bin", str(tmp_path / "out"))

    cmd = captured["cmd"]
    assert "-protocol_whitelist" in cmd
    assert cmd[cmd.index("-protocol_whitelist") + 1] == "file,pipe"
    assert "-t" in cmd
    assert captured["kw"].get("timeout")


def test_no_allowlist_env_allows_any_host(monkeypatch, tmp_path):
    # default (unset/empty) behavior: any host is allowed -- this preserves
    # current production behavior against the internal minio host.
    import app.audio as A
    monkeypatch.delenv("JINGO_AUDIO_HOST_ALLOWLIST", raising=False)

    class _Resp:
        headers = {}  # real httpx responses always carry headers
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_raw(self): return iter([b"\x00\x00"])
    monkeypatch.setattr(A.httpx, "stream", lambda method, url, **kw: _Resp())
    # the stub must actually produce the output file: download_and_normalize
    # now verifies ffmpeg wrote something rather than trusting exit status.
    monkeypatch.setattr(A, "subprocess", type("S", (), {
        "run": staticmethod(lambda cmd, **kw: open(cmd[-1], "wb").close()),
        "TimeoutExpired": subprocess.TimeoutExpired,
    }))
    wav = download_and_normalize("http://10.0.0.5:9000/bucket/x.bin", str(tmp_path / "out"))
    assert wav.endswith(".wav")

def test_download_rejects_declared_oversized_content_length(monkeypatch, tmp_path):
    # Early exit before reading the body at all, so an obviously-too-large
    # response is not pulled in chunk by chunk.
    import app.audio as A
    monkeypatch.setattr(A, "_MAX_DOWNLOAD_BYTES", 10)

    class _Resp(_StubResp):
        headers = {"content-length": "999999"}

        def iter_raw(self):
            raise AssertionError("must not read a declared-oversized body")

    monkeypatch.setattr(A.httpx, "stream", lambda m, u, **kw: _Resp([]))
    with pytest.raises(AudioFetchError):
        download_and_normalize("http://minio:9000/bucket/x.bin", str(tmp_path / "out"))


def test_download_errors_when_ffmpeg_exits_zero_without_output(monkeypatch, tmp_path):
    # ffmpeg can exit 0 without writing the WAV; returning that path would
    # surface as an unexpected exception rather than 'audio_unreachable'.
    import app.audio as A
    monkeypatch.setattr(A.httpx, "stream",
                        lambda m, u, **kw: _StubResp([b"\x00\x00"]))
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **kw: None)  # writes nothing
    with pytest.raises(AudioFetchError, match="no output"):
        download_and_normalize("http://minio:9000/bucket/x.bin", str(tmp_path / "out"))
