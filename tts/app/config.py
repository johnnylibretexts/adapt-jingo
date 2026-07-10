"""Configuration for the jingo-tts 'Hear it' service.

All values come from the environment so the same image runs in dev and on the
box without code changes (mirrors the jingo scorer's config module).

The synthesis engine is pluggable (see provider.py): the default is Kokoro
(Apache-2.0, natural multilingual voices); Piper is kept as a lightweight
alternative. Selected via TTS_ENGINE."""
import json
import os

# Which synthesis backend: "kokoro" (default), "piper", "gemini", or "polly".
TTS_ENGINE = os.environ.get("TTS_ENGINE", "kokoro")

# --- Gemini (proprietary Google cloud engine; opt-in) ---
# Runtime synthesis needs GEMINI_API_KEY; without it the service is cache-only
# (serves pre-generated clips, 503 on a miss). Language is auto-detected.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Zephyr")
# Prompt template; Gemini voices only the quoted text (per the docs' "Say
# <style>: '<text>'" pattern). Naming the language stops it reading a lone word
# with an English accent; "{lang_name}" / "{text}" are filled per request.
GEMINI_STYLE = os.environ.get(
    "GEMINI_STYLE",
    'Pronounce this clearly and naturally in {lang_name}, exactly as a native '
    'speaker would say it — not spelled out or broken into separate syllables: '
    '"{text}"',
)
# ADAPT language code -> language name used in the prompt.
GEMINI_LANG_NAMES = json.loads(
    os.environ.get("GEMINI_LANG_NAMES", '{"es": "Spanish", "fr": "French"}')
)

# --- Amazon Polly (proprietary AWS cloud engine; opt-in) ---
# Runtime synthesis needs AWS creds (an IAM key PAIR, not a single API key);
# without them the service is cache-only. Unlike Gemini's preview model, Polly
# has real production quotas, so bulk single-word generation isn't rate-capped.
# es-MX generative voices: Mia (F), Andrés (M); available in us-west-2.
POLLY_ACCESS_KEY_ID = os.environ.get("POLLY_ACCESS_KEY_ID", "")
POLLY_SECRET_ACCESS_KEY = os.environ.get("POLLY_SECRET_ACCESS_KEY", "")
POLLY_REGION = os.environ.get("POLLY_REGION", "us-west-2")
# Engine tier: "generative" (most natural), "neural", or "standard".
POLLY_ENGINE = os.environ.get("POLLY_ENGINE", "generative")
# Default voice + per-language voice/lang-code maps (ADAPT lang -> Polly).
POLLY_VOICE = os.environ.get("POLLY_VOICE", "Mia")
POLLY_VOICES = json.loads(os.environ.get("POLLY_VOICES", '{"es": "Mia", "fr": "Lea"}'))
POLLY_LANG_CODES = json.loads(
    os.environ.get("POLLY_LANG_CODES", '{"es": "es-MX", "fr": "fr-FR"}')
)
# Polly PCM output is 8k/16k only; 16k is wideband speech — plenty for a word.
POLLY_SAMPLE_RATE = int(os.environ.get("POLLY_SAMPLE_RATE", "16000"))

# --- Kokoro (default engine) ---
# Model + combined voice pack (mounted at runtime; not baked into the image).
KOKORO_MODEL_PATH = os.environ.get(
    "KOKORO_MODEL_PATH", "/opt/libretexts/tts/kokoro/kokoro-v1.0.onnx"
)
KOKORO_VOICES_PATH = os.environ.get(
    "KOKORO_VOICES_PATH", "/opt/libretexts/tts/kokoro/voices-v1.0.bin"
)
# Map of language code -> Kokoro voice name. Kokoro voice ids encode language
# (e=Spanish, f=French, a=American English, ...) + gender (f/m). One combined
# voice pack covers all languages, so adding a language is just a map entry.
KOKORO_VOICES = json.loads(
    os.environ.get("KOKORO_VOICES", '{"es": "ef_dora", "fr": "ff_siwis"}')
)
# ADAPT language code -> Kokoro/espeak language code (they differ: ADAPT uses
# "fr" but espeak wants "fr-fr"; Spanish is "es" for both). Extend as needed.
KOKORO_LANG_CODES = json.loads(
    os.environ.get("KOKORO_LANG_CODES", '{"es": "es", "fr": "fr-fr"}')
)

# --- Piper (optional alternative engine) ---
PIPER_VOICE_DIR = os.environ.get("PIPER_VOICE_DIR", "/opt/libretexts/tts/voices")
PIPER_VOICES = json.loads(
    os.environ.get("PIPER_VOICES", '{"es": "es_MX-ald-medium"}')
)

# Fallback language used when a request's lang has no configured voice.
DEFAULT_LANG = os.environ.get("TTS_DEFAULT_LANG", "es")

# On-disk cache of synthesized MP3s (one file per engine+voice+text). Persisted
# across restarts so a given word is only ever synthesized once.
CACHE_DIR = os.environ.get("TTS_CACHE_DIR", "/opt/libretexts/tts/cache")

# CORS origin allowed to call /say (the ADAPT app). "*" is fine for a read-only
# TTS endpoint but set it to the ADAPT origin in production.
ALLOWED_ORIGIN = os.environ.get("TTS_ALLOWED_ORIGIN", "*")

# Reject anything longer than this many characters (a word/short phrase tool,
# not a document reader). Guards CPU + cache from abuse.
MAX_CHARS = int(os.environ.get("TTS_MAX_CHARS", "200"))

# MP3 bitrate for the encoded clips.
MP3_KBPS = os.environ.get("TTS_MP3_KBPS", "96")

# Playback shaping. A single word at full speed sounds rushed for a learner, so
# we slow synthesis and add a little silence around the clip. These values are
# part of the cache key, so changing them transparently invalidates old clips.
SPEED = float(os.environ.get("TTS_SPEED", "0.8"))        # <1 = slower, clearer
PAD_LEAD_S = float(os.environ.get("TTS_PAD_LEAD_S", "0.12"))   # silence before
PAD_TRAIL_S = float(os.environ.get("TTS_PAD_TRAIL_S", "0.30"))  # silence after

# Post-synthesis playback tempo applied to EVERY engine's audio via ffmpeg
# `atempo` (pitch-preserving — it slows the delivery without deepening the voice).
# 1.0 = unchanged; <1 = slower/clearer for a learner (e.g. 0.9 = 10% slower).
# Engines like Polly's generative voice don't reliably honour SSML <prosody rate>,
# so we shape tempo here uniformly. Part of the cache key, so changing it
# transparently invalidates old clips. Valid ffmpeg atempo range is 0.5–100.
RATE = float(os.environ.get("TTS_RATE", "1.0"))
