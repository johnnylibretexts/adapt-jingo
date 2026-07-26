"""Download an attempt and transcode to the 16 kHz mono 16-bit PCM WAV the
engine requires. Raises on any failure; the caller maps exceptions to the
'audio_unreachable' / 'unscoreable' status flags (never to student penalty)."""
import os
import subprocess
import tempfile
from urllib.parse import urlsplit

import httpx


class AudioFetchError(Exception):
    """Raised for any failure fetching/preparing audio -- including SSRF
    guard rejections -- so main.py's existing except Exception -> map to
    'audio_unreachable' keeps working unchanged."""


# Resource caps for the download path. Read from the environment here (rather
# than threaded through the signature) so existing callers and their test
# monkeypatches keep working -- same idiom _guard_audio_url already uses.
# JINGO_ENGINE_MAX_AUDIO_SECONDS is the same var config.MAX_AUDIO_SECONDS reads.
_MAX_DOWNLOAD_BYTES = int(os.environ.get("JINGO_MAX_DOWNLOAD_BYTES", str(25_000_000)))
_MAX_AUDIO_SECONDS = float(os.environ.get("JINGO_ENGINE_MAX_AUDIO_SECONDS", "20"))
_FFMPEG_TIMEOUT_S = float(os.environ.get("JINGO_FFMPEG_TIMEOUT_S", "60"))


def _guard_audio_url(audio_url: str) -> None:
    """SSRF guard, run before any network I/O.

    - Always rejects non-http(s) schemes (file:, ftp:, gopher:, data:, ...).
      This is safe and non-breaking: real audio_urls are always http(s).
    - Optionally restricts to a host allowlist via JINGO_AUDIO_HOST_ALLOWLIST
      (comma-separated hostnames). Unset/empty = allow any host, which is the
      default and preserves current behavior against the internal minio host
      on the docker network -- do NOT block private/internal hosts by default.
    """
    parts = urlsplit(audio_url)
    if parts.scheme not in ("http", "https"):
        raise AudioFetchError(f"rejected non-http(s) scheme: {parts.scheme!r}")

    allowlist_env = os.environ.get("JINGO_AUDIO_HOST_ALLOWLIST", "")
    allowlist = [h.strip() for h in allowlist_env.split(",") if h.strip()]
    if allowlist and parts.hostname not in allowlist:
        raise AudioFetchError(f"rejected host not in allowlist: {parts.hostname!r}")


def download_and_normalize(audio_url: str, dest_dir: str) -> str:
    _guard_audio_url(audio_url)
    os.makedirs(dest_dir, exist_ok=True)
    fd, in_path = tempfile.mkstemp(suffix=".bin", dir=dest_dir)
    os.close(fd)
    wav_path = in_path.rsplit(".", 1)[0] + ".wav"
    try:
        # follow_redirects=False: _guard_audio_url only vets the URL we were
        # given. With automatic redirects an allowlisted origin could bounce us
        # to an internal host and the guard would never see the final target.
        with httpx.stream("GET", audio_url, timeout=30.0, follow_redirects=False) as r:
            r.raise_for_status()
            # Early exit on a declared oversized body, before reading any of it.
            # The streaming counter below is the real guard (Content-Length is
            # absent on chunked responses and can lie), but this avoids pulling
            # an obviously-too-large body into memory one chunk at a time.
            declared = r.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > _MAX_DOWNLOAD_BYTES:
                raise AudioFetchError(
                    f"audio exceeds {_MAX_DOWNLOAD_BYTES} bytes")
            # Cap the streamed body: the URL is remote and only partially
            # trusted, so an oversized/endless response must not fill /tmp.
            written = 0
            with open(in_path, "wb") as f:
                for chunk in r.iter_raw():
                    written += len(chunk)
                    if written > _MAX_DOWNLOAD_BYTES:
                        raise AudioFetchError(
                            f"audio exceeds {_MAX_DOWNLOAD_BYTES} bytes")
                    f.write(chunk)
        try:
            subprocess.run(
                # Mirrors normalize_upload's hardening:
                # -protocol_whitelist keeps a crafted playlist/concat input from
                #   reaching back out over the network; -t hard-caps the OUTPUT
                #   duration so a decompression bomb can't write a huge WAV.
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-protocol_whitelist", "file,pipe", "-i", in_path,
                 "-t", str(_MAX_AUDIO_SECONDS + 1),
                 "-ac", "1", "-ar", "16000",
                 "-sample_fmt", "s16", wav_path],
                check=True,
                timeout=_FFMPEG_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise AudioFetchError(f"ffmpeg timed out after {_FFMPEG_TIMEOUT_S}s")
        # Same belt-and-braces check normalize_upload does: ffmpeg can exit 0
        # without writing the output (e.g. a demux failure that doesn't set a
        # non-zero status). Returning a nonexistent path would surface as an
        # unexpected exception in the caller instead of 'audio_unreachable'.
        if not os.path.exists(wav_path):
            raise AudioFetchError("ffmpeg produced no output")
        # -t caps the transcode at max+1s; verify the result like
        # normalize_upload does, so an over-length clip cannot reach the engine.
        seconds = os.path.getsize(wav_path) / (16000 * 2)
        if seconds > _MAX_AUDIO_SECONDS:
            raise AudioFetchError(
                f"audio too long: {seconds:.1f}s > {_MAX_AUDIO_SECONDS}s")
        return wav_path
    except Exception:
        if os.path.exists(wav_path):
            os.remove(wav_path)
        raise
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)


def normalize_upload(data: bytes, dest_dir: str, max_seconds: float) -> str:
    """Transcode uploaded audio bytes to 16 kHz mono 16-bit PCM WAV.

    Rejects empty input and anything longer than max_seconds. Raises
    AudioFetchError on any failure (caller maps to a 4xx). Mirrors
    download_and_normalize but takes bytes instead of a URL — no network I/O."""
    if not data:
        raise AudioFetchError("empty audio upload")
    os.makedirs(dest_dir, exist_ok=True)
    fd, in_path = tempfile.mkstemp(suffix=".bin", dir=dest_dir)
    os.close(fd)
    wav_path = in_path.rsplit(".", 1)[0] + ".wav"
    try:
        with open(in_path, "wb") as f:
            f.write(data)
        proc = subprocess.run(
            # -protocol_whitelist: attacker-controlled input can't make a
            #   playlist/concat demuxer reach out beyond a local file.
            # -t: hard-cap the OUTPUT duration so a decompression bomb can't
            #   write a huge WAV before the post-transcode length check.
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-protocol_whitelist", "file,pipe", "-i", in_path,
             "-t", str(max_seconds + 1),
             "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", wav_path],
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT_S,
        )
        if proc.returncode != 0 or not os.path.exists(wav_path):
            raise AudioFetchError("could not decode audio")
        seconds = os.path.getsize(wav_path) / (16000 * 2)  # 16k samples/s * 2 bytes
        if seconds > max_seconds:
            raise AudioFetchError(f"audio too long: {seconds:.1f}s > {max_seconds}s")
        return wav_path
    except AudioFetchError:
        if os.path.exists(wav_path):
            os.remove(wav_path)
        raise
    except Exception as exc:
        if os.path.exists(wav_path):
            os.remove(wav_path)
        raise AudioFetchError(str(exc))
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)