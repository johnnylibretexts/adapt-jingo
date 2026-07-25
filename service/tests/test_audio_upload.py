import os
import pytest
from app import audio


def test_empty_upload_rejected(tmp_path):
    with pytest.raises(audio.AudioFetchError):
        audio.normalize_upload(b"", str(tmp_path), 20.0)


def test_decode_failure_rejected(tmp_path, monkeypatch):
    # ffmpeg "runs" but produces no wav -> AudioFetchError, temp cleaned up.
    class P:
        returncode = 1
        stderr = b"bad"
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(audio.AudioFetchError):
        audio.normalize_upload(b"not-audio", str(tmp_path), 20.0)


def test_over_length_rejected(tmp_path, monkeypatch):
    # ffmpeg "succeeds" and produces a wav that is too long -> rejected + removed.
    def fake_run(cmd, *a, **k):
        wav = cmd[-1]
        with open(wav, "wb") as f:
            f.write(b"\x00" * (16000 * 2 * 25))  # 25s of 16k/16-bit mono
        class P: returncode = 0; stderr = b""
        return P()
    monkeypatch.setattr(audio.subprocess, "run", fake_run)
    with pytest.raises(audio.AudioFetchError):
        audio.normalize_upload(b"x", str(tmp_path), 20.0)
    assert not any(p.suffix == ".wav" for p in tmp_path.iterdir())


def test_ok_returns_wav_path(tmp_path, monkeypatch):
    def fake_run(cmd, *a, **k):
        wav = cmd[-1]
        with open(wav, "wb") as f:
            f.write(b"\x00" * (16000 * 2 * 1))  # 1s
        class P: returncode = 0; stderr = b""
        return P()
    monkeypatch.setattr(audio.subprocess, "run", fake_run)
    out = audio.normalize_upload(b"x", str(tmp_path), 20.0)
    assert out.endswith(".wav") and os.path.exists(out)
