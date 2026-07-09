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


def _f32_to_mp3(samples: "np.ndarray", sample_rate: int) -> bytes:
    """Encode mono float32 [-1,1] samples to MP3 via ffmpeg (no temp files)."""
    pcm = np.asarray(samples, dtype=np.float32).tobytes()
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
            "-f", "mp3", "-b:a", f"{config.MP3_KBPS}k", "pipe:1",
        ],
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


@app.get("/say")
def say(
    text: str = Query(..., description="Word or short phrase to speak"),
    lang: str = Query("es", description="Language code (es, fr, ...)"),
):
    """Return an MP3 of `text` spoken in `lang`. Cached on disk per engine+voice+text."""
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")
    if len(text) > config.MAX_CHARS:
        raise HTTPException(status_code=413, detail="text too long")
    if not _provider.available:
        raise HTTPException(status_code=503, detail="tts engine unavailable")

    voice_id = _provider.voice_id(lang) or "default"
    key = hashlib.sha256(
        f"{config.TTS_ENGINE}|{voice_id}|{text}".encode("utf-8")
    ).hexdigest()
    path = os.path.join(config.CACHE_DIR, key + ".mp3")

    if not os.path.exists(path):
        try:
            samples, sample_rate = _provider.synthesize(text, lang)
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
