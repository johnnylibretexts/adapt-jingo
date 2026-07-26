"""Single source of truth for the /say disk-cache key.

The runtime service (main.py) and the build-time cache-population script
(scripts/cache_place.py) MUST derive identical keys — a clip placed under a
different key is simply never found, and /say silently re-synthesizes or 503s.
They previously each had their own copy of this logic and drifted: the script's
copy never gained the Polly engine tier or the RATE component and hardcoded the
Gemini voice, so on a Polly + TTS_RATE box every placed clip missed.

Anything that changes the produced audio bytes belongs in the key, so changing
it transparently invalidates old clips. Shaping values are included only when
they differ from their defaults (the same idiom RATE uses), which preserves the
keys of clips already cached under default settings.
"""
import hashlib

from . import config


def clip_signature(voice_id: str, lang: str, text: str) -> str:
    """The pre-hash key string. Exposed separately so tests can assert on it."""
    render = ""
    if config.TTS_ENGINE == "gemini":
        # Tweaking the style prompt changes delivery, so it must rekey.
        render = "|" + hashlib.sha256(
            config.GEMINI_STYLE.encode("utf-8")).hexdigest()[:8]
    elif config.TTS_ENGINE == "polly":
        # Engine tier is part of the voice's sound, so a generative<->neural
        # switch must invalidate old clips.
        render = "|" + config.POLLY_ENGINE
    # Tempo is post-processing that changes the audio, so it belongs in the key.
    if abs(config.RATE - 1.0) > 1e-3:
        render += f"|r{config.RATE:.3f}"
    # Synthesis speed and the silence padded around the clip likewise change the
    # bytes; omitted at default values so existing cache entries keep their key.
    if abs(config.SPEED - config.DEFAULT_SPEED) > 1e-3:
        render += f"|s{config.SPEED:.3f}"
    if (abs(config.PAD_LEAD_S - config.DEFAULT_PAD_LEAD_S) > 1e-3
            or abs(config.PAD_TRAIL_S - config.DEFAULT_PAD_TRAIL_S) > 1e-3):
        render += f"|p{config.PAD_LEAD_S:.3f},{config.PAD_TRAIL_S:.3f}"
    return f"v2|{config.TTS_ENGINE}|{voice_id}|{lang}{render}|{text}"


def clip_key(voice_id: str, lang: str, text: str) -> str:
    """SHA-256 of the signature — the cache filename stem."""
    return hashlib.sha256(
        clip_signature(voice_id, lang, text).encode("utf-8")).hexdigest()
