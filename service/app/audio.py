"""Download an attempt and transcode to the 16 kHz mono 16-bit PCM WAV the
engine requires. Raises on any failure; the caller maps exceptions to the
'audio_unreachable' / 'unscoreable' status flags (never to student penalty)."""
import os
import subprocess
import tempfile

import httpx


def download_and_normalize(audio_url: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    fd, in_path = tempfile.mkstemp(suffix=".bin", dir=dest_dir)
    os.close(fd)
    wav_path = in_path.rsplit(".", 1)[0] + ".wav"
    try:
        with httpx.stream("GET", audio_url, timeout=30.0, follow_redirects=True) as r:
            r.raise_for_status()
            with open(in_path, "wb") as f:
                for chunk in r.iter_raw():
                    f.write(chunk)
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", in_path, "-ac", "1", "-ar", "16000",
             "-sample_fmt", "s16", wav_path],
            check=True,
        )
        return wav_path
    except Exception:
        if os.path.exists(wav_path):
            os.remove(wav_path)
        raise
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)