"""jingo-tts — a tiny self-hosted text-to-speech service.

Purpose: give ADAPT's `pronunciation` question a "Hear it" button — an
exemplar (model) pronunciation a learner can listen to before recording their
own attempt. Open-source and self-hosted, mirroring the jingo scorer's
deployment shape; no proprietary cloud TTS.

The synthesis engine is pluggable (see provider.py); the default is Kokoro
(Apache-2.0, natural multilingual voices). Every synthesized clip is cached to
disk keyed by (engine, voice, text) so repeat plays are served as a static
file — the first request for a word synthesizes, the rest are ~instant."""
import hashlib
import logging
import os
import subprocess

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import config
from .provider import build_provider

logger = logging.getLogger("jingo-tts")
logging.basicConfig(level=logging.INFO)

_provider = build_provider()
os.makedirs(config.CACHE_DIR, exist_ok=True)

app = FastAPI(title="jingo-tts", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.ALLOWED_ORIGIN],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


def _pad(samples: "np.ndarray", sample_rate: int) -> "np.ndarray":
    """Add a little leading/trailing silence so a single word doesn't feel clipped."""
    lead = np.zeros(int(sample_rate * config.PAD_LEAD_S), dtype=np.float32)
    trail = np.zeros(int(sample_rate * config.PAD_TRAIL_S), dtype=np.float32)
    return np.concatenate([lead, np.asarray(samples, dtype=np.float32).squeeze(), trail])


def _f32_to_mp3(samples: "np.ndarray", sample_rate: int) -> bytes:
    """Encode mono float32 [-1,1] samples to MP3 via ffmpeg (no temp files)."""
    pcm = np.asarray(samples, dtype=np.float32).tobytes()
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
    ]
    # Slow (or speed) delivery without changing pitch, for learner clarity.
    if abs(config.RATE - 1.0) > 1e-3:
        cmd += ["-filter:a", f"atempo={config.RATE:.3f}"]
    cmd += ["-f", "mp3", "-b:a", f"{config.MP3_KBPS}k", "pipe:1"]
    proc = subprocess.run(
        cmd,
        input=pcm,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:200])
    return proc.stdout


@app.get("/health")
def health():
    return {
        "engine": config.TTS_ENGINE,
        "engine_available": _provider.available,
        "languages": _provider.languages,
    }


def _clip_path(voice_id: str, lang: str, text: str) -> str:
    # Cache key = version + engine + voice + lang + text (+ style for gemini, so
    # tweaking the style prompt transparently invalidates old clips).
    render = ""
    if config.TTS_ENGINE == "gemini":
        render = "|" + hashlib.sha256(config.GEMINI_STYLE.encode("utf-8")).hexdigest()[:8]
    elif config.TTS_ENGINE == "polly":
        # engine tier is part of the voice's sound, so a generative<->neural
        # switch must invalidate old clips.
        render = "|" + config.POLLY_ENGINE
    # Tempo is post-processing that changes the audio, so it belongs in the key.
    if abs(config.RATE - 1.0) > 1e-3:
        render += f"|r{config.RATE:.3f}"
    sig = f"v2|{config.TTS_ENGINE}|{voice_id}|{lang}{render}|{text}"
    key = hashlib.sha256(sig.encode("utf-8")).hexdigest()
    return os.path.join(config.CACHE_DIR, key + ".mp3")


@app.get("/say")
def say(
    text: str = Query(..., description="Word or short phrase to speak"),
    lang: str = Query("es", description="Language code (es, fr, ...)"),
    voice: str = Query(None, description="Override the default voice (for A/B sampling)"),
):
    """Return an MP3 of `text` spoken in `lang`. Served from the disk cache when
    present (so a keyless box still serves pre-generated clips); otherwise
    synthesized on demand if the engine is available."""
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")
    if len(text) > config.MAX_CHARS:
        raise HTTPException(status_code=413, detail="text too long")

    voice_id = _provider.voice_id(lang, voice) or "default"
    path = _clip_path(voice_id, lang, text)

    if not os.path.exists(path):
        if not _provider.available:
            raise HTTPException(status_code=503, detail="tts engine unavailable and clip not cached")
        try:
            samples, sample_rate = _provider.synthesize(text, lang, voice)
            # A leading buffer keeps the very first consonant (e.g. the "p" in
            # "perro") from being clipped; trailing silence rounds it off.
            samples = _pad(samples, sample_rate)
            mp3 = _f32_to_mp3(samples, sample_rate)
        except Exception as exc:
            logger.error("synthesis failed for %r (%s): %s", text, lang, exc)
            raise HTTPException(status_code=500, detail="synthesis failed")
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(mp3)
        os.replace(tmp, path)  # atomic publish so concurrent readers never see a partial file

    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
